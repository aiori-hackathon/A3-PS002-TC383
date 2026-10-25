
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CONSENT_DB=/data/consent.db

WORKDIR /app

# Install dependencies first so Docker can cache this layer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code, tests and demo script
COPY app ./app
COPY tests ./tests
COPY demo.py .
COPY pytest.ini .

# Run as a non-root user; /data holds the SQLite database
RUN useradd --create-home appuser \
    && mkdir /data \
    && chown -R appuser /app /data
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/state')"

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
