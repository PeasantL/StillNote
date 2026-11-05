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
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m flask --app app run --debug
```

Open <http://127.0.0.1:5000>.

## Test

```sh
.venv\Scripts\pip install pytest
.venv\Scripts\python -m pytest
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
