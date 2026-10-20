"""Seed realistic demo data (works fully offline).

* Demo student (demo@student.msot.edu / demo12345): resume, LinkedIn, coding stats, achievements,
  two reviewed projects (local fixture repos + local live pages), a scored mock interview,
  tracked applications, and an MSOT job application.
* A cohort of 20 students built from the labelled resume corpus, so the placement-cell
  dashboard has a realistic distribution and common gaps.

Usage:  python scripts/seed_demo.py            (uses DATA_DIR / DATABASE_URL like the app)
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import shutil
import sys
import zlib
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LLM_PROVIDER", os.environ.get("LLM_PROVIDER", "mock"))

from app.config import get_settings  # noqa: E402
from app.db import get_db, now_iso, parse_iso, utcnow  # noqa: E402
from app.main import create_app, seed  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.tasks import drain, enqueue  # noqa: E402
from tests import site_server  # noqa: E402
from tests.github_fixture import demo_github_profile  # noqa: E402
from tests.interview_personas import simulate  # noqa: E402
from tests.linkedin_factory import linkedin_pdf  # noqa: E402
from tests.resume_factory import make_spec, render  # noqa: E402
from tests.repo_factory import build_all  # noqa: E402

RESUMES = ROOT / "tests" / "fixtures" / "resumes"
# Tables (and their timestamp columns) whose new rows are moved back to the day a demo stage represents.
STAGED = {"readiness_snapshots": ["created_at"], "reviews": ["created_at"], "profile_sources": ["created_at", "updated_at"],
          "interviews": ["started_at", "ended_at"], "notifications": ["created_at"], "files": ["created_at"]}


def make_user(email: str, name: str, **extra) -> dict:
    db = get_db()
    row = db.fetchone("SELECT * FROM users WHERE email = ?", (email,))
    if row:
        return row
    uid = db.insert("users", {"email": email, "password_hash": hash_password(extra.pop("password", "student123")), "name": name,
                              "role": "student", "created_at": now_iso(), "consent_at": now_iso(), "consent_version": "2026-10-v1",
                              "settings": {}, "target_locations": extra.pop("target_locations", ["Bengaluru", "Remote"]), **extra})
    return db.fetchone("SELECT * FROM users WHERE id = ?", (uid,))


async def run_all() -> None:
    while await drain(500):
        pass


async def main() -> None:
    create_app(start_worker=False)
    seed()
    db = get_db()
    from app import profile_service as ps
    from app.interview import service as iv
    from app.review import repo_analyzer
    from app.tracker import applications as apps

    # Fixture repos stand in for GitHub during the demo (offline); live links point at a local test site.
    repos_dir = get_settings().data_dir / "demo_repos"
    if repos_dir.exists():
        shutil.rmtree(repos_dir)
    repos = build_all(repos_dir)
    server, base = site_server.start()
    real_clone = repo_analyzer.clone_repo

    # Cohort resumes link to made-up GitHub repos and *.vercel.app sites; map each one deterministically onto a
    # fixture repo / local page so every project gets a real (offline) review with a realistic mix of problems.
    cohort_repos = ["good_fullstack", "python_ml", "firebase_and_mongo", "readme_no_setup", "good_fullstack",
                    "default_cra_readme", "node_modules_committed", "web_upload", "python_ml", "no_readme"]
    cohort_pages = ["/good", "/good", "/good", "/jserror", "/notmobile", "/cra", "/netlify404", "/unrelated"]

    def fake_clone(url: str, dest: Path, depth: int = 60, timeout: int = 90):
        name = url.rstrip("/").removesuffix(".git").split("/")[-1]
        if name not in repos:
            name = cohort_repos[zlib.crc32(url.encode()) % len(cohort_repos)]
        shutil.copytree(repos[name]["path"], dest)
        return True, ""

    repo_analyzer.clone_repo = fake_clone

    from app.review import livelink

    real_live = livelink.check_live_link

    async def fake_live(url: str, claims: dict | None = None) -> dict:
        if "127.0.0.1" not in url:
            url = base + cohort_pages[zlib.crc32(url.encode()) % len(cohort_pages)]
        return await real_live(url, claims)

    livelink.check_live_link = fake_live

    from app.review import github_review

    async def fake_profile(username: str) -> dict:
        return demo_github_profile(username)

    github_review.fetch_profile = fake_profile   # offline GitHub API stand-in for the demo account

    # ------------------------------------------------------------------ demo student
    # Kabir's five-week journey is replayed stage by stage, so every readiness snapshot on his progress chart is a
    # real computation; only the timestamps of each stage are moved back to the day it represents.
    demo = db.fetchone("SELECT * FROM users WHERE email = 'demo@student.msot.edu'")
    # The demo resume (corpus resume_05) belongs to "Kabir Mehta"; the account uses the same name so the
    # LinkedIn-vs-resume consistency check compares like with like.
    db.update("users", demo["id"], {"consent_at": now_iso(), "consent_version": "2026-10-v1", "name": "Kabir Mehta"})
    demo = db.fetchone("SELECT * FROM users WHERE id = ?", (demo["id"],))
    uid = demo["id"]

    async def stage(days_ago: float, action) -> None:
        marks = {t: db.scalar(f"SELECT COALESCE(MAX(id), 0) FROM {t}") for t in STAGED}
        began = now_iso()
        res = action()
        if asyncio.iscoroutine(res):
            await res
        await run_all()
        when = utcnow() - timedelta(days=days_ago)
        for t, cols in STAGED.items():
            for n, r in enumerate(db.fetchall(f"SELECT id, {', '.join(cols)} FROM {t} WHERE id > ? ORDER BY id", (marks[t],))):
                first = parse_iso(r[cols[0]])
                if not first:
                    continue
                delta = (when + timedelta(seconds=40 * n)) - first     # shift every column by the same amount
                vals = [(parse_iso(r[c]) + delta).isoformat(timespec="seconds") if r[c] else None for c in cols]
                db.execute(f"UPDATE {t} SET " + ", ".join(f"{c} = ?" for c in cols) + " WHERE id = ?", (*vals, r["id"]))
        # Older rows touched during this stage (e.g. a source re-reviewed) get the stage's date too.
        db.execute("UPDATE profile_sources SET updated_at = ? WHERE user_id = ? AND updated_at >= ?",
                   (when.isoformat(timespec="seconds"), uid, began))

    v1 = render(make_spec(4, {"mixed_dates", "typos", "no_metrics", "no_leetcode_link", "tech_casing"}, random.Random(1004)))

    def week1():
        ps.upload_resume(uid, "Kabir_Mehta_Resume_final.pdf", v1, "application/pdf", 10)
        ps.add_coding(uid, "leetcode", "demo_student", {"solved": 148, "easy": 80, "medium": 60, "hard": 8, "contests": 1, "rating": 1488})
        ps.add_achievement(uid, "Finalist (top 10 of 140 teams) at Smart India Hackathon 2025 internal round")

    def week1b():
        li = linkedin_pdf("Kabir Mehta", "Student at MSOT Institute of Technology", "Bengaluru, Karnataka, India", "kabir-mehta-8f3a91c2",
                          "I am a hardworking student passionate about technology and looking for opportunities to grow.",
                          ["Java", "Python", "Communication"],
                          [{"org": "Fintrix Labs", "title": "Software Engineering Intern", "dates": "May 2025 - July 2025 (3 months)",
                            "location": "Pune, Maharashtra, India", "description": "Built payment reconciliation APIs in Spring Boot."}],
                          [{"school": "MSOT Institute of Technology", "degree": "Bachelor of Technology - BTech, Computer Science · (2022 - 2026)"}],
                          ["AWS Cloud Practitioner"])
        ps.upload_linkedin(uid, "linkedin.pdf", li, None, None, 10)
        ps.add_github(uid, "demo-msot")

    def week2():
        ps.add_project(uid, "DevConnect", "https://github.com/demo-msot/good_fullstack", f"{base}/good",
                       "Real-time Q&A platform for student developers with chat", ["React", "Node.js", "MongoDB", "Socket.io"])
        ps.add_project(uid, "ShopLite", "https://github.com/demo-msot/default_cra_readme", f"{base}/jserror",
                       "Online store with cart and checkout", ["React", "JavaScript"])
        # Added explicitly so the resume pipeline doesn't auto-create it with the resume's (made-up) GitHub URL.
        ps.add_project(uid, "CropDoc", "https://github.com/demo-msot/python_ml", f"{base}/notmobile",
                       "Crop disease detection from leaf images", ["Python", "PyTorch", "OpenCV", "Streamlit"])

    async def interview(persona: str, seed: int):
        st = iv.start(db.fetchone("SELECT * FROM users WHERE id = ?", (uid,)), "text", 15, "mock", "deterministic")
        await simulate(st["interview_id"], db.fetchone("SELECT * FROM users WHERE id = ?", (uid,)), persona, seed=seed)

    def week4():
        ps.upload_resume(uid, "Kabir_Mehta_Resume_final.pdf", (RESUMES / "resume_05.pdf").read_bytes(), "application/pdf", 10)
        ps.add_coding(uid, "leetcode", "demo_student", {"solved": 212, "easy": 98, "medium": 96, "hard": 18, "contests": 4, "rating": 1612})
        ps.add_achievement(uid, "Web lead, MSOT Coding Club: organised 5 workshops for 300+ students")

    await stage(34, week1)
    await stage(31, week1b)
    await stage(25, week2)
    await stage(18, lambda: interview("average", 5))
    await stage(9, week4)
    await stage(2, lambda: interview("good", 11))
    demo = db.fetchone("SELECT * FROM users WHERE id = ?", (uid,))
    enqueue("crawl_jobs", {"source": "demo"})
    await run_all()

    jobs = db.fetchall("SELECT * FROM jobs_index WHERE source = 'demo' ORDER BY id LIMIT 60")
    picks = [j for j in jobs if "Full Stack" in j["title"] or "Backend" in j["title"]][:4]
    statuses = ["applied", "shortlisted", "saved", "interview"]
    for j, st in zip(picks, statuses):
        a = apps.create(demo["id"], {"job_id": j["id"], "title": j["title"], "company": j["company"], "url": j["url"],
                                     "location": j["location"], "source": "demo", "status": "saved"})
        if st != "saved":
            apps.update_status(demo["id"], a["id"], "applied")
            if st in ("shortlisted", "interview"):
                apps.update_status(demo["id"], a["id"], st, interview_at=now_iso() if st == "interview" else None)
    db.execute("UPDATE applications SET next_follow_up_at = ?, applied_at = ? WHERE user_id = ? AND status = 'applied'",
               ("2026-10-10T09:00:00+00:00", "2026-10-03T09:00:00+00:00", demo["id"]))
    admin = db.fetchone("SELECT id FROM users WHERE role = 'admin'")
    if not db.fetchone("SELECT id FROM msot_jobs"):
        for title, company, desc, skills, min_score in [
            ("Software Engineering Intern", "Fintrix Labs", "Build and test payment reconciliation APIs.\n\nRequirements: Java, Spring Boot, "
             "SQL, REST APIs. Strong DSA fundamentals.\n\nSelection: online test, two technical interviews.", ["Java", "SQL"], 40),
            ("Full Stack Developer Intern", "EduSpark", "Ship features across our React frontend and Node.js API.\n\nRequirements: React, "
             "Node.js, MongoDB, Git.", ["React", "Node.js"], 55),
            ("Data Analyst Intern", "Nimbus Analytics", "Build dashboards and SQL reports for clients.\n\nRequirements: SQL, Excel, Power BI.",
             ["SQL", "Excel"], 80),
        ]:
            db.insert("msot_jobs", {"posted_by": admin["id"], "title": title, "company": company, "location": "Bengaluru",
                                    "employment_type": "internship", "stipend": "₹35,000/month", "description": desc, "skills": skills,
                                    "eligibility": {"min_score": min_score, "batches": [2026], "branches": [], "skills": skills},
                                    "deadline": "2026-12-15", "status": "open", "created_at": now_iso(), "updated_at": now_iso()})

    # ------------------------------------------------------------------ cohort
    labels = json.loads((RESUMES / "labels.json").read_text(encoding="utf-8"))
    rng = random.Random(7)
    roles = ["Full Stack Developer", "Backend Developer", "Data Scientist", "SDE", "Frontend Developer", "Data Analyst"]
    from tests.resume_factory import FIRST, LAST
    for i, lab in enumerate(labels):
        name = f"{FIRST[(i + 3) % len(FIRST)]} {LAST[(i * 3 + 1) % len(LAST)]}"
        u = make_user(f"student{i + 1:02d}@msot.edu", name, roll_no=f"MSOT22CS{i + 10:03d}", batch_year=2026,
                      branch=rng.choice(["CSE", "IT", "ECE", "AI&DS"]), target_role=rng.choice(roles), job_type="internship")
        if db.fetchone("SELECT id FROM profile_sources WHERE user_id = ? AND kind = 'resume'", (u["id"],)):
            continue
        ps.upload_resume(u["id"], lab["file"], (RESUMES / lab["file"]).read_bytes(), "application/pdf", 10)
        if rng.random() < 0.8:
            solved = rng.randint(20, 420)
            med = int(solved * rng.uniform(0.25, 0.55))
            ps.add_coding(u["id"], "leetcode", None, {"solved": solved, "easy": solved - med, "medium": med, "hard": rng.randint(0, 30),
                                                     "contests": rng.randint(0, 9), "rating": rng.randint(1300, 1900)})
    await run_all()
    # A few cohort interviews (mixed personas) so the component average and distribution exist.
    personas = ["average", "weak", "strong", "average", "rambler", "average", "weak", "injector"]
    for u, persona in zip(db.fetchall("SELECT * FROM users WHERE email LIKE 'student%@msot.edu' ORDER BY id LIMIT 8"), personas):
        st = iv.start(u, "text", 15, "mock", "deterministic")
        await simulate(st["interview_id"], u, persona, seed=u["id"])
    await run_all()

    # MSOT applications: the demo student shares the report; eligible cohort students apply too.
    from app.jobs.pipeline import student_profile
    from app.jobs.ranker import msot_eligibility

    def msot_apply(user: dict, job: dict, share: bool) -> None:
        if db.fetchone("SELECT id FROM applications WHERE user_id = ? AND msot_job_id = ?", (user["id"], job["id"])):
            return
        ok, _ = msot_eligibility(job, student_profile(user))
        if not ok:
            return
        a = apps.create(user["id"], {"msot_job_id": job["id"], "title": job["title"], "company": job["company"], "url": None,
                                     "location": job.get("location"), "source": "msot", "status": "applied", "shared_report": share})
        db.update("applications", a["id"], {"shared_report": int(share)})

    msot = {j["title"]: j for j in db.fetchall("SELECT * FROM msot_jobs")}
    demo = db.fetchone("SELECT * FROM users WHERE id = ?", (demo["id"],))
    msot_apply(demo, msot["Full Stack Developer Intern"], True)
    for i, u in enumerate(db.fetchall("SELECT * FROM users WHERE email LIKE 'student%@msot.edu' ORDER BY id")):
        if i % 3 == 0:
            msot_apply(u, msot["Software Engineering Intern"], i % 2 == 0)
        if i % 4 == 1:
            msot_apply(u, msot["Full Stack Developer Intern"], True)
    server.shutdown()
    print("Seeded demo data. Students:", db.scalar("SELECT COUNT(*) FROM users WHERE role = 'student'"),
          "| reviews:", db.scalar("SELECT COUNT(*) FROM reviews"), "| jobs:", db.scalar("SELECT COUNT(*) FROM jobs_index"))


if __name__ == "__main__":
    asyncio.run(main())
