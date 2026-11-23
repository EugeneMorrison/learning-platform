#!/usr/bin/env bash
# Local restore orchestration regression. All paths and Docker calls are fixtures.
set -eu
original="$(cd "$(dirname "$0")" && pwd)"
root=$(mktemp -d)
trap 'rm -rf -- "$root"' EXIT
export fixture="$root"
mkdir -p "$root/scripts" "$root/backups/sample" "$root/db" "$root/media"
touch "$root/docker-compose.yml"
sed -e "s|^BACKUP_ROOT=.*|BACKUP_ROOT='$root/backups'|" \
    -e "s|^LOCK_FILE=.*|LOCK_FILE='$root/backup.lock'|" \
    "$original/restore.sh" > "$root/scripts/restore.sh"
echo sample > "$root/backups/sample/db.sqlite3"
tar -czf "$root/backups/sample/media.tar.gz" -C "$root/media" .
(cd "$root/backups/sample" && sha256sum db.sqlite3 media.tar.gz > SHA256SUMS)

# Allow scripted confirmation only in this fixture. Git Bash lacks util-linux
# flock. Linux runs the same regression with the real kernel locks.
function [ {
    if [[ $# == 3 && $1 == -t && $2 == 0 ]]; then return 0; fi
    builtin [ "$@"
}
export -f '['
if command -v flock >/dev/null; then
    DB_DIR="$root/db" sh "$original/db-entrypoint.sh" sh -ec '
        if flock -xn "$DB_DIR/.uchebus-service.lock" true; then exit 1; fi'
    touch "$root/db/.uchebus-restore-in-progress"
    if DB_DIR="$root/db" sh "$original/db-entrypoint.sh" true; then exit 1; fi
    rm "$root/db/.uchebus-restore-in-progress"
else
    flock() { return 0; }
    export -f flock
fi

docker() {
    local cmd="$*" arg out
    echo "$cmd" >> "$fixture/calls"
    case "$cmd" in
        'volume inspect --format '*) echo "$fixture/db" ;;
        'volume inspect '*) ;;
        'ps --quiet --filter '*) echo "${other_holder:-}" ;;
        'compose ps --all --quiet '*) echo "${4:-service}-id" ;;
        'compose ps --status running --services') cat "$fixture/running" ;;
        'inspect --format {{.Image}} '*) echo image ;;
        'inspect --format {{index .Config.Entrypoint 0}} '*) echo /usr/local/bin/uchebus-db-service ;;
        'inspect --format {{range .Mounts}}'*) echo learning-platform_db-data ;;
        'compose stop '*)
            test -f "$fixture/db/.uchebus-restore-in-progress" || return 1
            grep -vx "$3" "$fixture/running" > "$fixture/new" || :
            mv "$fixture/new" "$fixture/running" ;;
        'compose start '*)
            test ! -f "$fixture/db/.uchebus-restore-in-progress" || return 1
            echo "$3" >> "$fixture/running" ;;
        'compose exec -T web '*) ;;
        *'/backup:ro --entrypoint sh image '*) ;;
        'run '*|'compose run '*)
            test -f "$fixture/db/.uchebus-restore-in-progress" && test ! -s "$fixture/running" || return 1
            for arg in "$@"; do
                if [[ "$arg" == *:/out ]]; then
                    out="${arg%:/out}"
                    touch "$out/db.sqlite3" "$out/media.tar.gz"
                fi
            done
            if [[ -n "${fail_at:-}" && "$cmd" == *"$fail_at"* ]]; then return 1; fi ;;
        *) echo "Unexpected Docker call: $cmd" >&2; return 1 ;;
    esac
}
export -f docker
restore() { bash "$root/scripts/restore.sh" "$@" <<< sample; }
reset_fixture() {
    rm -rf -- "$root/backups"/pre-restore_*
    rm -f -- "$root/db/.uchebus-restore-in-progress"
    printf 'web\nexport-worker\n' > "$root/running"
    : > "$root/calls"
}

reset_fixture
restore --check sample
! grep -q 'compose stop' "$root/calls" || exit 1
echo damaged >> "$root/backups/sample/db.sqlite3"
if restore sample; then exit 1; fi
! grep -q 'compose stop' "$root/calls" || exit 1
echo sample > "$root/backups/sample/db.sqlite3"
restore sample
test -f "$root"/backups/pre-restore_*/SHA256SUMS
test "$(tail -1 "$root/calls")" = 'compose start export-worker'
grep -q 'CourseExportJob.objects.all().delete()' "$root/calls"

reset_fixture
if other_holder=unexpected-client restore sample; then exit 1; fi
! grep -q 'Replacing the database\|learning-platform_db-data:/db ' "$root/calls" || exit 1
test ! -e "$root/db/.uchebus-restore-in-progress"

reset_fixture
if fail_at=':/out' restore sample; then exit 1; fi
test ! -e "$root/db/.uchebus-restore-in-progress"
grep -qx web "$root/running"
grep -qx export-worker "$root/running"

reset_fixture
if fail_at='manage.py migrate' restore sample; then exit 1; fi
test -f "$root/db/.uchebus-restore-in-progress"
test ! -s "$root/running"
test -f "$root"/backups/pre-restore_*/SHA256SUMS
sleep 1  # Safety snapshots have second-resolution names.
restore sample
test "$(tail -1 "$root/calls")" = 'compose start export-worker'

reset_fixture
echo web > "$root/running"
restore sample
test "$(cat "$root/running")" = web
echo 'Restore coordination tests passed.'
