# ==============================================================================
# Stage 1: Build NEXVORA React TypeScript PWA
# ==============================================================================
FROM node:22-alpine AS frontend-builder

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
RUN npm run build

# ==============================================================================
# Stage 2: Production FastAPI + Trading Hub 3.0 Engine + Built PWA
# ==============================================================================
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NEXVORA_ENV=production \
    NEXVORA_DATA_MODE=auto \
    COOKIE_SECURE=true \
    COOKIE_SAMESITE=lax \
    FRONTEND_DIST_DIR=/app/frontend/dist \
    PORT=8000

WORKDIR /app

# Fonts: the signal card bundles Vazirmatn (Arabic/Persian glyphs) and falls back
# to DejaVu for Latin/mono runs. Without the bundled font Persian text renders as
# empty boxes in the Telegram card.
RUN apt-get update && \
    apt-get install -y --no-install-recommends fonts-dejavu-core && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user for hardened runtime
RUN groupadd --system nexvora && useradd --system --gid nexvora --create-home nexvora

# Install setuptools & wheel first so legacy setup.py deps (e.g. sgmllib3k for feedparser)
# build cleanly under modern pip without needing gcc or failing PEP 517 isolation.
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir "setuptools<81" wheel && \
    pip install --no-cache-dir --prefer-binary -r /app/backend/requirements.txt

# Copy backend application, bundled assets (Vazirmatn fonts for signal cards) and
# the built frontend PWA bundle. Omitting assets/ silently degrades Telegram cards.
COPY backend/app /app/backend/app
COPY backend/assets /app/backend/assets
COPY --from=frontend-builder /build/frontend/dist /app/frontend/dist

# Ensure writable data directory if SQLite fallback or Railway Volume is mounted at /app/data
RUN mkdir -p /app/data && chown -R nexvora:nexvora /app

USER nexvora
WORKDIR /app/backend

EXPOSE 8000

# Single worker (--workers 1) is intentional so the background Trading Hub 3.0
# scanner, position tracker, and Telegram broadcaster run once without duplicate signals.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
