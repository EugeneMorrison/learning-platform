# =============================================================
# Code runner: runs student Python code for the web service
# =============================================================
# Its own container (runner/server.py; docker-compose.yml locks
# it down: no volumes, no secrets but RUNNER_TOKEN, internal
# network only, read-only filesystem). The build context is
# runner/ alone, so nothing else of the project (database, .env,
# Django code) can end up in this image.
# =============================================================


# =============================================================
# Stage 1: Official Python 3.10 image (source for "Python 3.10")
# =============================================================
# Debian — the base of python:3.12-slim — has no apt package for
# python3.10, so we pull the official 3.10 image and copy just the
# interpreter + standard library into the final image below. Pinned
# to the same Debian release (bookworm) as the 3.12 base so the
# shared system libraries (OpenSSL, sqlite, ...) are compatible.
# =============================================================
FROM python:3.10-slim-bookworm AS py310


# =============================================================
# Stage 2: the runner
# =============================================================
FROM python:3.12-slim-bookworm

# --- Python 3.10 next to the base image's 3.12 ----------------------
# Copy only what's needed to run plain Python 3.10 scripts: the
# interpreter, its standard library, and the shared libpython. Then
# refresh the linker cache and assert both binaries actually run (this
# fails the build early if anything is missing).
COPY --from=py310 /usr/local/bin/python3.10 /usr/local/bin/python3.10
COPY --from=py310 /usr/local/lib/python3.10 /usr/local/lib/python3.10
COPY --from=py310 /usr/local/lib/libpython3.10.so.1.0 /usr/local/lib/libpython3.10.so.1.0
RUN ldconfig && python3.10 --version && python3.12 --version

# --- One unprivileged user per concurrency slot ---------------------
# Student code runs as runner<slot> (uid/gid 11000 + slot), never as
# root and never as the user of another run happening at the same
# time. They own nothing. RUNNER_SLOTS in docker-compose.yml must not
# exceed the number of users made here (the server refuses to start).
RUN for slot in 0 1 2 3; do \
        groupadd --system --gid "1100${slot}" "runner${slot}" \
     && useradd --system --uid "1100${slot}" --gid "1100${slot}" --no-create-home \
            --home-dir /nonexistent --shell /usr/sbin/nologin "runner${slot}" \
     || exit 1; \
    done

# The server and its tests: /srv/runner is the "runner" package.
WORKDIR /srv
COPY __init__.py sandbox.py server.py runner/
COPY tests/ runner/tests/

# /work: per-run directories (docker-compose.yml mounts a tmpfs here,
# root-owned 0711: a run can enter its own directory, not list others).
RUN mkdir -p /work && chmod 0711 /work

EXPOSE 8001

# Listens on the internal network only (docker-compose.yml publishes
# no ports). Runs as root to switch to the slot users; compose drops
# every capability but SETUID, SETGID, KILL and CHOWN.
CMD ["python", "-I", "-B", "/srv/runner/server.py", "--host", "0.0.0.0", "--port", "8001"]
