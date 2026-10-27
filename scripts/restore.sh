#!/usr/bin/env bash
# Restore the database and media from a backup made by backup.sh.
#
# Usage (on the server, as root):
#   scripts/restore.sh --check auto_2026-10-27_000003Z   # verify only, changes nothing
#   scripts/restore.sh auto_2026-10-27_000003Z           # restore (asks to confirm)
# The argument is a folder name inside /root/backups or a full path to a folder.
#
# A restore:
#   1. verifies the backup's checksums and (if web is running) its database;
#   2. asks you to type the folder name to confirm;
#   3. stops ONLY the web container (nginx and runner keep running, so the site
#      shows a 502 error page meanwhile);
#   4. saves the current DB and media to /root/backups/pre-restore_<time>/;
#   5. replaces the DB and media with the backup's;
#   6. starts web and waits until it answers (it runs migrations first).
# To undo a restore, restore that pre-restore_* folder the same way.

set -euo pipefail

# Same full PATH as backup.sh, in case this is run from a minimal environment.
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# ---- Settings ---------------------------------------------------------------
BACKUP_ROOT=/root/backups
DB_VOLUME=learning-platform_db-data         # mounted at /app/db in web
MEDIA_VOLUME=learning-platform_media-data   # mounted at /app/media in web
DB_PATH_IN_WEB=/app/db/db.sqlite3           # see backup.sh
HELPER_IMAGE=alpine:3.20                    # throwaway container that edits volumes
LOCK_FILE=/run/lock/uchebus-backup.lock     # shared with backup.sh
WAIT_SECONDS=120                            # how long to wait for web after start

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log() { echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') $*"; }
die() { log "ERROR: $*" >&2; exit 1; }
usage() { echo "Usage: $0 [--check] <backup folder name or full path>" >&2; exit 2; }

# ---- Arguments --------------------------------------------------------------
CHECK_ONLY=no
if [ "${1:-}" = "--check" ]; then CHECK_ONLY=yes; shift; fi
[ $# -eq 1 ] || usage
case "$1" in
    /*) SRC="$1" ;;                  # full path
    *)  SRC="$BACKUP_ROOT/$1" ;;     # folder name inside /root/backups
esac
SRC="${SRC%/}"                       # allow a trailing slash
SRC_NAME="${SRC##*/}"
[ -d "$SRC" ] || die "backup folder not found: $SRC"

cd "$PROJECT_DIR"
[ -f docker-compose.yml ] || die "docker-compose.yml not found in $PROJECT_DIR"

# No backup may run while we restore (and no second restore).
exec 9>"$LOCK_FILE"
flock -n 9 || die "a backup or restore is running (lock: $LOCK_FILE)"
umask 077

web_is_running() {
    docker compose ps --status running --services | grep -x web >/dev/null
}

# Python program run in the web container: integrity check and a summary of
# a database file (sys.argv[1]). Opens it read-only.
CHECK_PY=$(cat <<'PY'
import sqlite3
import sys

db = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True, timeout=30)
problems = [row[0] for row in db.execute("PRAGMA integrity_check")]
if problems != ["ok"]:
    print("  integrity_check FAILED:", *problems[:20], sep="\n    ")
    sys.exit(1)
print("  integrity_check: ok")
app, name = db.execute(
    "SELECT app, name FROM django_migrations ORDER BY id DESC LIMIT 1").fetchone()
print(f"  newest applied migration: {app}.{name}")
print("  rows per table (empty tables not shown):")
tables = [row[0] for row in db.execute(
    "SELECT name FROM sqlite_master WHERE type = 'table'"
    " AND name NOT LIKE 'sqlite_%' ORDER BY name")]
for table in tables:
    count = db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    if count:
        print(f"    {table}: {count}")
PY
)

# ---- 1. Verify the backup ---------------------------------------------------
log "Checking backup $SRC"
# docker run -v NAME:/path silently creates an empty volume if NAME is wrong,
# so make sure both exist before any container mounts them.
for volume in "$DB_VOLUME" "$MEDIA_VOLUME"; do
    docker volume inspect "$volume" >/dev/null || die "docker volume $volume not found"
done
for file in SHA256SUMS db.sqlite3 media.tar.gz; do
    [ -f "$SRC/$file" ] || die "$file is missing in $SRC"
done
# sha256sum --check reads the "hash  name" lines and recomputes every file.
(cd "$SRC" && sha256sum --check --quiet SHA256SUMS) \
    || die "checksum mismatch: this backup is damaged, do not use it"
log "Checksums: ok"
MEDIA_FILES=$(tar -tzf "$SRC/media.tar.gz" | awk '!/\/$/ { n++ } END { print n + 0 }')
log "media.tar.gz is readable: $MEDIA_FILES files"

# The database check runs in the running web container on a temporary copy
# in its /tmp, so the live site is not affected.
if web_is_running; then
    log "Checking the backup's database (on a copy inside the web container)"
    tmp_dir="/tmp/restore-check-$$"
    docker compose exec -T web mkdir -p "$tmp_dir"
    # db.sqlite3 plus a -journal/-wal file if the backup has one.
    for file in "$SRC"/db.sqlite3*; do
        docker compose cp "$file" "web:$tmp_dir/"
    done
    check_status=0
    docker compose exec -T web python -I -c "$CHECK_PY" "$tmp_dir/db.sqlite3" || check_status=$?
    docker compose exec -T web rm -rf "$tmp_dir"
    [ "$check_status" -eq 0 ] || die "the backup's database failed the check; not restoring it"
elif [ "$CHECK_ONLY" = yes ]; then
    die "web is not running: --check needs it to read the database"
