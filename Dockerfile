# Unfold backend. One stage: the image is the deps plus the source.
#
#   docker build -t unfold .
#   docker run --rm -p 8000:8000 --env-file .env unfold
#
# Without an .env the image still runs: ANALYZER_PROVIDER defaults to fake below,
# which serves deterministic responses and calls nothing on the network.

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    ANALYZER_PROVIDER=fake \
    HOST=0.0.0.0 \
    PORT=8000 \
    SEARCH_CACHE_PATH=/cache/brave.sqlite

WORKDIR /app

# Deps first so a source edit does not reinstall them.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY scripts/ scripts/
COPY tests/fixtures/ tests/fixtures/

# The Brave cache is a volume: a rebuilt image must not throw away paid search results.
RUN mkdir -p /cache && useradd -m -u 1000 app && chown -R app /cache /app
USER app
VOLUME ["/cache"]

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
