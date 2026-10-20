#!/bin/sh
# Production start (Docker, Render, Railway, any VM): `sh scripts/start.sh`
#
# The web server binds 0.0.0.0:$PORT straight away, so hosting platforms see the port open. On the first start
# the demo data is loaded in the background (SEED_DEMO=true), then the background worker takes over the queue.
set -e
cd "$(dirname "$0")/.."
PORT="${PORT:-8000}"
DATA_DIR="${DATA_DIR:-$(pwd)/data}"
export DATA_DIR
mkdir -p "$DATA_DIR"
# The web process serves requests only; one separate worker process runs reviews and scheduled jobs.
export EMBEDDED_WORKER=false

if [ "${SEED_DEMO:-true}" = "true" ] && [ ! -f "$DATA_DIR/.demo-seeded" ]; then
  (
    echo "Loading demo data in the background..."
    if python scripts/seed_demo.py; then touch "$DATA_DIR/.demo-seeded"; else echo "Demo data could not be loaded (see above)."; fi
    exec python -m app.worker
  ) &
else
  python -m app.worker &
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --workers "${WEB_WORKERS:-1}" \
  --proxy-headers --forwarded-allow-ips="*"
