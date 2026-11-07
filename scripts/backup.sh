#!/bin/sh
# Run locally or from a user timer. No live configuration is modified.
set -eu
umask 077
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
backup_dir=${STILLNOTE_BACKUP_DIR:?Set STILLNOTE_BACKUP_DIR to storage outside the notes volume}
retention_days=${STILLNOTE_BACKUP_RETENTION_DAYS:-30}
case "$retention_days" in ''|*[!0-9]*) exit 2;; esac
if [ "$retention_days" -lt 1 ]; then exit 2; fi
mkdir -p "$backup_dir"
backup_name="stillnote-$(date -u +%Y%m%dT%H%M%SZ)-$$.db"
backup_path="$backup_dir/$backup_name"
container=${STILLNOTE_CONTAINER:-stillnote}
mode=${STILLNOTE_BACKUP_MODE:-docker}
if [ "$mode" = local ]; then
    "${STILLNOTE_PYTHON:-python3}" "$project_dir/manage.py" backup "$backup_path" --database "${STILLNOTE_DATABASE:-$project_dir/instance/notes.db}"
elif [ "$mode" = docker ]; then
    # Copy via a private temporary host directory; publish only a complete copy.
    temporary_dir=$(mktemp -d "$backup_dir/.stillnote-backup.XXXXXX")
    trap 'docker exec "$container" rm -f "/tmp/$backup_name" >/dev/null 2>&1 || :; rm -rf "$temporary_dir"' EXIT HUP INT TERM
    docker exec "$container" python manage.py backup "/tmp/$backup_name" --database /app/data/notes.db
    docker cp "$container:/tmp/$backup_name" "$temporary_dir/backup.db"
    chmod 600 "$temporary_dir/backup.db"
    # A hard link publishes atomically and refuses any existing destination.
    ln "$temporary_dir/backup.db" "$backup_path"
else
    exit 2
fi
# Only rotate this script's timestamped filenames, after a successful backup.
find "$backup_dir" -maxdepth 1 -type f -name 'stillnote-????????T??????Z-*.db' -mtime +"$retention_days" -delete
printf 'Backup ready: %s\n' "$backup_path"
