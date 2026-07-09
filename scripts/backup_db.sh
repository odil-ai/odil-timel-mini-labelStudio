#!/usr/bin/env bash
set -euo pipefail

# Back up the TIMEL decisions SQLite database.
#
# Meant to be run via cron (e.g. at the end of the week, around
# deployment time): keeps at most MAX_BACKUPS timestamped copies; the
# oldest one is deleted on every new backup.
#
# Example crontab (Friday 8pm):
#   0 20 * * 5 /path/to/timel-annotation-studio/scripts/backup_db.sh >> /var/log/timel_backup.log 2>&1
#
# Overridable variables (.env or .dev.env): DB_PATH, BACKUP_DIR, MAX_BACKUPS.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Load .env then .dev.env (which wins locally), without overriding
# variables already exported by the environment (cron, systemd...)
for env_file in .env .dev.env; do
    if [ -f "$PROJECT_ROOT/$env_file" ]; then
        set -a
        # shellcheck disable=SC1090
        source "$PROJECT_ROOT/$env_file"
        set +a
    fi
done

DB_PATH="${DB_PATH:-$PROJECT_ROOT/data/timel_reconcile.sqlite}"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_ROOT/data/backups}"
MAX_BACKUPS="${MAX_BACKUPS:-2}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

if ! command -v sqlite3 >/dev/null 2>&1; then
    log "ERROR: sqlite3 not found in PATH."
    exit 1
fi

if [ ! -f "$DB_PATH" ]; then
    log "ERROR: database not found: $DB_PATH"
    exit 1
fi

mkdir -p "$BACKUP_DIR"

DB_NAME="$(basename "$DB_PATH" .sqlite)"
TIMESTAMP="$(date '+%Y%m%d_%H%M%S')"
DEST="$BACKUP_DIR/${DB_NAME}_${TIMESTAMP}.sqlite"

log "Backing up $DB_PATH to $DEST"
sqlite3 "$DB_PATH" ".backup '$DEST'"

if [ ! -s "$DEST" ]; then
    log "ERROR: backup is empty or failed: $DEST"
    exit 1
fi
log "Backup OK ($(du -h "$DEST" | cut -f1))"

# Rotation: keep only the MAX_BACKUPS most recent backups
# (chronological order guaranteed by the YYYYMMDD_HHMMSS name format)
backups=()
while IFS= read -r f; do
    backups+=("$f")
done < <(find "$BACKUP_DIR" -maxdepth 1 -name "${DB_NAME}_*.sqlite" -print | sort)

count=${#backups[@]}
if [ "$count" -gt "$MAX_BACKUPS" ]; then
    to_delete=$((count - MAX_BACKUPS))
    for i in $(seq 0 $((to_delete - 1))); do
        log "Removing old backup: ${backups[$i]}"
        rm -f "${backups[$i]}"
    done
fi

log "Done. Backups kept: $(find "$BACKUP_DIR" -maxdepth 1 -name "${DB_NAME}_*.sqlite" | wc -l | tr -d ' ')"
