import io
import os
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, abort, jsonify, render_template, request, send_file


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_app(test_config=None):
    app = Flask(__name__)
    default_database = Path(app.instance_path) / "notes.db"
    app.config.from_mapping(
        DATABASE=os.environ.get("NOTES_DATABASE", str(default_database)),
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)

    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)

    def connect():
        connection = sqlite3.connect(app.config["DATABASE"])
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialise_database():
        with connect() as database:
            database.executescript(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL DEFAULT 'Untitled note',
                    content TEXT NOT NULL DEFAULT '',
                    pinned INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1)),
                    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE
                );

                CREATE TABLE IF NOT EXISTS note_tags (
                    note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
                    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                    PRIMARY KEY (note_id, tag_id)
                );

                CREATE INDEX IF NOT EXISTS notes_updated_at_idx ON notes(updated_at DESC);
                CREATE INDEX IF NOT EXISTS notes_archived_idx ON notes(archived);
                """
            )

    def note_as_dict(database, row):
        tags = database.execute(
            """
            SELECT tags.name FROM tags
            JOIN note_tags ON note_tags.tag_id = tags.id
            WHERE note_tags.note_id = ? ORDER BY tags.name COLLATE NOCASE
            """,
            (row["id"],),
        ).fetchall()
        result = dict(row)
        result["pinned"] = bool(result["pinned"])
        result["archived"] = bool(result["archived"])
        result["tags"] = [tag["name"] for tag in tags]
        return result

    def get_note(database, note_id):
        row = database.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        if row is None:
            abort(404)
        return row

    def normalise_tags(value):
        if isinstance(value, str):
            values = value.split(",")
        elif isinstance(value, list):
            values = value
        else:
            return []
        result = []
        seen = set()
        for item in values:
            tag = str(item).strip()[:40]
            key = tag.casefold()
            if tag and key not in seen:
                seen.add(key)
                result.append(tag)
        return result[:20]

    def replace_tags(database, note_id, tag_names):
        database.execute("DELETE FROM note_tags WHERE note_id = ?", (note_id,))
        for name in tag_names:
            database.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
            tag = database.execute(
                "SELECT id FROM tags WHERE name = ? COLLATE NOCASE", (name,)
            ).fetchone()
            database.execute(
                "INSERT INTO note_tags (note_id, tag_id) VALUES (?, ?)",
                (note_id, tag["id"]),
            )
        database.execute(
            "DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM note_tags)"
        )

    initialise_database()

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/notes")
    def list_notes():
        archived = 1 if request.args.get("archived") == "1" else 0
        search = request.args.get("q", "").strip()
        tag = request.args.get("tag", "").strip()
        sql = "SELECT DISTINCT notes.* FROM notes"
        parameters = []
        if tag:
            sql += " JOIN note_tags ON note_tags.note_id = notes.id JOIN tags ON tags.id = note_tags.tag_id"
        sql += " WHERE notes.archived = ?"
        parameters.append(archived)
        if search:
            sql += " AND (notes.title LIKE ? ESCAPE '\\' OR notes.content LIKE ? ESCAPE '\\')"
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            parameters.extend([f"%{escaped}%", f"%{escaped}%"])
        if tag:
            sql += " AND tags.name = ? COLLATE NOCASE"
            parameters.append(tag)
        sql += " ORDER BY notes.pinned DESC, notes.updated_at DESC"
        with connect() as database:
            rows = database.execute(sql, parameters).fetchall()
            return jsonify([note_as_dict(database, row) for row in rows])

    @app.post("/api/notes")
    def create_note():
        payload = request.get_json(silent=True) or {}
        now = utc_now()
        title = str(payload.get("title") or "Untitled note").strip()[:200] or "Untitled note"
        with connect() as database:
            cursor = database.execute(
                "INSERT INTO notes (title, content, created_at, updated_at) VALUES (?, '', ?, ?)",
                (title, now, now),
            )
            row = get_note(database, cursor.lastrowid)
            return jsonify(note_as_dict(database, row)), 201

    @app.get("/api/notes/<int:note_id>")
    def read_note(note_id):
        with connect() as database:
            return jsonify(note_as_dict(database, get_note(database, note_id)))

    @app.patch("/api/notes/<int:note_id>")
    def update_note(note_id):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return {"error": "Expected a JSON object."}, 400
        allowed = {"title", "content", "pinned", "archived", "tags"}
        if not (set(payload) & allowed):
            return {"error": "No supported fields were provided."}, 400
        with connect() as database:
            current = get_note(database, note_id)
            title = str(payload.get("title", current["title"])).strip()[:200] or "Untitled note"
            content = str(payload.get("content", current["content"]))[:1_000_000]
            pinned = int(bool(payload.get("pinned", current["pinned"])))
            archived = int(bool(payload.get("archived", current["archived"])))
            database.execute(
                "UPDATE notes SET title = ?, content = ?, pinned = ?, archived = ?, updated_at = ? WHERE id = ?",
                (title, content, pinned, archived, utc_now(), note_id),
            )
            if "tags" in payload:
                replace_tags(database, note_id, normalise_tags(payload["tags"]))
            return jsonify(note_as_dict(database, get_note(database, note_id)))

    @app.delete("/api/notes/<int:note_id>")
    def delete_note(note_id):
        with connect() as database:
            get_note(database, note_id)
            database.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        return Response(status=204)

    @app.get("/api/tags")
    def list_tags():
        with connect() as database:
            rows = database.execute(
                """
                SELECT tags.name, COUNT(note_tags.note_id) AS note_count
                FROM tags JOIN note_tags ON note_tags.tag_id = tags.id
                JOIN notes ON notes.id = note_tags.note_id
                WHERE notes.archived = 0
                GROUP BY tags.id ORDER BY tags.name COLLATE NOCASE
                """
            ).fetchall()
            return jsonify([dict(row) for row in rows])

    @app.get("/export/notes.zip")
    def export_notes():
        memory_file = io.BytesIO()
        used_names = set()
        with connect() as database, zipfile.ZipFile(memory_file, "w", zipfile.ZIP_DEFLATED) as archive:
            rows = database.execute("SELECT * FROM notes ORDER BY updated_at DESC").fetchall()
            for row in rows:
                base = "".join(character for character in row["title"] if character.isalnum() or character in " -_").strip() or "untitled-note"
                filename = f"{base[:80]}.md"
                counter = 2
                while filename.casefold() in used_names:
                    filename = f"{base[:72]}-{counter}.md"
                    counter += 1
                used_names.add(filename.casefold())
                archive.writestr(filename, f"# {row['title']}\n\n{row['content']}\n")
        memory_file.seek(0)
        return send_file(memory_file, mimetype="application/zip", as_attachment=True, download_name="notes-export.zip")

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)

