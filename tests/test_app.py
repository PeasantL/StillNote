import pytest

from app import create_app


@pytest.fixture()
def client(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.db")})
    return app.test_client()


def test_health(client):
    assert client.get("/health").get_json() == {"status": "ok"}


def test_note_lifecycle(client):
    created = client.post("/api/notes", json={"title": "First note"})
    assert created.status_code == 201
    note_id = created.get_json()["id"]

    updated = client.patch(
        f"/api/notes/{note_id}",
        json={"content": "Remember the milk", "pinned": True, "tags": ["home", "todo"]},
    ).get_json()
    assert updated["pinned"] is True
    assert updated["tags"] == ["home", "todo"]

    results = client.get("/api/notes?q=milk").get_json()
    assert [note["id"] for note in results] == [note_id]

    assert client.delete(f"/api/notes/{note_id}").status_code == 204
    assert client.get(f"/api/notes/{note_id}").status_code == 404


def test_archive_and_restore(client):
    note = client.post("/api/notes", json={}).get_json()
    client.patch(f"/api/notes/{note['id']}", json={"archived": True})
    assert client.get("/api/notes").get_json() == []
    assert len(client.get("/api/notes?archived=1").get_json()) == 1


def test_export(client):
    client.post("/api/notes", json={"title": "Export me"})
    response = client.get("/export/notes.zip")
    assert response.status_code == 200
    assert response.mimetype == "application/zip"



def test_revision_conflict_preserves_newer_note(client):
    note = client.post('/api/notes', json={'content': 'original', 'tags': ['idea']}).get_json()
    url = f"/api/notes/{note['id']}"
    saved = client.patch(url, json={'content': 'newer', 'revision': note['revision']}).get_json()
    conflict = client.patch(url, json={'content': 'stale', 'tags': [], 'revision': note['revision']})
    assert conflict.status_code == 409
    assert client.get(url).get_json()['content'] == 'newer'
    assert client.get(url).get_json()['tags'] == ['idea']
    assert saved['revision'] == note['revision'] + 1


@pytest.mark.parametrize('payload', [[], 'text', None, {'content': None}, {'pinned': 'false'},
                                    {'tags': [1]}, {'title': 'x' * 201}, {'revision': True}])
def test_invalid_input_does_not_modify_note(client, payload):
    note = client.post('/api/notes', json={}).get_json()
    url = f"/api/notes/{note['id']}"
    assert client.patch(url, json=payload).status_code == 400
    assert client.get(url).get_json() == note
    assert client.post('/api/notes', json=payload).status_code == 400


def test_summary_searches_full_content_and_keeps_literal_wildcards(client):
    note = client.post('/api/notes', json={'content': 'a' * 1000 + '100%_done', 'tags': ['Beta', 'alpha']}).get_json()
    response = client.get('/api/notes?summary=1&q=100%25_done')
    result = response.get_json()
    assert len(result) == 1
    assert result[0]['id'] == note['id']
    assert 'content' not in result[0]
    assert len(result[0]['preview']) == 240
    assert result[0]['tags'] == ['alpha', 'Beta']
    assert response.headers['Cache-Control'] == 'no-store'
    assert client.get('/api/notes?q=100X_done').get_json() == []


def test_migration_preserves_existing_note(tmp_path):
    import sqlite3
    path = str(tmp_path / 'legacy.db')
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE notes (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, content TEXT NOT NULL, pinned INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)')
        db.execute("INSERT INTO notes VALUES (7, 'Legacy', 'Keep this text', 1, 0, '2020-01-01', '2020-01-02')")
    for _ in range(2):
        app = create_app({'TESTING': True, 'DATABASE': path})
        note = app.test_client().get('/api/notes/7').get_json()
        assert note['content'] == 'Keep this text'
        assert note['pinned'] is True
        assert note['revision'] == 1


def test_trash_restore_preserves_content_tags_and_state(client):
    note = client.post('/api/notes', json={'title': 'Keep me', 'content': 'Exact text\n日本語', 'tags': ['personal']}).get_json()
    url = f"/api/notes/{note['id']}"
    original = client.patch(url, json={'pinned': True, 'archived': True}).get_json()
    assert client.delete(url, json={'revision': original['revision']}).status_code == 204
    assert client.get(url).status_code == 404
    trash = client.get('/api/notes?trash=1').get_json()
    assert len(trash) == 1
    assert client.patch(url, json={'content': 'stale edit'}).status_code == 409
    restored = client.post(url + '/restore', json={'revision': trash[0]['revision']}).get_json()
    assert restored['deleted_at'] is None
    for field in ('content', 'tags', 'pinned', 'archived', 'created_at', 'updated_at'):
        assert restored[field] == original[field]
    assert client.get('/api/notes?trash=1').get_json() == []
    assert client.get('/api/notes?archived=1').get_json()[0]['id'] == note['id']


def test_trash_is_excluded_from_tags_search_and_export(client):
    import io
    import zipfile
    note = client.post('/api/notes', json={'title': 'Hidden', 'content': 'secret', 'tags': ['only-trash']}).get_json()
    client.delete(f"/api/notes/{note['id']}")
    assert client.get('/api/notes?q=secret').get_json() == []
    assert client.get('/api/tags').get_json() == []
    with zipfile.ZipFile(io.BytesIO(client.get('/export/notes.zip').data)) as archive:
        assert archive.namelist() == []


def test_permanent_deletion_requires_trash_and_current_revision(client):
    note = client.post('/api/notes', json={'tags': ['orphan']}).get_json()
    url = f"/api/notes/{note['id']}"
    assert client.delete(url + '/permanent', json={'revision': note['revision']}).status_code == 409
    assert client.delete(url, json={'revision': 999}).status_code == 409
    client.delete(url)
    assert client.delete(url + '/permanent', json={}).status_code == 400
    assert client.delete(url + '/permanent', json={'revision': note['revision']}).status_code == 409
    trashed = client.get(url + '?trash=1').get_json()
    assert client.delete(url + '/permanent', json={'revision': trashed['revision']}).status_code == 204
    assert client.get(url + '?trash=1').status_code == 404
