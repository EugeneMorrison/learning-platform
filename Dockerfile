# =============================================================
# Stage 1: Build React frontend
# =============================================================
# Uses Node to install npm packages and run "npm run build".
# The output (frontend/dist/) is copied to the next stage.
# Node is NOT included in the final image — only used here.
# =============================================================
FROM node:20-alpine AS frontend-build

WORKDIR /app/frontend

# Copy package files first (Docker caches this layer if they don't change)
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Copy frontend source and build
COPY frontend/ ./
RUN npm run build


# =============================================================
# Stage 1b: Official Python 3.10 image (source for the code runner)
# =============================================================
# Debian — the base of python:3.12-slim — has no apt package for
# python3.10, so we pull the official 3.10 image and copy just the
# interpreter + standard library into the final image below. Pinned
# to the same Debian release (bookworm) as the 3.12 base so the
# shared system libraries (OpenSSL, sqlite, ...) are compatible.
# =============================================================
FROM python:3.10-slim-bookworm AS py310


# =============================================================
# Stage 2: Django backend + built React files
# =============================================================
# Uses Python to run Django. Copies the React build from stage 1.
# This is the final image that actually runs.
# =============================================================
FROM python:3.12-slim-bookworm

WORKDIR /app

# --- Python 3.10 for the multi-version code runner -----------------
# Copy only what's needed to run plain Python 3.10 scripts: the
# interpreter, its standard library, and the shared libpython. Then
# refresh the linker cache and assert the binary actually runs (this
# fails the build early if anything is missing).
COPY --from=py310 /usr/local/bin/python3.10 /usr/local/bin/python3.10
COPY --from=py310 /usr/local/lib/python3.10 /usr/local/lib/python3.10
COPY --from=py310 /usr/local/lib/libpython3.10.so.1.0 /usr/local/lib/libpython3.10.so.1.0
RUN ldconfig && python3.10 --version

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Django project files
COPY manage.py .
COPY backend/ backend/
COPY api/ api/
COPY templates/ templates/
COPY static/ static/
COPY fixtures.json .
COPY python_strings_lesson.html .

# Copy React build output from stage 1
COPY --from=frontend-build /app/frontend/dist frontend/dist/

# Database directory (mounted as a Docker volume for persistence)
ENV DB_DIR=/app/db
RUN mkdir -p /app/db

# Port Django will listen on
EXPOSE 8000

# On startup: run migrations, load test data, start server
CMD ["bash", "-c", "\
    echo 'Running migrations...' && \
    python manage.py migrate && \
    python manage.py loaddata fixtures.json 2>/dev/null || true && \
    echo 'Starting server on port 8000...' && \
    exec python manage.py runserver 0.0.0.0:8000 \
"]
