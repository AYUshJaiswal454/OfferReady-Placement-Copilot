"""Prepare a data directory for the load test: admin account, MSOT jobs, and a realistically large job index.

The bundled demo source has 48 postings; a live deployment that crawls the permitted sources typically holds a few
thousand active jobs, so this script adds synthetic variants (clearly marked source "loadtest") to reach --jobs.

    DATA_DIR=/path/to/loaddata python loadtest/prepare.py --jobs 3000
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=3000)
    args = ap.parse_args()
    from app.db import get_db, iso_in, now_iso
    from app.jobs.pipeline import upsert_jobs
    from app.main import create_app, seed
    from app.tasks import drain, enqueue

    import app.pipelines  # noqa: F401

    create_app(start_worker=False)
    seed()
    enqueue("crawl_jobs", {"source": "demo"})
    asyncio.run(drain())
    base = json.loads((ROOT / "app" / "data" / "demo_jobs.json").read_text(encoding="utf-8"))
    cities = ["Bengaluru, India", "Hyderabad, India", "Pune, India", "Chennai, India", "Gurugram, India", "Noida, India",
              "Mumbai, India", "Remote (India)", "Kolkata, India", "Ahmedabad, India"]
    companies = [f"{a} {b}" for a in ("Nova", "Blue", "Quantum", "Bright", "Indus", "Saffron", "Delta", "Peak", "Orbit", "Kite")
                 for b in ("Labs", "Systems", "Tech", "Works", "Digital", "AI", "Cloud", "Soft")]
    rng = random.Random(42)
    batch = []
    for i in range(max(0, args.jobs - len(base))):
        j = dict(rng.choice(base))
        batch.append({**j, "source": "loadtest", "source_job_id": f"lt-{i}", "company": rng.choice(companies),
                      "location": rng.choice(cities), "remote": "Remote" in j.get("location", ""),
                      "url": f"https://jobs.example.com/lt/{i}", "posted_at": iso_in(days=-rng.randint(0, 28)),
                      "title": j["title"] + rng.choice(["", "", " - 2026", " (6 months)", " - Bengaluru"])})
        if len(batch) == 500:
            upsert_jobs(batch)
            batch = []
    if batch:
        upsert_jobs(batch)
    db = get_db()
    admin = db.fetchone("SELECT id FROM users WHERE role = 'admin'")
    for title, skills, min_score in [("Software Engineering Intern", ["Java", "SQL"], 30), ("Full Stack Intern", ["React", "Node.js"], 50)]:
        db.insert("msot_jobs", {"posted_by": admin["id"], "title": title, "company": "Fintrix Labs", "location": "Bengaluru",
                                "employment_type": "internship", "description": f"{title}. Requirements: {', '.join(skills)}.",
                                "skills": skills, "eligibility": {"min_score": min_score, "batches": [], "branches": [], "skills": skills},
                                "deadline": "2030-12-31", "status": "open", "created_at": now_iso(), "updated_at": now_iso()})
    print("active jobs:", db.scalar("SELECT COUNT(*) FROM jobs_index WHERE active = 1"))


if __name__ == "__main__":
    main()
