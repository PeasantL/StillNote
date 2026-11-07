import io
import json
import os
import sqlite3
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, abort, jsonify, render_template, request, send_file
from werkzeug.exceptions import HTTPException


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_app(test_config=None):
    app = Flask(__name__)
    default_database = Path(app.instance_path) / "notes.db"
    app.config.from_mapping(
        DATABASE=os.environ.get("NOTES_DATABASE", str(default_database)),
        MAX_CONTENT_LENGTH=16 * 1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)

    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect():
        connection = sqlite3.connect(app.config["DATABASE"])
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

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

                CREATE TABLE IF NOT EXISTS note_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
                    saved_at TEXT NOT NULL,
                    snapshot TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS history_note_idx ON note_history(note_id, id DESC);
                CREATE INDEX IF NOT EXISTS notes_updated_at_idx ON notes(updated_at DESC);
                CREATE INDEX IF NOT EXISTS notes_archived_idx ON notes(archived);
                """
            )
            columns = {row["name"] for row in database.execute("PRAGMA table_info(notes)")}
            if "revision" not in columns:
                database.execute("ALTER TABLE notes ADD COLUMN revision INTEGER NOT NULL DEFAULT 1")
            if "deleted_at" not in columns:
                database.execute("ALTER TABLE notes ADD COLUMN deleted_at TEXT")
            database.execute("CREATE INDEX IF NOT EXISTS note_tags_tag_idx ON note_tags(tag_id, note_id)")

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

    def snapshot_note(database, current, force=False):
        latest = database.execute("SELECT saved_at FROM note_history WHERE note_id = ? ORDER BY id DESC LIMIT 1", (current["id"],)).fetchone()
        now = utc_now()
        if force or latest is None or (datetime.fromisoformat(now) - datetime.fromisoformat(latest["saved_at"])).total_seconds() >= 300:
            database.execute("INSERT INTO note_history (note_id, saved_at, snapshot) VALUES (?, ?, ?)",
                             (current["id"], now, json.dumps(note_as_dict(database, current))))
            database.execute("DELETE FROM note_history WHERE note_id = ? AND id NOT IN (SELECT id FROM note_history WHERE note_id = ? ORDER BY id DESC LIMIT 20)", (current["id"], current["id"]))

    def get_note(database, note_id, include_deleted=False):
        row = database.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        if row is None or (row["deleted_at"] and not include_deleted):
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

    def payload_object():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            abort(400, description="Expected a JSON object.")
        return payload

    def validate_fields(payload):
        for field, limit in (("title", 200), ("content", 1_000_000)):
            if field in payload and (not isinstance(payload[field], str) or len(payload[field]) > limit):
                abort(400, description=f"{field} must be text with at most {limit} characters.")
        for field in ("pinned", "archived"):
            if field in payload and not isinstance(payload[field], bool):
                abort(400, description=f"{field} must be true or false.")
        if "revision" in payload and (type(payload["revision"]) is not int or payload["revision"] < 1):
            abort(400, description="revision must be a positive integer.")
        if "tags" in payload:
            tags = payload["tags"]
            if isinstance(tags, str):
                tags = tags.split(",")
            if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
                abort(400, description="tags must be text or a list of strings.")
            if len([tag for tag in tags if tag.strip()]) > 20 or any(len(tag.strip()) > 40 for tag in tags):
                abort(400, description="Use at most 20 tags, each at most 40 characters.")

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.after_request
    def private_response(response):
        if request.path.startswith(("/api/", "/export/")):
            response.headers["Cache-Control"] = "no-store"
        return response

    initialise_database()

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/health")
    def health():
        with connect() as database:
            database.execute("SELECT id FROM notes LIMIT 1").fetchone()
        return {"status": "ok"}

    @app.get("/api/notes")
    def list_notes():
        archived = 1 if request.args.get("archived") == "1" else 0
        search = request.args.get("q", "").strip()
        tag = request.args.get("tag", "").strip()
        summary = request.args.get("summary") == "1"
        fields = "notes.*"
        if summary:
            fields = "notes.id, notes.title, notes.pinned, notes.archived, notes.created_at, notes.updated_at, notes.revision, notes.deleted_at, substr(notes.content, 1, 240) AS preview"
        sql = f"SELECT DISTINCT {fields} FROM notes"
        parameters = []
        if tag:
            sql += " JOIN note_tags ON note_tags.note_id = notes.id JOIN tags ON tags.id = note_tags.tag_id"
        if request.args.get("trash") == "1":
            sql += " WHERE notes.deleted_at IS NOT NULL"
        else:
            sql += " WHERE notes.deleted_at IS NULL AND notes.archived = ?"
            parameters.append(archived)
        if search:
            sql += " AND (notes.title LIKE ? ESCAPE '\\' OR notes.content LIKE ? ESCAPE '\\')"
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            parameters.extend([f"%{escaped}%", f"%{escaped}%"])
        if tag:
            sql += " AND tags.name = ? COLLATE NOCASE"
            parameters.append(tag)
        if request.args.get("pinned") == "1":
            sql += " AND notes.pinned = 1"
        count_sql = "SELECT COUNT(*) FROM (" + sql + ")"
        sort = {"updated": "notes.updated_at DESC", "created": "notes.created_at DESC", "title": "notes.title COLLATE NOCASE ASC"}.get(request.args.get("sort", "updated"))
        if sort is None:
            abort(400, description="Unknown sort order.")
        sql += f" ORDER BY notes.pinned DESC, {sort}, notes.id DESC"
        limit = request.args.get("limit", type=int)
        offset = request.args.get("offset", 0, type=int)
        if ("limit" in request.args and (limit is None or not 1 <= limit <= 200)) or offset is None or offset < 0:
            abort(400, description="Use a limit from 1 to 200 and a nonnegative offset.")
        query_parameters = list(parameters)
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            query_parameters.extend([limit, offset])
        with connect() as database:
            rows = database.execute(sql, query_parameters).fetchall()
            total = database.execute(count_sql, parameters).fetchone()[0]
            # Fetch tags in batches instead of one query per note.
            result = [dict(row, pinned=bool(row["pinned"]), archived=bool(row["archived"]), tags=[]) for row in rows]
            by_id = {note["id"]: note for note in result}
            ids = list(by_id)
            for offset in range(0, len(ids), 500):
                batch = ids[offset:offset + 500]
                placeholders = ",".join("?" for _ in batch)
                for tag_row in database.execute(
                    f"SELECT note_id, name FROM note_tags JOIN tags ON tags.id = tag_id WHERE note_id IN ({placeholders}) ORDER BY name COLLATE NOCASE", batch
                ):
                    by_id[tag_row["note_id"]]["tags"].append(tag_row["name"])
            response = jsonify(result)
            response.headers["X-Total-Count"] = str(total)
            return response

    @app.post("/api/notes")
    def create_note():
        payload = payload_object()
        validate_fields(payload)
        now = utc_now()
        title = str(payload.get("title") or "Untitled note").strip()[:200] or "Untitled note"
        with connect() as database:
            cursor = database.execute(
                "INSERT INTO notes (title, content, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (title, payload.get("content", ""), now, now),
            )
            if "tags" in payload:
                replace_tags(database, cursor.lastrowid, normalise_tags(payload["tags"]))
            row = get_note(database, cursor.lastrowid)
            return jsonify(note_as_dict(database, row)), 201

    @app.get("/api/notes/<int:note_id>")
    def read_note(note_id):
        with connect() as database:
            return jsonify(note_as_dict(database, get_note(database, note_id, request.args.get("trash") == "1")))

    @app.patch("/api/notes/<int:note_id>")
    def update_note(note_id):
        payload = payload_object()
        validate_fields(payload)
        allowed = {"title", "content", "pinned", "archived", "tags"}
        if not (set(payload) & allowed):
            return {"error": "No supported fields were provided."}, 400
        with connect() as database:
            database.execute("BEGIN IMMEDIATE")
            current = get_note(database, note_id, include_deleted=True)
            if current["deleted_at"]:
                return {"error": "This note is in Trash. Recover your draft as a new note or restore the saved note first."}, 409
            if "revision" in payload and payload["revision"] != current["revision"]:
                return {"error": "This note changed elsewhere. Your edits are kept locally; reopen the note to review them.", "current": note_as_dict(database, current)}, 409
            if any(payload[field] != current[field] for field in ("title", "content", "pinned", "archived") if field in payload) or "tags" in payload and normalise_tags(payload["tags"]) != note_as_dict(database, current)["tags"]:
                snapshot_note(database, current)
            title = str(payload.get("title", current["title"])).strip()[:200] or "Untitled note"
            content = str(payload.get("content", current["content"]))[:1_000_000]
            pinned = int(bool(payload.get("pinned", current["pinned"])))
            archived = int(bool(payload.get("archived", current["archived"])))
            database.execute(
                "UPDATE notes SET title = ?, content = ?, pinned = ?, archived = ?, updated_at = ?, revision = revision + 1 WHERE id = ?",
                (title, content, pinned, archived, utc_now(), note_id),
            )
            if "tags" in payload:
                replace_tags(database, note_id, normalise_tags(payload["tags"]))
            return jsonify(note_as_dict(database, get_note(database, note_id)))

    def check_revision(payload, current, required=False):
        if required and "revision" not in payload:
            abort(400, description="A revision is required.")
        if "revision" in payload and payload["revision"] != current["revision"]:
            abort(409, description="This note changed elsewhere. Reopen it before trying again.")

    @app.delete("/api/notes/<int:note_id>")
    def delete_note(note_id):
        payload = payload_object() if request.data else {}
        validate_fields(payload)
        with connect() as database:
            database.execute("BEGIN IMMEDIATE")
            current = get_note(database, note_id)
            check_revision(payload, current)
            database.execute("UPDATE notes SET deleted_at = ?, revision = revision + 1 WHERE id = ?", (utc_now(), note_id))
        return Response(status=204)

    @app.post("/api/notes/<int:note_id>/restore")
    def restore_note(note_id):
        payload = payload_object()
        validate_fields(payload)
        with connect() as database:
            database.execute("BEGIN IMMEDIATE")
            current = get_note(database, note_id, include_deleted=True)
            check_revision(payload, current, required=True)
            if not current["deleted_at"]:
                abort(409, description="This note is not in Trash.")
            database.execute("UPDATE notes SET deleted_at = NULL, revision = revision + 1 WHERE id = ?", (note_id,))
            return jsonify(note_as_dict(database, get_note(database, note_id)))

    @app.delete("/api/notes/<int:note_id>/permanent")
    def permanently_delete_note(note_id):
        payload = payload_object()
        validate_fields(payload)
        with connect() as database:
            database.execute("BEGIN IMMEDIATE")
            current = get_note(database, note_id, include_deleted=True)
            check_revision(payload, current, required=True)
            if not current["deleted_at"]:
                abort(409, description="Move this note to Trash before deleting it permanently.")
            database.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            database.execute("DELETE FROM tags WHERE id NOT IN (SELECT tag_id FROM note_tags)")
        return Response(status=204)

    @app.get("/api/notes/<int:note_id>/history")
    def list_history(note_id):
        with connect() as database:
            get_note(database, note_id, include_deleted=True)
            rows = database.execute("SELECT id, saved_at, snapshot FROM note_history WHERE note_id = ? ORDER BY id DESC", (note_id,)).fetchall()
            return jsonify([dict(id=row["id"], saved_at=row["saved_at"], title=json.loads(row["snapshot"])["title"]) for row in rows])

    @app.get("/api/notes/<int:note_id>/history/<int:history_id>")
    def read_history(note_id, history_id):
        with connect() as database:
            get_note(database, note_id, include_deleted=True)
            row = database.execute("SELECT snapshot FROM note_history WHERE id = ? AND note_id = ?", (history_id, note_id)).fetchone()
            if row is None:
                abort(404)
            return jsonify(json.loads(row["snapshot"]))

    @app.post("/api/notes/<int:note_id>/history/<int:history_id>/restore")
    def restore_history(note_id, history_id):
        payload = payload_object()
        validate_fields(payload)
        with connect() as database:
            database.execute("BEGIN IMMEDIATE")
            current = get_note(database, note_id)
            check_revision(payload, current, required=True)
            row = database.execute("SELECT snapshot FROM note_history WHERE id = ? AND note_id = ?", (history_id, note_id)).fetchone()
            if row is None:
                abort(404)
            previous = json.loads(row["snapshot"])
            snapshot_note(database, current, force=True)
            database.execute("UPDATE notes SET title = ?, content = ?, pinned = ?, archived = ?, updated_at = ?, revision = revision + 1 WHERE id = ?",
                             (previous["title"], previous["content"], previous["pinned"], previous["archived"], utc_now(), note_id))
            replace_tags(database, note_id, previous["tags"])
            return jsonify(note_as_dict(database, get_note(database, note_id)))

    @app.get("/export/notes.json")
    def export_json():
        with connect() as database:
            database.execute("BEGIN")
            notes = [note_as_dict(database, row) for row in database.execute("SELECT * FROM notes ORDER BY id")]
        response = jsonify(format="stillnote", version=1, exported_at=utc_now(), notes=notes)
        response.headers["Content-Disposition"] = 'attachment; filename="stillnote-backup.json"'
        return response

    @app.post("/api/import")
    def import_json():
        payload = payload_object()
        if payload.get("format") != "stillnote" or type(payload.get("version")) is not int or payload["version"] != 1 or not isinstance(payload.get("notes"), list):
            abort(400, description="Expected a StillNote version 1 JSON backup.")
        if len(payload["notes"]) > 10_000:
            abort(400, description="Import at most 10,000 notes at once.")
        # Validate the entire archive before opening the write transaction.
        required = {"title", "content", "tags", "pinned", "archived", "created_at", "updated_at", "deleted_at"}
        for note in payload["notes"]:
            if not isinstance(note, dict) or not required <= note.keys() or not isinstance(note["tags"], list):
                abort(400, description="A backup note is missing required fields.")
            validate_fields(note)
            for field in ("created_at", "updated_at", "deleted_at"):
                value = note[field]
                if field == "deleted_at" and value is None:
                    continue
                try:
                    if not isinstance(value, str) or len(value) > 64:
                        raise ValueError()
                    datetime.fromisoformat(value)
                except ValueError:
                    abort(400, description=f"Invalid {field} timestamp.")
        with connect() as database:
            database.execute("BEGIN IMMEDIATE")
            ids = []
            for note in payload["notes"]:
                cursor = database.execute("INSERT INTO notes (title, content, pinned, archived, created_at, updated_at, deleted_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    tuple(note[field] for field in ("title", "content", "pinned", "archived", "created_at", "updated_at", "deleted_at")))
                replace_tags(database, cursor.lastrowid, normalise_tags(note["tags"]))
                ids.append(cursor.lastrowid)
        return jsonify(imported=len(ids), ids=ids), 201

    @app.post("/api/tags/rename")
    def rename_tag():
        payload = payload_object()
        source, target = payload.get("from"), payload.get("to")
        if not isinstance(source, str) or not isinstance(target, str) or not target.strip() or len(target.strip()) > 40 or "," in target:
            abort(400, description="Provide a source tag and a new name of 1–40 characters without commas.")
        target = target.strip()
        with connect() as database:
            database.execute("BEGIN IMMEDIATE")
            old = database.execute("SELECT id FROM tags WHERE name = ? COLLATE NOCASE", (source,)).fetchone()
            if old is None:
                abort(404)
            affected = database.execute("SELECT notes.* FROM notes JOIN note_tags ON notes.id = note_id WHERE tag_id = ?", (old["id"],)).fetchall()
            for note in affected:
                snapshot_note(database, note, force=True)
            database.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (target,))
            new = database.execute("SELECT id FROM tags WHERE name = ? COLLATE NOCASE", (target,)).fetchone()
            if new["id"] == old["id"]:
                database.execute("UPDATE tags SET name = ? WHERE id = ?", (target, old["id"]))
            else:
                database.execute("INSERT OR IGNORE INTO note_tags SELECT note_id, ? FROM note_tags WHERE tag_id = ?", (new["id"], old["id"]))
                database.execute("DELETE FROM tags WHERE id = ?", (old["id"],))
            for note in affected:
                database.execute("UPDATE notes SET revision = revision + 1 WHERE id = ?", (note["id"],))
        return jsonify(updated=len(affected))

    @app.get("/api/tags")
    def list_tags():
        with connect() as database:
            rows = database.execute(
                """
                SELECT tags.name, COUNT(note_tags.note_id) AS note_count
                FROM tags JOIN note_tags ON note_tags.tag_id = tags.id
                JOIN notes ON notes.id = note_tags.note_id
                WHERE notes.archived = 0 AND notes.deleted_at IS NULL
                GROUP BY tags.id ORDER BY tags.name COLLATE NOCASE
                """
            ).fetchall()
            return jsonify([dict(row) for row in rows])

    @app.get("/export/notes.zip")
    def export_notes():
        memory_file = io.BytesIO()
        used_names = set()
        with connect() as database, zipfile.ZipFile(memory_file, "w", zipfile.ZIP_DEFLATED) as archive:
            rows = database.execute("SELECT * FROM notes WHERE deleted_at IS NULL ORDER BY updated_at DESC").fetchall()
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

