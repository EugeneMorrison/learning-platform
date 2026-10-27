#!/usr/bin/env bash
# Daily backup of the learning platform: SQLite database + uploaded media.
#
# Runs on the server as root, from cron (install: docs/BACKUP.md). The site
# keeps running: the database is copied with SQLite's online backup API inside
# the running web container, and media is read through a read-only mount.
#
# Each run creates /root/backups/auto_YYYY-MM-DD_HHMMSSZ/ (time in UTC) with:
#   db.sqlite3     consistent snapshot that passed PRAGMA integrity_check
#   media.tar.gz   everything in the media volume (lesson images)
#   info.txt       when, from which code version, file counts
#   SHA256SUMS     checksums of the three files above
# No .env and no certificates: secrets are never part of a backup.
#
# Retention keeps the 14 newest auto_* folders. Nothing else in /root/backups
# (manual snapshots, pre-restore_* folders, other files) is ever deleted.
#
# Usage: scripts/backup.sh        (no arguments; exit code 0 = success)

set -euo pipefail

# cron starts jobs with a minimal PATH (/usr/bin:/bin); set the usual full one
# so docker, flock, sha256sum etc. are found exactly as in a login shell.
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# ---- Settings ---------------------------------------------------------------
BACKUP_ROOT=/root/backups
KEEP=14                                     # how many auto_* backups to keep
MEDIA_VOLUME=learning-platform_media-data   # mounted at /app/media in web
# Dockerfile sets DB_DIR=/app/db (the db-data volume); settings.py uses
# DB_DIR / 'db.sqlite3'.
DB_PATH_IN_WEB=/app/db/db.sqlite3
HELPER_IMAGE=alpine:3.20                    # throwaway container that reads media
LOCK_FILE=/run/lock/uchebus-backup.lock     # shared with restore.sh
# Backup folder name without the auto_ prefix: 2026-10-27_000003Z
STAMP_REGEX='[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{6}Z'

# The project folder is the parent of this script's folder (scripts/..).
# docker compose must run there to find docker-compose.yml and .env.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log() { echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') $*"; }
die() { log "ERROR: $*" >&2; exit 1; }

cd "$PROJECT_DIR"
[ -f docker-compose.yml ] || die "docker-compose.yml not found in $PROJECT_DIR"

# Only one backup or restore at a time. File descriptor 9 stays open until the
# script exits; flock -n fails at once instead of waiting for the other run.
exec 9>"$LOCK_FILE"
flock -n 9 || die "another backup or restore is running (lock: $LOCK_FILE)"

# Everything we create is readable by root only: the DB holds personal data.
umask 077

NAME="auto_$(date -u +%Y-%m-%d_%H%M%SZ)"
FINAL_DIR="$BACKUP_ROOT/$NAME"
WORK_DIR="$FINAL_DIR.partial"        # renamed to FINAL_DIR only when complete
TMP_IN_WEB="/tmp/$NAME.sqlite3"      # snapshot inside the web container

# Runs on every exit, success or failure.
cleanup() {
    local status=$?
    # Best effort: the temp file may not exist, or web may be down.
    docker compose exec -T web rm -f "$TMP_IN_WEB" >/dev/null 2>&1 || true
    # A folder still named .partial means the run did not finish: drop it.
    if [ -d "$WORK_DIR" ]; then rm -rf -- "$WORK_DIR"; fi
    if [ "$status" -ne 0 ]; then log "BACKUP FAILED (exit code $status)"; fi
}
trap cleanup EXIT

log "Backup $NAME started"
mkdir -p "$BACKUP_ROOT"

