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
# Mount a volume at /data to keep data across restarts (docker-compose does this).
ENV PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT', '8000'), timeout=4)"

# Binds 0.0.0.0:$PORT immediately; loads the demo data in the background on first start (SEED_DEMO=true).
CMD ["sh", "scripts/start.sh"]
