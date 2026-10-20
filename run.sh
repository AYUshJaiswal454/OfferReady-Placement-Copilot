#!/usr/bin/env bash
# One-command setup and start (Linux/macOS): ./run.sh
# Creates a virtualenv, installs dependencies and the headless browser, loads the demo data and starts the app.
set -euo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
if [ ! -d .venv ]; then
  echo "Creating virtualenv…"; $PY -m venv .venv
fi
. .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements-dev.txt
python -m playwright install chromium >/dev/null 2>&1 || echo "Note: Chromium download failed; live-link checks will use the HTTP fallback."
command -v tesseract >/dev/null || echo "Note: tesseract not found (apt install tesseract-ocr / brew install tesseract); OCR of images is skipped."
command -v soffice >/dev/null || echo "Note: LibreOffice not found; upload resumes as PDF (DOCX conversion needs soffice)."
[ -f .env ] || cp .env.example .env
if [ ! -f data/.demo-seeded ]; then
  echo "Loading demo data (about 1-2 minutes)…"
  python scripts/seed_demo.py && mkdir -p data && touch data/.demo-seeded
fi
echo
echo "OfferReady is starting at http://localhost:8000"
echo "  Student: demo@student.msot.edu / demo12345    Placement cell: admin@msot.edu / admin12345"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
