"""Load test: N simulated students using OfferReady at the same time.

Every virtual student signs up, gives consent, uploads a resume (the heaviest operation: parsing, OCR, page
renders and 16 checks run in the background worker), then keeps using the app for the whole stage with 1-4 s of
"thinking" between actions: readiness, report, job search, tracker updates, notifications, chat, and a mock
interview with answers. AI calls go to whatever provider the server is configured with; for repeatable numbers
point the server at the local stub (tests/llm_stub.py) whose "slow" models add hosted-API-like latency.

Usage (server already running):
    python loadtest/run.py --base http://127.0.0.1:8000 --stages 50,100,150 --duration 120
Results are written to loadtest/results/<timestamp>.json and summarised on stdout.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

try:
    import httpx
except ImportError:  # pragma: no cover
    import httpx2 as httpx  # type: ignore

ROOT = Path(__file__).resolve().parent.parent
RESUMES = sorted((ROOT / "tests" / "fixtures" / "resumes").glob("resume_*.pdf"))
H = {"X-Requested-With": "offerready"}
ANSWERS = [
    "I'm a final-year CSE student who builds full stack apps with React and Node.js; my main project is a real-time Q&A app.",
    "The frontend is React, the API is Express on Node.js, MongoDB stores data and Socket.io handles chat. I built auth and chat.",
    "A hash map hashes the key to a bucket; collisions are chained or probed, and lookups are O(1) on average.",
    "I don't know that one well.",
]


class Metrics:
    def __init__(self) -> None:
        self.lat: dict[str, list[float]] = defaultdict(list)
        self.status: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        self.errors: dict[str, list[str]] = defaultdict(list)
        self.review_seconds: list[float] = []
        self.reviews_pending = 0

    def add(self, name: str, ms: float, status: int) -> None:
        self.lat[name].append(ms)
        self.status[name][status] += 1

    def fail(self, name: str, err: str) -> None:
        self.status[name][0] += 1
        if len(self.errors[name]) < 5:
            self.errors[name].append(err[:200])

    def summary(self) -> dict:
        out = {}
        for name in sorted(self.status):
            lat = sorted(self.lat.get(name, []))
            total = sum(self.status[name].values())
            bad = sum(n for code, n in self.status[name].items() if code == 0 or code >= 500)
            out[name] = {
                "requests": total, "errors": bad, "rate_limited": self.status[name].get(429, 0),
                "p50_ms": round(lat[len(lat) // 2]) if lat else None,
                "p95_ms": round(lat[min(len(lat) - 1, int(len(lat) * 0.95))]) if lat else None,
                "p99_ms": round(lat[min(len(lat) - 1, int(len(lat) * 0.99))]) if lat else None,
                "max_ms": round(lat[-1]) if lat else None, "sample_errors": self.errors.get(name, []),
            }
        return out


async def timed(m: Metrics, name: str, coro):
    t0 = time.perf_counter()
    try:
        r = await coro
    except Exception as exc:  # timeouts, connection errors
        m.fail(name, f"{type(exc).__name__}: {exc}")
        return None
    m.add(name, (time.perf_counter() - t0) * 1000, r.status_code)
    return r


async def student(i: int, stage: str, base: str, m: Metrics, until: float, upload: bool) -> None:
    async with httpx.AsyncClient(base_url=base, timeout=60, headers=H) as c:
        email = f"load-{stage}-{i}-{random.randint(1, 10**9)}@student.msot.edu"
        r = await timed(m, "signup", c.post("/api/auth/signup", json={"name": f"Load Student {i}", "email": email,
                                                                       "password": "password123", "batch_year": 2026, "branch": "CSE"}))
        if not r or r.status_code != 200:
            return
        await timed(m, "consent", c.post("/api/me/consent", json={"accept": True}))
        await timed(m, "update_profile", c.patch("/api/me", json={"target_role": random.choice(
            ["Full Stack Developer", "Backend Developer", "Data Analyst", "Frontend Developer"]), "job_type": "internship",
            "target_locations": ["Bengaluru", "Remote"]}))
        uploaded_at = None
        if upload:
            pdf = RESUMES[i % len(RESUMES)]
            r = await timed(m, "upload_resume", c.post("/api/profile/resume", files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")}))
            if r is not None and r.status_code == 200:
                uploaded_at = time.perf_counter()
                m.reviews_pending += 1
        interview_id = None
        app_id = None
        while time.perf_counter() < until:
            await asyncio.sleep(random.uniform(1, 4))
            if uploaded_at:
                r = await timed(m, "profile", c.get("/api/profile"))
                if r is not None and r.status_code == 200:
                    src = (r.json().get("sources", {}).get("resume") or [{}])[0]
                    if src.get("status") in ("ready", "error"):
                        m.review_seconds.append(time.perf_counter() - uploaded_at)
                        m.reviews_pending -= 1
                        uploaded_at = None
                continue
            action = random.choices(["readiness", "report", "jobs", "tracker", "notifications", "chat", "interview"],
                                    weights=[22, 14, 18, 12, 12, 8, 14])[0]
            if action == "readiness":
                await timed(m, "readiness", c.get("/api/readiness"))
            elif action == "report":
                await timed(m, "report", c.get("/api/report"))
            elif action == "jobs":
                await timed(m, "jobs_search", c.get("/api/jobs"))
            elif action == "notifications":
                await timed(m, "notifications", c.get("/api/notifications"))
            elif action == "tracker":
                if app_id is None:
                    r = await timed(m, "tracker_add", c.post("/api/applications", json={"title": "SDE Intern", "company": f"Co {i}",
                                                                                        "status": "saved"}))
                    if r is not None and r.status_code == 200:
                        app_id = r.json()["application"]["id"]
                else:
                    await timed(m, "tracker_update", c.patch(f"/api/applications/{app_id}", json={"status": random.choice(
                        ["applied", "shortlisted", "interview"]), "interview_at": "2030-01-10T10:00:00+00:00"}))
                await timed(m, "tracker_board", c.get("/api/applications"))
            elif action == "chat":
                t0 = time.perf_counter()
                try:
                    async with c.stream("POST", "/api/chat", json={"message": "What should I fix first?"}) as resp:
                        async for _ in resp.aiter_text():
                            pass
                        m.add("chat_stream", (time.perf_counter() - t0) * 1000, resp.status_code)
                except Exception as exc:
                    m.fail("chat_stream", f"{type(exc).__name__}: {exc}")
            elif action == "interview":
                if interview_id is None:
                    r = await timed(m, "interview_start", c.post("/api/interviews", json={"mode": "text", "duration": 15}))
                    if r is not None and r.status_code == 200:
                        interview_id = r.json()["interview_id"]
                else:
                    r = await timed(m, "interview_turn", c.post(f"/api/interviews/{interview_id}/turn",
                                                                json={"text": random.choice(ANSWERS)}))
                    if r is not None and r.status_code == 200 and r.json().get("done"):
                        interview_id = None


async def stage(base: str, users: int, duration: int, upload: bool, ramp: float) -> dict:
    m = Metrics()
    until = time.perf_counter() + duration
    t0 = time.perf_counter()
    tasks = []
    for i in range(users):
        tasks.append(asyncio.create_task(student(i, f"{users}u", base, m, until, upload)))
        await asyncio.sleep(ramp / max(1, users))         # students arrive over `ramp` seconds
    await asyncio.gather(*tasks)
    wall = time.perf_counter() - t0
    summ = m.summary()
    total = sum(v["requests"] for v in summ.values())
    errors = sum(v["errors"] for v in summ.values())
    interactive = [v for k, v in summ.items() if k in ("readiness", "report", "jobs_search", "tracker_board", "tracker_update",
                                                         "notifications", "profile", "interview_turn")]
    p95s = [v["p95_ms"] for v in interactive if v["p95_ms"] is not None]
    rs = sorted(m.review_seconds)
    return {
        "users": users, "duration_s": duration, "wall_s": round(wall, 1), "requests": total, "errors": errors,
        "error_rate": round(errors / max(1, total), 4), "throughput_rps": round(total / wall, 1),
        "worst_interactive_p95_ms": max(p95s) if p95s else None,
        "resume_reviews_completed": len(rs), "resume_reviews_unfinished": m.reviews_pending,
        "review_p50_s": round(rs[len(rs) // 2], 1) if rs else None,
        "review_p95_s": round(rs[min(len(rs) - 1, int(len(rs) * 0.95))], 1) if rs else None,
        "endpoints": summ,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--stages", default="50,100,150")
    ap.add_argument("--duration", type=int, default=120)
    ap.add_argument("--ramp", type=float, default=20.0, help="seconds over which each stage's students arrive")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--pause", type=int, default=20, help="seconds between stages so the queue can drain")
    ap.add_argument("--label", default="")
    args = ap.parse_args()
    results = []
    for n in [int(x) for x in args.stages.split(",")]:
        print(f"--- stage: {n} concurrent students for {args.duration}s", flush=True)
        res = asyncio.run(stage(args.base, n, args.duration, not args.no_upload, args.ramp))
        results.append(res)
        print(json.dumps({k: v for k, v in res.items() if k != "endpoints"}), flush=True)
        for name, e in res["endpoints"].items():
            print(f"   {name:16s} n={e['requests']:5d} err={e['errors']:3d} p50={e['p50_ms']} p95={e['p95_ms']} p99={e['p99_ms']}")
        time.sleep(args.pause)
    out_dir = ROOT / "loadtest" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{time.strftime('%Y%m%d-%H%M%S')}{('-' + args.label) if args.label else ''}.json"
    out.write_text(json.dumps({"base": args.base, "stages": results, "python": sys.version.split()[0]}, indent=2), encoding="utf-8")
    print("results:", out)


if __name__ == "__main__":
    main()
