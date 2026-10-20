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
# Small containers (e.g. Render's free 512 MB plan): headless Chromium does not fit next to the app, so live-link
# checks use the plain HTTP check unless PLAYWRIGHT_ENABLED is set explicitly.
if [ -z "${PLAYWRIGHT_ENABLED:-}" ]; then
  LIMIT=$(cat /sys/fs/cgroup/memory.max 2>/dev/null || cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null || echo max)
  case "$LIMIT" in
    ''|max) ;;
    *) if [ "$LIMIT" -lt 1073741824 ] 2>/dev/null; then
         export PLAYWRIGHT_ENABLED=false
         export WORKER_CONCURRENCY="${WORKER_CONCURRENCY:-2}"
         echo "Memory limit under 1 GB: live-link checks use HTTP, ${WORKER_CONCURRENCY} reviews at a time."
       fi ;;
  esac
fi
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
