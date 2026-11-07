# StillNote

A small, self-hosted notes app built with Flask, SQLite, Bootstrap, and plain JavaScript.

## Run with Docker

```sh
docker compose up --build -d
```

Open <http://localhost:8080>. Stop it with `docker compose down`. Notes are kept in the `notes-data` Docker volume.

Set `PORT` in `.env` to use a different host port while keeping the app
loopback-only. For example, `PORT=1000` serves it at
<http://localhost:1000>.

## Run for development

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m flask --app app run --debug
```

Open <http://127.0.0.1:5000>.

## Test

```sh
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

## iPad landscape checks

The layout uses Safari's visual viewport to keep the editor above the on-screen
keyboard. Short windows use a smaller toolbar and scrollable writing area; the
title and note body retain usable heights even with many tags.

Optional WebKit regression tests require Playwright:

```sh
python -m pip install pytest playwright
python -m playwright install webkit
python -m pytest
```

These checks model the 11-inch iPad Pro landscape viewport (1210 × 834 CSS pixels
at 2× scale), keyboard-sized visible areas, viewport panning, long-note editing
and saving, and tag overflow. They also check desktop and narrow-window layouts.
They simulate viewport events; they do not run iPadOS or its native keyboard.

Before release, open the deployed app from the iPad Home Screen in landscape.
With the keyboard open, edit the title, type at the end of a long note, and edit
tags. Check that each field scrolls into view, text remains readable, saving
works, and dismissing/reopening the keyboard restores the available space. Also
check Safari browser mode and a hardware or floating keyboard if used.

## Keyboard shortcuts

- `Ctrl+N`: create a note
- `Ctrl+K`: focus search
- `Ctrl+S`: save now

## Saving and recovery

Edits autosave after a short pause. **Save now** (or Ctrl/Cmd+S) retries a failed
save. Switching notes or creating a note waits for pending edits to save; on
failure, the current editor stays open.

Pending title, body and tags are also stored locally in this browser for recovery
on reload. This recovery copy contains your note text; it is separate from any
usage counts. Successful saves remove it. Browser storage may be
unavailable or cleared, so recovery drafts are not a backup. Avoid editing the
same note offline in several tabs: local recovery storage is shared by this
browser's tabs.

If the saved note changed on another device or tab, the editor keeps your draft
and offers **Recover as new note** or **Discard draft**. Recovery preserves the
other version. The updated client sends a revision with each save; older API
clients that omit revisions remain compatible but do not get conflict protection.

Library requests use compact previews; opening a note loads its full text. The
SQLite revision column is added automatically on startup without rewriting note
contents. Back up the database before deploying schema changes. The current
Markdown ZIP export is available at `/export/notes.zip`; it is not a full database
backup and does not preserve tags or note state.

See [the improvement plan](docs/IMPROVEMENT_PLAN.md) for priorities, acceptance
criteria and implementation status. Open **Usage** to opt into private daily feature counts. Counts stay in this
browser for 90 days; use the same panel to stop, clear or export them. No note
text, titles, tags, queries or identifiers are collected or uploaded. Recoverable
trash is available from the sidebar.

## Trash and quick capture

**Move to Trash** keeps the complete note. Open **Trash**, choose a note, and use
**Restore from Trash** to recover it with its previous tags and pin/archive state.
Trashed notes are read-only and excluded from normal search and Markdown export.
**Delete permanently** is available only in Trash and asks for confirmation. Trash
is never purged automatically.

**New journal entry** creates an ordinary note titled with today's local date and
the Diary tag. Each click creates a new entry. **Export Markdown** downloads all
non-trashed notes after saving pending edits.


## Database backups and restore

The backup command uses SQLite's online backup API, includes committed WAL data,
checks integrity and writes a private file. It works while the app is running.
Existing destination files are refused. A database backup preserves tags, note
state, trash and revisions; it excludes browser-only drafts and usage counts.

For a local installation (create the backup directory first):

```sh
python manage.py backup /safe/backups/stillnote.db --database instance/notes.db
python manage.py restore /safe/backups/stillnote.db --database /safe/restore/notes.db
```

Restore always writes to a **new** destination. To verify it, start a separate
instance with `NOTES_DATABASE=/safe/restore/notes.db` and check its notes and Trash.
Stop the original instance before switching its database path to the verified
restored file. Keep the previous database until recovery is confirmed.

