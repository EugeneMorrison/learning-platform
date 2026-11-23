#!/usr/bin/env bash
# Restore the database and media from a backup made by backup.sh.
#
# Usage (on the server, as root):
#   scripts/restore.sh --check auto_2026-10-27_000003Z   # verify only, changes nothing
#   scripts/restore.sh auto_2026-10-27_000003Z           # restore (asks to confirm)
# The argument is a folder name inside /root/backups or a full path to a folder.
#
# A restore:
#   1. verifies the backup's checksums and its database on a disposable copy;
#   2. asks you to type the folder name to confirm;
#   3. fences database access and stops web and the export worker;
#   4. saves the current DB and media to /root/backups/pre-restore_<time>/;
#   5. replaces the DB and media with the backup's;
#   6. migrates and verifies offline, starts web, then resumes the worker.
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
if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
    sys.exit("  foreign_key_check FAILED")
app, name = db.execute(
    "SELECT app, name FROM django_migrations ORDER BY id DESC LIMIT 1").fetchone()
print(f"  newest applied migration: {app}.{name}")
print("  rows per table (empty tables not shown):")
tables = [row[0] for row in db.execute(
    "SELECT name FROM sqlite_master WHERE type = 'table'"
    " AND name NOT LIKE 'sqlite_%' ORDER BY name")]
for table in tables:
    quoted = table.replace('"', '""')
    count = db.execute(f'SELECT COUNT(*) FROM "{quoted}"').fetchone()[0]
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

# Use the installed web image without mounting the live DB or loading .env.
# This also works when recovering from an interrupted restore with web stopped.
web_id=$(docker compose ps --all --quiet web)
[ -n "$web_id" ] || die "web container not found"
web_image=$(docker inspect --format '{{.Image}}' "$web_id")
docker run --rm --network none -v "$SRC:/backup:ro" --entrypoint sh "$web_image" -ec \
    'cp /backup/db.sqlite3* /tmp/ && exec python -I -c "$1" /tmp/db.sqlite3' sh "$CHECK_PY" \
    || die "the backup database failed verification"

if [ "$CHECK_ONLY" = yes ]; then
    log "Check finished: $SRC_NAME looks good. Nothing was changed."
    exit 0
fi

# ---- 2. Confirm -------------------------------------------------------------
[ -t 0 ] || die "restore needs an interactive terminal to confirm"
SAFETY_NAME="pre-restore_$(date -u +%Y-%m-%d_%H%M%SZ)"
SAFETY_DIR="$BACKUP_ROOT/$SAFETY_NAME"
[ ! -e "$SAFETY_DIR" ] && [ ! -e "$SAFETY_DIR.partial" ] || die "safety snapshot name already exists; retry"
echo
echo "This REPLACES the live database and ALL uploaded media with:"
echo "  $SRC"
if [ -f "$SRC/info.txt" ]; then sed 's/^/    /' "$SRC/info.txt"; fi
echo "Web and export-worker will be stopped while the database and media are replaced."
echo "The current data is saved first to $SAFETY_DIR"
echo
read -r -p "Type the backup folder name ($SRC_NAME) to restore it: " answer
[ "$answer" = "$SRC_NAME" ] || die "not confirmed; nothing was changed"

# What to do if something fails from here on depends on how far we got.
db_mount=$(docker volume inspect --format '{{.Mountpoint}}' "$DB_VOLUME")
[[ "$db_mount" = /* && -d "$db_mount" ]] || die "DB volume must be local to this VPS"
marker="$db_mount/.uchebus-restore-in-progress"
worker_id=$(docker compose ps --all --quiet export-worker)
# Refuse to restore against older service containers that do not honor the fence.
for id in "$web_id" $worker_id; do
    [ "$(docker inspect --format '{{index .Config.Entrypoint 0}}' "$id")" = /usr/local/bin/uchebus-db-service ] \
        || die "installed web/worker must use the restore-aware entrypoint"
    [ "$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/app/db"}}{{.Name}}{{end}}{{end}}' "$id")" = "$DB_VOLUME" ] \
        || die "service is not using the expected database volume"
done
was_running=$(docker compose ps --status running --services)
interrupted=no
if [ -e "$marker" ]; then interrupted=yes; fi
STAGE=stopping
on_exit() {
    local status=$?
    if [ "$status" -eq 0 ]; then return 0; fi
    # An unfinished safety copy is useless: remove it.
    if [ -d "$SAFETY_DIR.partial" ]; then rm -rf -- "$SAFETY_DIR.partial"; fi
    case "$STAGE" in
        stopping|stopped)
            if [ "$interrupted" = no ]; then
                rm -f -- "$marker"
                flock -u 8
                for service in web export-worker; do
                    if grep -qx "$service" <<<"$was_running"; then
                        docker compose start "$service" || log "Could not restart $service"
                    fi
                done
            fi
            ;;
        changed)
            log "RESTORE FAILED. The persistent restore marker blocks web and worker startup."
            log "The data from before this restore is in $SAFETY_DIR"
            log "  put it back:  $0 $SAFETY_NAME"
            log "  web logs:     cd $PROJECT_DIR && docker compose logs --tail 50 web"
            ;;
        verified)
            log "Restored DB passed verification. Check service startup before resuming exports."
            ;;
    esac
}
exec 8>>"$db_mount/.uchebus-service.lock"
trap on_exit EXIT
trap 'exit 1' HUP INT TERM

# ---- 3. Stop web ------------------------------------------------------------
if [ "$interrupted" = no ]; then
    printf '%s\n' "$was_running" > "$marker"
fi
sync -f "$marker"
log "Stopping SQLite clients"
if [ -n "$worker_id" ]; then docker compose stop export-worker; fi
docker compose stop web
flock -xn 8 || die "another process holds the database service lock"
holders=$(docker ps --quiet --filter "volume=$DB_VOLUME")
[ -z "$holders" ] || die "another running container mounts the database volume"
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
sync -f "$SAFETY_DIR"

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

# ---- 6. Verify while both services are fenced -------------------------------
# Maintenance is the only deliberate bypass of the normal shared lock.
log "Migrating and checking the restored DB before admitting traffic"
docker compose run --rm --no-deps -T --entrypoint sh web -ec '
    python manage.py migrate --noinput
    python manage.py shell -c "from api.models import CourseExportJob; CourseExportJob.objects.all().delete()"
    exec python -I -c "$1" "$2"
' sh "$CHECK_PY" "$DB_PATH_IN_WEB"
resume_worker=no
if grep -qx export-worker "$marker"; then resume_worker=yes; fi
STAGE=verified
rm -- "$marker"
flock -u 8
docker compose start web
PING_PY=$(cat <<'PY'
import json
import urllib.request

req = urllib.request.Request("http://127.0.0.1:8000/api/status/", headers={"Host": "uchebus.ru"})
with urllib.request.urlopen(req, timeout=3) as response:
    raise SystemExit(json.load(response).get("status") != "ok")
PY
)
deadline=$(( SECONDS + WAIT_SECONDS ))       # SECONDS: bash's own seconds counter
until docker compose exec -T web python -I -c "$PING_PY" >/dev/null 2>&1; do
    if [ "$SECONDS" -ge "$deadline" ]; then
        die "web did not answer within ${WAIT_SECONDS}s"
    fi
    sleep 3
done
if [ "$resume_worker" = yes ]; then docker compose start export-worker; fi

STAGE=finished
log "Restore of $SRC_NAME finished."
log "The previous data stays in $SAFETY_DIR (delete it by hand when no longer needed)."
