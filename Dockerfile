FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # In a container we are by definition not in local dev: refuse to boot
    # with the dev-secret fallback. See app/main.py.
    REQUIRE_TOOL_SECRET=1 \
    # Redeploys replace the container; agreements must land on a mounted
    # volume, not the container filesystem.
    DB_PATH=/data/agreements.db

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY config/ config/
COPY prompts/ prompts/

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown appuser:appuser /data
USER appuser

EXPOSE 8000

# python:*-slim has no curl; stdlib does the same job.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8000'), timeout=4)"

# One worker on purpose: app/store.py keeps per-call negotiation state in a
# process-local dict. A second worker would split a call's requests across
# processes and reset the concession ladder mid-negotiation.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
