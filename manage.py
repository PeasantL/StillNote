"""Consistent SQLite backups and restore into a new database, including WAL data."""
import argparse
import os
import sqlite3
from contextlib import closing
from pathlib import Path


def copy_database(source, destination):
    source = Path(source).resolve()
    destination = Path(destination).absolute()
    if not source.is_file():
        raise ValueError(f"Source database does not exist: {source}")
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as database:
        if database.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('Source database failed its integrity check.')
        tables = {row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        required = {'notes': {'id', 'title', 'content', 'pinned', 'archived', 'created_at', 'updated_at'},
                    'tags': {'id', 'name'}, 'note_tags': {'note_id', 'tag_id'}}
        if not required.keys() <= tables:
            raise ValueError('Source is not a StillNote database.')
        for table, columns in required.items():
            if not columns <= {row[1] for row in database.execute(f'PRAGMA table_info({table})')}:
                raise ValueError('Source has an incompatible StillNote schema.')
        if database.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise ValueError('Source has broken note/tag references.')
        # Exclusive creation avoids overwriting any existing destination, including symlinks.
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        try:
            with closing(sqlite3.connect(destination)) as target:
                database.backup(target)
                # Archives must reopen from read-only storage without WAL sidecars.
                target.execute('PRAGMA journal_mode = DELETE')
                if target.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise ValueError('Copied database failed its integrity check.')
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    backup = commands.add_parser('backup', help='Back up a running or stopped database into a new file.')
    backup.add_argument('destination')
    backup.add_argument('--database', default=os.environ.get('NOTES_DATABASE', 'instance/notes.db'))
    restore = commands.add_parser('restore', help='Restore a backup into a new database file; existing files are refused.')
    restore.add_argument('source')
    restore.add_argument('--database', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'backup':
            result = copy_database(args.database, args.destination)
        else:
            result = copy_database(args.source, args.database)
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f'{error}\n')
    print(f'{args.command.capitalize()} complete: {result}')


if __name__ == '__main__':
    main()