else
    log "web is not running: skipping the database check (checksums are ok)"
fi

if [ "$CHECK_ONLY" = yes ]; then
    log "Check finished: $SRC_NAME looks good. Nothing was changed."
    exit 0
fi

# ---- 2. Confirm -------------------------------------------------------------
[ -t 0 ] || die "restore needs an interactive terminal to confirm"
SAFETY_NAME="pre-restore_$(date -u +%Y-%m-%d_%H%M%SZ)"
SAFETY_DIR="$BACKUP_ROOT/$SAFETY_NAME"
echo
echo "This REPLACES the live database and ALL uploaded media with:"
echo "  $SRC"
if [ -f "$SRC/info.txt" ]; then sed 's/^/    /' "$SRC/info.txt"; fi
echo "The web container is stopped meanwhile (visitors get an error page)."
echo "The current data is saved first to $SAFETY_DIR"
echo
read -r -p "Type the backup folder name ($SRC_NAME) to restore it: " answer
[ "$answer" = "$SRC_NAME" ] || die "not confirmed; nothing was changed"

# What to do if something fails from here on depends on how far we got.
STAGE=confirmed
on_exit() {
    local status=$?
    if [ "$status" -eq 0 ]; then return 0; fi
    # An unfinished safety copy is useless: remove it.
    if [ -d "$SAFETY_DIR.partial" ]; then rm -rf -- "$SAFETY_DIR.partial"; fi
    case "$STAGE" in
        stopped)
            log "RESTORE FAILED before any data was changed. Starting web again."
            docker compose start web \
                || log "ERROR: could not start web; run: cd $PROJECT_DIR && docker compose start web"
            ;;
        changed)
            log "RESTORE FAILED after the live data was changed; web may be stopped."
            log "The data from before this restore is in $SAFETY_DIR"
            log "  put it back:  $0 $SAFETY_NAME"
            log "  web logs:     cd $PROJECT_DIR && docker compose logs --tail 50 web"
            ;;
    esac
}
trap on_exit EXIT

# ---- 3. Stop web ------------------------------------------------------------
log "Stopping web (nginx and runner keep running)"
docker compose stop web
STAGE=stopped

# ---- 4. Safety copy of the current data -------------------------------------
# web is stopped, so nothing writes to the DB and a plain file copy is
# consistent. The folder has the same layout as a backup, so this script can
# restore it.
log "Saving the current data to $SAFETY_DIR"
mkdir "$SAFETY_DIR.partial"
# db.sqlite3 plus a -journal/-wal file if one exists (normally none after a
# clean stop). :ro = the current data is only read here.
docker run --rm --network none \
    -v "$DB_VOLUME:/db:ro" -v "$SAFETY_DIR.partial:/out" \
    "$HELPER_IMAGE" sh -c 'cp /db/db.sqlite3* /out/'
docker run --rm --network none \
    -v "$MEDIA_VOLUME:/media:ro" -v "$SAFETY_DIR.partial:/out" \
    "$HELPER_IMAGE" tar -czf /out/media.tar.gz -C /media .
{
    echo "backup:      $SAFETY_NAME"
    echo "created:     $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
    echo "note:        live data saved by restore.sh before restoring $SRC_NAME"
    echo "git commit:  $(git -C "$PROJECT_DIR" log -1 --format='%h %s' 2>/dev/null || echo unknown)"
} > "$SAFETY_DIR.partial/info.txt"
(cd "$SAFETY_DIR.partial" && sha256sum db.sqlite3* media.tar.gz info.txt > SHA256SUMS)
chmod 600 "$SAFETY_DIR.partial"/*
mv -- "$SAFETY_DIR.partial" "$SAFETY_DIR"

# ---- 5. Replace the data ----------------------------------------------------
STAGE=changed
log "Replacing the database"
# Delete the current DB together with any -journal/-wal/-shm file (a leftover
# from the old DB would damage the restored one), then copy the backup's in.
docker run --rm --network none \
    -v "$DB_VOLUME:/db" -v "$SRC:/backup:ro" \
    "$HELPER_IMAGE" sh -c 'rm -f /db/db.sqlite3 /db/db.sqlite3-* && cp /backup/db.sqlite3* /db/'
log "Replacing media"
# Empty the media volume (the volume itself stays), then unpack the archive.
docker run --rm --network none \
    -v "$MEDIA_VOLUME:/media" -v "$SRC:/backup:ro" \
    "$HELPER_IMAGE" sh -c 'find /media -mindepth 1 -delete && tar -xzf /backup/media.tar.gz -C /media'

# ---- 6. Start web and wait for it -------------------------------------------
log "Starting web (it applies migrations first, if any)"
docker compose start web
# Any HTTP answer, even an error status, means Django is up; a refused
# connection means it is still starting.
PING_PY=$(cat <<'PY'
import urllib.error
import urllib.request

try:
    urllib.request.urlopen("http://127.0.0.1:8000/", timeout=3)
except urllib.error.HTTPError:
    pass
PY
)
deadline=$(( SECONDS + WAIT_SECONDS ))       # SECONDS: bash's own seconds counter
until docker compose exec -T web python -I -c "$PING_PY" >/dev/null 2>&1; do
    if [ "$SECONDS" -ge "$deadline" ]; then
        die "web did not answer within ${WAIT_SECONDS}s"
    fi
    sleep 3
done
log "web is answering. Checking the restored database:"
docker compose exec -T web python -I -c "$CHECK_PY" "$DB_PATH_IN_WEB"

STAGE=finished
log "Restore of $SRC_NAME finished."
log "The previous data stays in $SAFETY_DIR (delete it by hand when no longer needed)."
