# ---- Stage 1: build the React UI ----
FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: API + built UI ----
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CONSENT_DB=/data/consent.db \
    LOG_DIR=/data/logs

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY tests ./tests
COPY demo.py pytest.ini ./
COPY --from=ui /ui/dist ./app/static
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# /data holds the SQLite database and error log; the entrypoint drops root before starting the app
RUN useradd --create-home appuser && mkdir -p /data/logs && chown -R appuser:appuser /app /data \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000
# Render provides $PORT; locally it defaults to 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=5 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT','8000'))"

ENTRYPOINT ["docker-entrypoint.sh"]
# --proxy-headers: the host's HTTPS proxy terminates TLS and tells the app via X-Forwarded-* headers
CMD ["sh", "-c", "exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
