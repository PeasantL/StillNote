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

