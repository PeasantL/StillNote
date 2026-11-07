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
    with sqlite3.connect(backup) as archive:
        assert archive.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'
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


def test_backup_script_local_mode_and_retention(tmp_path):
    import os
    import subprocess
    import time
    from pathlib import Path
    source = tmp_path / 'notes.db'
    create_app({'TESTING': True, 'DATABASE': str(source)})
    backups = tmp_path / 'backups'
    backups.mkdir()
    expired = backups / 'stillnote-20000101T000000Z-100.db'
    expired.write_text('expired')
    os.utime(expired, (time.time() - 40 * 86400,) * 2)
    other = backups / 'unrelated.db'
    other.write_text('keep')
    result = subprocess.run(['sh', str(Path(__file__).resolve().parents[1] / 'scripts/backup.sh')],
        env={**os.environ, 'STILLNOTE_BACKUP_MODE': 'local', 'STILLNOTE_DATABASE': str(source), 'STILLNOTE_BACKUP_DIR': str(backups)}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert not expired.exists()
    assert other.read_text() == 'keep'
    saved = list(backups.glob('stillnote-*.db'))
    assert len(saved) == 1
    assert saved[0].stat().st_mode & 0o777 == 0o600


def test_failed_scheduled_backup_keeps_old_copies(tmp_path):
    import os
    import subprocess
    import time
    from pathlib import Path
    old = tmp_path / 'stillnote-20000101T000000Z-100.db'
    old.write_text('last known copy')
    os.utime(old, (time.time() - 40 * 86400,) * 2)
    result = subprocess.run(['sh', str(Path(__file__).resolve().parents[1] / 'scripts/backup.sh')],
        env={**os.environ, 'STILLNOTE_BACKUP_MODE': 'local', 'STILLNOTE_DATABASE': str(tmp_path / 'missing.db'), 'STILLNOTE_BACKUP_DIR': str(tmp_path)}, capture_output=True, text=True)
    assert result.returncode != 0
    assert old.read_text() == 'last known copy'


def test_backup_refuses_dangling_destination_symlink(tmp_path):
    source = tmp_path / 'source.db'
    create_app({'TESTING': True, 'DATABASE': str(source)})
    target = tmp_path / 'unexpected.db'
    link = tmp_path / 'link.db'
    link.symlink_to(target)
    with pytest.raises(FileExistsError):
        copy_database(source, link)
    assert not target.exists()
