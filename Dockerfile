# OfferReady — one image for the web app and the background worker.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright DATA_DIR=/data
# Set to 0 to leave out LibreOffice (about 400 MB); students then upload resumes as PDF only.
ARG WITH_LIBREOFFICE=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends git tesseract-ocr fonts-crosextra-carlito fonts-crosextra-caladea \
      fonts-liberation libgl1 libglib2.0-0 \
 && if [ "$WITH_LIBREOFFICE" = "1" ]; then apt-get install -y --no-install-recommends libreoffice-writer-nogui; fi \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements-dev.txt \
 && python -m playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*

COPY app ./app
COPY scripts ./scripts
COPY tests ./tests
COPY loadtest ./loadtest

RUN useradd --create-home --uid 1000 offerready && mkdir -p /data && chown -R offerready /data /app
USER offerready
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

# Seed the demo data on first start (SEED_DEMO=true), then serve.
CMD ["sh", "-c", "if [ \"${SEED_DEMO:-true}\" = \"true\" ] && [ ! -f /data/.demo-seeded ]; then python scripts/seed_demo.py && touch /data/.demo-seeded; fi; exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_WORKERS:-2} --proxy-headers"]
