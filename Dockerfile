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
# This is the final image that actually runs.
# =============================================================
FROM python:3.12-slim

WORKDIR /app

# Install Python 3.10 alongside the default 3.12
RUN apt-get update && apt-get install -y --no-install-recommends python3.10 && rm -rf /var/lib/apt/lists/*

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
