import sqlite3

import pytest

from app import create_app
from manage import copy_database


def test_backup_and_restore_include_committed_wal_and_trash(tmp_path):
    source = tmp_path / 'notes.db'
    client = create_app({'TESTING': True, 'DATABASE': str(source)}).test_client()
    note = client.post('/api/notes', json={'content': 'Preserve 日本語', 'tags': ['diary']}).get_json()
    client.delete(f"/api/notes/{note['id']}")
    # Keep WAL active while making a committed write and taking the backup.
    with sqlite3.connect(source) as writer:
        writer.execute('PRAGMA wal_autocheckpoint = 0')
        writer.execute("UPDATE notes SET title = 'Committed in WAL'")
        writer.commit()
        backup = copy_database(source, tmp_path / 'backup.db')
    restored = copy_database(backup, tmp_path / 'restored.db')
    restored_client = create_app({'TESTING': True, 'DATABASE': str(restored)}).test_client()
    saved = restored_client.get('/api/notes?trash=1').get_json()[0]
    assert saved['title'] == 'Committed in WAL'
    assert saved['content'] == 'Preserve 日本語'
    assert saved['tags'] == ['diary']
    assert saved['revision'] == 2
    assert backup.stat().st_mode & 0o777 == 0o600


def test_backup_refuses_overwrite_and_invalid_sources(tmp_path):
    source = tmp_path / 'source.db'
    create_app({'TESTING': True, 'DATABASE': str(source)})
    target = tmp_path / 'keep.txt'
    target.write_text('keep this')
    with pytest.raises(FileExistsError):
        copy_database(source, target)
    assert target.read_text() == 'keep this'
    invalid = tmp_path / 'invalid.db'
    with sqlite3.connect(invalid) as database:
        database.execute('CREATE TABLE unrelated (id INTEGER)')
    with pytest.raises(ValueError):
        copy_database(invalid, tmp_path / 'output.db')
    assert not (tmp_path / 'output.db').exists()
