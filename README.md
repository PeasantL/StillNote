# StillNote

A small, self-hosted notes app built with Flask, SQLite, Bootstrap, and plain JavaScript.

## Run with Docker

```sh
docker compose up --build -d
```

Open <http://localhost:8080>. Stop it with `docker compose down`. Notes are kept in the `notes-data` Docker volume.

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

## Keyboard shortcuts

- `Ctrl+N`: create a note
- `Ctrl+K`: focus search
- `Ctrl+S`: save now
