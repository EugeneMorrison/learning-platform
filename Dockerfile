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
# Stage 2: Django backend + built React files
# =============================================================
# Uses Python to run Django. Copies the React build from stage 1.
# This is the final image that actually runs. Student code never
# runs here: that's the runner service (runner/Dockerfile).
# =============================================================
FROM python:3.12-slim-bookworm

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Django project files
COPY manage.py .
COPY backend/ backend/
COPY api/ api/
COPY templates/ templates/
COPY static/ static/
COPY python_strings_lesson.html .

# Copy React build output from stage 1
COPY --from=frontend-build /app/frontend/dist frontend/dist/

# Database directory (mounted as a Docker volume for persistence)
ENV DB_DIR=/app/db
RUN mkdir -p /app/db

# /app (code, database volume, media volume, static files) is
# root-only: the server runs as root and nothing else needs it.
RUN chmod 0700 /app

# Port Django will listen on
EXPOSE 8000

# On startup: run migrations, collect static files, start server. No sample
# data is loaded here: production keeps only what is in its database volume
# (local sample accounts and a course come from "manage.py seed_data").
# A failed migration stops the start instead of being ignored.
CMD ["bash", "-c", "\
    echo 'Running migrations...' && \
    python manage.py migrate && \
    python manage.py collectstatic --noinput && \
    echo 'Starting server on port 8000...' && \
    exec python manage.py runserver 0.0.0.0:8000 \
"]