After rebuilding the Docker image with this change, back up and copy the result
to storage outside the container and notes volume:

```sh
docker exec stillnote python manage.py backup /tmp/stillnote-backup.db --database /app/data/notes.db
docker cp stillnote:/tmp/stillnote-backup.db ./stillnote-backup.db
docker exec stillnote rm /tmp/stillnote-backup.db
```

Choose a fresh destination for every backup, restrict access to the copied file,
and keep a second copy on another disk or host. Schedule this command with your
host's scheduler and verify restores periodically. A directory named `backups`
inside the notes volume does not protect against loss of that volume. Never copy
only the main database file while it is being written; use the backup command.

## Portable JSON and history

**Backup JSON** exports every current note, including Trash, tags, timestamps and
pin/archive state. **Import JSON** validates the complete backup and imports new
copies with fresh IDs. Existing notes stay in place; importing the same file
again creates duplicates. Imports are atomic and limited to 16 MiB and 10,000
notes. JSON backups omit history, local drafts and usage counts. Use SQLite
backup/restore for larger libraries or to preserve history.

Open **Note history** from a note's action menu to preview and restore older
text. StillNote captures the previous version at most once every five minutes
and keeps the latest 20 checkpoints per note. This is recovery history, not a
record of every keystroke. Restoring requires the current revision and also saves
a checkpoint of the version being replaced. Empty/new notes may have no history.
Permanent deletion also removes the note's history.

## Finding and organising notes

The library loads 100 summaries at a time. **Load more notes** extends the list;
search and tag filters always query the full library. Choose recently edited,
recently created or title order. Pins stay first within each sort order. **Clear
filters** removes the search and tag restriction within the selected view.

The tag field suggests existing tags. **Edit** beside Tags renames a tag across
all its notes, including archived and trashed notes. Choosing an existing name
merges the tags. These changes create history checkpoints and invalidate stale
editor revisions, so unsaved copies cannot silently reintroduce the previous tag.

## Scheduled backups

`scripts/backup.sh` supports Docker (default) and local installations. It publishes
complete backups outside the notes volume, restricts file permissions and rotates
only its own timestamped files after a successful backup (30-day default).

```sh
STILLNOTE_BACKUP_DIR=/path/to/external/storage scripts/backup.sh
# Local installation:
STILLNOTE_BACKUP_MODE=local STILLNOTE_PYTHON=.venv/bin/python STILLNOTE_BACKUP_DIR=/path/to/external/storage scripts/backup.sh
```

Use `STILLNOTE_DATABASE` for a different local source, `STILLNOTE_CONTAINER` for a
different container name, and `STILLNOTE_BACKUP_RETENTION_DAYS` for retention.

Optional user-systemd units are in `deploy/`. Review their checkout and backup
paths before installation. They assume `~/StillNote`, Docker access, and backups
in `~/Backups/StillNote`; choose a separate disk or replicated location when
possible. From the checkout:

```sh
mkdir -p ~/.config/systemd/user
cp deploy/stillnote-backup.service deploy/stillnote-backup.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now stillnote-backup.timer
systemctl --user start stillnote-backup.service
journalctl --user -u stillnote-backup.service
```

The units are provided for installation; running the app does not enable them.
A user timer requires the user's systemd manager to be running; use your host's
normal service policy for backups while logged out. Keep and periodically verify
a copy on another host or disk.

## Platform and automated checks

Home-screen metadata supports standalone launch where the browser offers it.
The app requires a connection to save; it does not implement offline sync.
Browser zoom remains enabled. Narrow navigation supports Escape, focus return,
and contained Tab navigation, and scrolls when the keyboard reduces its height.

Install `requirements-dev.txt`, then run `python -m playwright install --with-deps
webkit` and `python -m pytest -q` for the full suite. GitHub Actions runs those
checks on Python 3.12 and 3.13. The deployment image uses Python 3.13. These checks
include browser editing, save failures, conflicts, history, import, privacy,
backup recovery and simulated iPad keyboard layouts; actual iPad verification
still requires the device.

StillNote is designed for one trusted user. Keep its loopback binding and use your
existing trusted access boundary. Authentication, per-user isolation, shared
editing and full offline synchronisation require a separate design before opening
it to other users or untrusted networks.
