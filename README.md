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
.venv/bin/pip install pytest
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
future usage analytics. Successful saves remove it. Browser storage may be
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
