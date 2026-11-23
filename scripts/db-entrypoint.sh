#!/bin/sh
set -eu
# Keep the shared lock across exec, including migrations and the lifetime of
# the web server. restore.sh takes the exclusive side of the same inode.
exec flock --shared --no-fork "${DB_DIR:?}/.uchebus-service.lock" sh -ec '
    if [ -e "$DB_DIR/.uchebus-restore-in-progress" ]; then
        echo "Database restore is incomplete. See scripts/restore.sh." >&2
        exit 1
    fi
    exec "$@"
' sh "$@"
