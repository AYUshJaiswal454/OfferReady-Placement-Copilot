# Scalability: 100–150 students at once, and beyond

## Setup

* **Machine:** one 2-vCPU Intel Xeon (2.8 GHz) cloud VM with 8 GB RAM. The load generator ran on the same machine,
  so the server had less than the full 2 vCPUs.
* **Server:** `uvicorn app.main:app --workers 2`, each process with its embedded background worker
  (`WORKER_CONCURRENCY=2`), SQLite in WAL mode, 3,000 active jobs in the index (`loadtest/prepare.py`).
* **AI:** calls went to the local stub API with 0.8 s added latency per call, which behaves like a hosted model.
  Interview answers therefore include ~0.8 s that is the model's, not the server's.
* **Live-link checks:** these used the HTTP fallback (`PLAYWRIGHT_ENABLED=false`) because the resumes link to
  made-up sites. Real Chromium checks run in the background queue, limited to 2 pages per worker. They make
  project reviews slower but don't change page latency.
* **Script:** `loadtest/run.py`. Each simulated student signs up, consents, sets a target role and uploads a
  resume (parse, OCR, page renders, 16 checks and follow-up tasks, all in the background). They poll until the review
  is ready, then keep using the app with 1–4 s of thinking between actions: readiness, report, a job search, tracker
  add/update/board, notifications, chat, and starting and answering a mock interview. Students arrive over 20 s,
  then each stage runs for 2 minutes (90 s for the stress stages). Raw results are in `loadtest/results/`.

## Results

| Students at once | Requests | Errors | Throughput | Readiness p50 / p95 | Report p95 | Job search p95 | Tracker update p95 | Interview answer p95* | Resume upload p95 | Review ready p50 / p95 |
|---|---|---|---|---|---|---|---|---|---|---|
| **50** | 2,548 | **0** | 20.6 req/s | 4 / 12 ms | 18 ms | 52 ms | 8 ms | 818 ms | 172 ms | 3.0 / 3.9 s |
| **100** | 5,152 | **0** | 41.6 req/s | 5 / 38 ms | 60 ms | 157 ms | 16 ms | 826 ms | 395 ms | 5.2 / 7.3 s |
| **150** | 7,388 | **0** | 59.3 req/s | 6 / 167 ms | 155 ms | 198 ms | 38 ms | 882 ms | 612 ms | 10.6 / 15.2 s |
| 250 | 9,070 | 0 | 96.3 req/s | 38 / 362 ms | 326 ms | 487 ms | 340 ms | 1,375 ms | 251 ms | 35 / 58 s |
| 400 | 12,657 | 0 | 133.8 req/s | 113 / 482 ms | 488 ms | 580 ms | 443 ms | 1,502 ms | 2,723 ms | 44 / 68 s (152 still queued) |
| 600 | 15,312 | 0 | 163.0 req/s | 190 / 661 ms | 672 ms | 917 ms | 574 ms | 1,778 ms | 8,440 ms | 46 / 64 s (435 still queued) |

\* includes the 0.8 s simulated model latency.

**At the required 100–150 concurrent students:** zero errors, readiness, report, job search and tracker answered in under 200 ms at p95 (every page under 400 ms), and every
uploaded resume was fully reviewed within about 15 s even though all 150 uploaded at once.

## Breaking point

Nothing returned an error even at 600 simultaneous students (four times the requirement). What degrades first,
in order:

1. **Resume review throughput** (CPU-bound PDF parsing, OCR and rendering) tops out at about **2.7 reviews per
   second, roughly 165 per minute, on 2 vCPUs.** From about 300 students uploading at the same moment, reviews
   queue. The queue is prioritised, so a new resume review always runs before slow project clones and crawls.
   Students see a progress bar, and the rest of the app stays usable while they wait.
2. **Sign-up and upload requests** slow down beyond ~400 simultaneous arrivals (p95 2.8 s at 400, 8 s at 600).
   Password hashing (scrypt) and receiving the file compete with the review workers for the same 2 CPUs.
3. **Interactive pages** were still under 1 s at p95 at 600 students.

For one 2-vCPU server we therefore rate the comfortable capacity at **about 250 students active at the same
moment**. That is far more than the number logged in at once in a typical college placement season.

## What made this possible (and what we fixed while testing)

* The first run at 150 students showed job search at 4 s p95 with 3,000 jobs, which slowed everything else. Search
  now keeps the job index in memory (refreshed when the index changes), evaluates the boolean query with per-term
  set indexes shared by all students, precomputes job skill weights at crawl time, and builds result cards only for
  the visible page. Warm searches dropped from about 350 ms of CPU to about 10 ms.
* The queue was first-in-first-out, so new resume reviews waited behind hundreds of project clones. Tasks now have
  priorities (resume and interview scoring first, crawling last): review p95 at 150 students fell from 61 s to 15 s.
* PDFium (page rendering) is not thread-safe, so all PDFium calls now go through one lock and pages are closed
  explicitly.
* Rate limits were per IP and would have locked out a whole lab behind one campus NAT. They are now generous per
  IP, with brute-force protection per account, and `TRUST_PROXY` uses the real client IP behind a reverse proxy.

## Scaling further

| Need | Change |
|---|---|
| Faster review turnaround in placement season | Run `python -m app.worker` processes on extra cores or machines (`docker compose --profile scale up --scale worker=3`) and set `EMBEDDED_WORKER=false` on the web processes. Review throughput grows with cores. |
| More than ~400 students active at once | PostgreSQL (`DATABASE_URL=postgresql://…`, `--profile postgres`) and more `uvicorn` workers behind nginx or Caddy (`TRUST_PROXY=true`). |
| Interviews for a whole batch at once with Ollama | Local-model throughput depends on the GPU, so measure yours with `scripts/prove_ollama.py` (it reports latency per call). Run Ollama on a GPU machine and point `OLLAMA_BASE_URL` at it. The orchestrator limits concurrent requests per provider and falls back to rule-based turns if the model is too slow, so interviews never stall. |
| Very large job index (50k+) | The in-memory index is about 2 KB per job. Beyond that, move the term index into PostgreSQL full-text search. |

To reproduce: `DATA_DIR=/tmp/load python loadtest/prepare.py --jobs 3000`, start the server as above with
`RATE_LIMIT_SCALE=100` (the load generator signs up hundreds of accounts from one IP), then run
`python loadtest/run.py --stages 50,100,150 --duration 120`.