# A run that was killed (reboot, out of memory) can leave auto_*.partial
# behind. The lock above guarantees no other run is using them now.
for dir in "$BACKUP_ROOT"/auto_*.partial; do
    if [ -d "$dir" ] && [[ ${dir##*/} =~ ^auto_${STAMP_REGEX}\.partial$ ]]; then
        log "Removing unfinished backup from an earlier run: ${dir##*/}"
        rm -rf -- "$dir"
    fi
done

# Fail early with a clear message instead of halfway through.
# (grep reads all of its input, so pipefail never sees a broken pipe.)
docker compose ps --status running --services | grep -x web >/dev/null \
    || die "the web container is not running (docker compose ps)"
docker volume inspect "$MEDIA_VOLUME" >/dev/null \
    || die "docker volume $MEDIA_VOLUME not found"
mkdir "$WORK_DIR"

# ---- 1. Database ------------------------------------------------------------
log "Step 1/4: database snapshot inside the web container"
# Python program run by the container's own Python 3.12 (python -c CODE ARGS):
# sys.argv[1] = live DB, sys.argv[2] = where to write the snapshot.
SNAPSHOT_PY=$(cat <<'PY'
import sqlite3
import sys

live_path, snapshot_path = sys.argv[1], sys.argv[2]

# Open the live database read-only (mode=ro): the backup never writes to it.
# timeout: wait up to 30 s if the site is in the middle of a write.
live = sqlite3.connect(f"file:{live_path}?mode=ro", uri=True, timeout=30)
snapshot = sqlite3.connect(snapshot_path)
# Online backup API: copies every page as one consistent snapshot while the
# site keeps reading and writing.
live.backup(snapshot)
live.close()

problems = [row[0] for row in snapshot.execute("PRAGMA integrity_check")]
snapshot.close()
if problems != ["ok"]:
    print("integrity_check FAILED:", *problems[:20], sep="\n  ", file=sys.stderr)
    sys.exit(1)
PY
)
# -T: no terminal (cron has none). -I: isolated mode, ignores files in /app.
docker compose exec -T web python -I -c "$SNAPSHOT_PY" "$DB_PATH_IN_WEB" "$TMP_IN_WEB" \
    || die "database snapshot failed or did not pass integrity_check"
log "integrity_check: ok"
docker compose cp "web:$TMP_IN_WEB" "$WORK_DIR/db.sqlite3"

# ---- 2. Media ---------------------------------------------------------------
# Taken after the DB snapshot, so it holds every image the snapshot refers to.
log "Step 2/4: media archive (read-only mount of $MEDIA_VOLUME)"
# --rm: delete the container afterwards. --network none: it needs no network.
# :ro mounts the media volume read-only; /out is the backup folder.
docker run --rm --network none \
    -v "$MEDIA_VOLUME:/media:ro" \
    -v "$WORK_DIR:/out" \
    "$HELPER_IMAGE" tar -czf /out/media.tar.gz -C /media .
# Read the whole archive back (proves it is not truncated) and count the files;
# entries ending in / are folders.
MEDIA_FILES=$(tar -tzf "$WORK_DIR/media.tar.gz" | awk '!/\/$/ { n++ } END { print n + 0 }')
log "media files: $MEDIA_FILES"

# ---- 3. info.txt and checksums ----------------------------------------------
log "Step 3/4: info.txt and SHA256SUMS"
{
    echo "backup:      $NAME"
    echo "created:     $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
    echo "server:      $(hostname)"
    echo "git commit:  $(git -C "$PROJECT_DIR" log -1 --format='%h %s' 2>/dev/null || echo unknown)"
    echo "db size:     $(stat -c %s "$WORK_DIR/db.sqlite3") bytes"
    echo "media files: $MEDIA_FILES"
} > "$WORK_DIR/info.txt"
# Run in a subshell (parentheses) so the cd does not affect the rest.
(cd "$WORK_DIR" && sha256sum db.sqlite3 media.tar.gz info.txt > SHA256SUMS)
# docker cp and the helper container ignore our umask; make everything 0600.
chmod 600 "$WORK_DIR"/*

# The backup is complete: give it its final name.
mv -- "$WORK_DIR" "$FINAL_DIR"

# ---- 4. Retention -----------------------------------------------------------
log "Step 4/4: retention (keep the $KEEP newest auto_* backups)"
# Only folders whose whole name matches our own pattern count. The glob lists
# them sorted by name, and the names sort by time, so the oldest come first.
backups=()
for dir in "$BACKUP_ROOT"/auto_*; do
    if [ -d "$dir" ] && [[ ${dir##*/} =~ ^auto_${STAMP_REGEX}$ ]]; then
        backups+=("${dir##*/}")
    fi
done
kept=${#backups[@]}
excess=$(( kept - KEEP ))             # negative or 0: nothing to delete
for (( i = 0; i < excess; i++ )); do
    log "Deleting old backup ${backups[i]}"
    # ${BACKUP_ROOT:?} stops the script if the variable were ever empty.
    rm -rf -- "${BACKUP_ROOT:?}/${backups[i]}"
    kept=$(( kept - 1 ))
done

log "Backup $NAME finished ($(du -sh "$FINAL_DIR" | cut -f1)); $kept auto backups kept"
