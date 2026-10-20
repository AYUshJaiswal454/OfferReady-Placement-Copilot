"""Measured evaluations used by both the test suite (pass/fail thresholds) and the test report (the numbers).

Each function sets up what it needs, runs the real code paths and returns a plain dict of results.
Run everything and print a summary:   python -m tests.evaluate
"""
from __future__ import annotations

import asyncio
import json
import random
import statistics
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

from tests.support import RESUMES, drain, ensure_resume_corpus, fresh_environment

ROLE_TARGET = "Full Stack Developer"


# ----------------------------------------------------------------------------- 1. resume review vs ground truth
def resume_accuracy() -> dict:
    """Each corpus resume was generated with known, human-specified defects. A check counts as flagged when its
    status is fail or warn. Ground truth = the checks each planted defect must trigger (tests/resume_factory.py)."""
    from app.intake.resume_parser import parse_resume_pdf
    from app.review.resume_checks import review_resume

    labels = ensure_resume_corpus()
    rows, per_check = [], defaultdict(lambda: Counter())
    tp = fp = fn = tn = 0
    all_checks: set[str] = set()
    t_total = 0.0
    for lab in labels:
        t0 = time.perf_counter()
        parsed = parse_resume_pdf((RESUMES / lab["file"]).read_bytes(), ocr=True)
        result = review_resume(parsed, lab["file"], ROLE_TARGET)
        t_total += time.perf_counter() - t0
        ids = {c["id"] for c in result["checks"]}
        all_checks |= ids
        flagged = {c["id"] for c in result["checks"] if c["status"] in ("fail", "warn")}
        expected = set(lab["expected_failures"])
        for cid in ids:
            if cid in flagged and cid in expected:
                tp += 1
                per_check[cid]["tp"] += 1
            elif cid in flagged:
                fp += 1
                per_check[cid]["fp"] += 1
            elif cid in expected:
                fn += 1
                per_check[cid]["fn"] += 1
            else:
                tn += 1
                per_check[cid]["tn"] += 1
        rows.append({"file": lab["file"], "defects": lab["defects"], "expected": sorted(expected), "flagged": sorted(flagged),
                     "missed": sorted(expected - flagged), "extra": sorted(flagged - expected), "score": round(result["score"], 1)})
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    return {"resumes": len(labels), "checks_per_resume": len(all_checks), "decisions": tp + fp + fn + tn,
            "tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": round(precision, 3), "recall": round(recall, 3),
            "agreement": round((tp + tn) / max(1, tp + fp + fn + tn), 4), "rows": rows,
            "per_check": {k: dict(v) for k, v in sorted(per_check.items())},
            "avg_seconds": round(t_total / max(1, len(labels)), 2)}


# ----------------------------------------------------------------------------- 2. consistency over repeated runs
def resume_consistency(runs: int = 5, files: list[str] | None = None) -> dict:
    """Parse + review each resume `runs` times from scratch; scores must stay within ±3 (they are deterministic)."""
    from app.intake.resume_parser import parse_resume_pdf
    from app.review.resume_checks import review_resume

    labels = ensure_resume_corpus()
    files = files or [l["file"] for l in labels]
    rows = []
    for f in files:
        data = (RESUMES / f).read_bytes()
        scores, statuses = [], set()
        for _ in range(runs):
            r = review_resume(parse_resume_pdf(data, ocr=True), f, ROLE_TARGET)
            scores.append(r["score"])
            statuses.add(json.dumps([(c["id"], c["status"]) for c in r["checks"]]))
        rows.append({"file": f, "scores": scores, "spread": round(max(scores) - min(scores), 2), "same_verdicts": len(statuses) == 1})
    return {"runs": runs, "resumes": len(rows), "max_spread": max(r["spread"] for r in rows),
            "all_verdicts_identical": all(r["same_verdicts"] for r in rows), "rows": rows}


def interview_scoring_consistency(runs: int = 5) -> dict:
    """Score the same finished interview transcript `runs` times (rule scorer; the LLM scorer takes a median of 3)."""
    from app.interview.scorer import score_interview

    from app.db import get_db

    from app.interview import service as iv

    fresh_environment()
    user, _ = _interview_user("Consistency Check")
    iid = iv.start(user, "text", 15, "mock", "deterministic")["interview_id"]
    asyncio.run(_simulate(iid, user, "average", 3))
    db = get_db()
    row = db.fetchone("SELECT plan FROM interviews WHERE id = ?", (iid,))
    turns = db.fetchall("SELECT seq, speaker, text, t_ms, meta FROM interview_turns WHERE interview_id = ? ORDER BY seq", (iid,))
    scores = [asyncio.run(score_interview(row["plan"], turns, user))["score"] for _ in range(runs)]
    return {"runs": runs, "scores": scores, "spread": round(max(scores) - min(scores), 2)}


# ----------------------------------------------------------------------------- 3. repositories and live links
REPO_EXPECT_DESC = {
    "readme": "README present", "setup": "setup steps in README", "screenshots": "screenshots in README",
    "secrets": "high-severity secrets", "secrets_min": "at least N secrets found", "rule": "secret type detected",
    "info_rule": "low-risk key reported as info", "history": "secret found in git history", "junk_min": "junk files flagged",
    "gitignore": ".gitignore present", "web_upload": "browser uploads detected", "good_commits": "meaningful commits",
    "organized": "organised folder structure", "tests": "tests found", "long_function": "long function flagged",
    "default_template": "default template README", "localhost": "hard-coded localhost flagged", "junk": "junk files",
}


def _repo_assert(key: str, value, a: dict) -> tuple[bool, str]:
    sec = a["secrets"]["findings"]
    checks = {
        "readme": lambda: a["readme"]["present"] == value,
        "setup": lambda: bool(a["readme"]["has_setup"]) == value,
        "screenshots": lambda: (len(a["readme"]["screenshots"]) > 0) == value,
        "secrets": lambda: a["secrets"]["high"] == value,
        "secrets_min": lambda: a["secrets"]["high"] >= value,
        "rule": lambda: any(f["rule"] == value and f["severity"] == "high" for f in sec),
        "info_rule": lambda: any(f["rule"] == value and f["severity"] == "info" for f in sec),
        "history": lambda: any(f.get("commit") for f in sec) == value,
        "junk_min": lambda: len(a["structure"]["junk"]) >= value,
        "junk": lambda: len(a["structure"]["junk"]) == value,
        "gitignore": lambda: bool(a["structure"]["gitignore"]) == value,
        "web_upload": lambda: (a["commits"]["web_uploads"] > 0) == value,
        "good_commits": lambda: (a["commits"]["ratio"] >= 0.6) == value,
        "organized": lambda: bool(a["structure"]["organized"]) == value,
        "tests": lambda: (a["tests"]["test_files"] > 0) == value,
        "long_function": lambda: bool(a["code"]["long_functions"]) == value,
        "default_template": lambda: bool(a["readme"]["default_template"]) == value,
        "localhost": lambda: bool(a["code"]["hardcoded_localhost"]) == value,
    }
    ok = checks[key]()
    return ok, f"{REPO_EXPECT_DESC.get(key, key)} = {value}"


def repo_checks() -> dict:
    from app.review.repo_analyzer import analyze_repo
    from tests.repo_factory import FAKE_AWS, FAKE_OPENAI, FIREBASE_WEB_KEY, build_all

    root = Path(tempfile.mkdtemp(prefix="repos-"))
    repos = build_all(root)
    rows, passed, total = [], 0, 0
    for name, info in repos.items():
        t0 = time.perf_counter()
        a = analyze_repo(info["path"], "asha")
        secs = time.perf_counter() - t0
        results = []
        for key, value in info["expect"].items():
            ok, desc = _repo_assert(key, value, a)
            results.append({"expectation": desc, "ok": ok})
            passed += ok
            total += 1
        planted = [FAKE_AWS, FAKE_OPENAI, "S3cr3tPassw0rd", FIREBASE_WEB_KEY]
        leaked = [f for f in a["secrets"]["findings"] if any(p in json.dumps(f) for p in planted)]
        rows.append({"repo": name, "expectations": results, "all_ok": all(r["ok"] for r in results), "seconds": round(secs, 2),
                     "secrets": [(f["rule"], f["severity"], f["redacted"]) for f in a["secrets"]["findings"]],
                     "unredacted_values": len(leaked)})
    return {"repos": len(rows), "expectations": total, "passed": passed, "rows": rows}


LINK_CASES = [
    # path, what is wrong, expected check outcomes (PR2 = opens without errors, PR3 = mobile, PR4 = matches claims)
    ("/good", "nothing", {"PR2": "pass", "PR3": "pass", "PR4": "pass"}),
    ("/jserror", "uncaught JS error + missing image", {"PR2": "not-pass"}),
    ("/notmobile", "no viewport meta, fixed 1200px layout", {"PR3": "not-pass"}),
    ("/cra", "default Create React App placeholder", {"PR4": "not-pass"}),
    ("/netlify404", "Netlify 'Page not found'", {"PR2": "fail"}),
    ("/error500", "HTTP 500", {"PR2": "fail"}),
    ("/unrelated", "page about something else", {"PR4": "not-pass"}),
    ("http://does-not-exist.invalid/", "domain does not resolve", {"PR2": "fail"}),
    ("http://127.0.0.1:9/", "nothing listening on the port", {"PR2": "fail"}),
]


def live_link_checks() -> dict:
    from app.review.livelink import check_live_link, close_browser
    from app.review.project_review import review_project
    from tests import site_server

    server, base = site_server.start()
    project = {"name": "DevConnect", "description": "Real-time Q&A platform for student developers",
               "tech": ["React", "Node.js", "MongoDB", "Socket.io"]}

    async def run():
        out = []
        for path, problem, expect in LINK_CASES:
            url = path if path.startswith("http") else base + path
            t0 = time.perf_counter()
            live = await check_live_link(url, project)
            secs = time.perf_counter() - t0
            review = review_project({**project, "live_url": url}, None, live)
            status = {c["id"]: c["status"] for c in review["checks"]}
            res = []
            for cid, want in expect.items():
                got = status.get(cid)
                ok = got == want if want != "not-pass" else got in ("fail", "warn")
                res.append({"check": cid, "want": want, "got": got, "ok": ok})
            out.append({"case": path, "problem": problem, "results": res, "all_ok": all(r["ok"] for r in res),
                        "engine": live.get("engine"), "error": live.get("error"), "seconds": round(secs, 2)})
        await close_browser()
        return out

    rows = asyncio.run(run())
    server.shutdown()
    return {"cases": len(rows), "passed": sum(r["all_ok"] for r in rows), "rows": rows}


# ----------------------------------------------------------------------------- 4. interviews (rules / API / Ollama)
def _interview_user(name: str, role: str = ROLE_TARGET) -> tuple[dict, int | None]:
    from app.db import get_db, now_iso
    from app.intake.resume_parser import parse_resume_pdf
    from app.security import hash_password

    db = get_db()
    ensure_resume_corpus()
    uid = db.insert("users", {"email": f"{name.lower().replace(' ', '.')}.{random.randint(1, 10**6)}@test.msot.edu",
                              "password_hash": hash_password("x" * 10), "name": name, "role": "student", "created_at": now_iso(),
                              "consent_at": now_iso(), "consent_version": "2026-10-v1", "settings": {}, "target_role": role,
                              "job_type": "internship", "target_locations": ["Bengaluru"]})
    extracted = parse_resume_pdf((RESUMES / "resume_05.pdf").read_bytes(), ocr=False).to_summary()
    db.insert("profile_sources", {"user_id": uid, "kind": "resume", "label": "resume.pdf", "input": {}, "status": "ready",
                                  "extracted": extracted, "created_at": now_iso(), "updated_at": now_iso()})
    for pname, tech in [("DevConnect", ["React", "Node.js", "MongoDB", "Socket.io"]), ("ShopLite", ["Next.js", "TypeScript", "Stripe"]),
                        ("CropDoc", ["Python", "PyTorch", "OpenCV"])]:
        db.insert("profile_sources", {"user_id": uid, "kind": "project", "label": pname, "status": "ready",
                                      "input": {"name": pname, "tech": tech}, "created_at": now_iso(), "updated_at": now_iso()})
    user = db.fetchone("SELECT * FROM users WHERE id = ?", (uid,))
    return user, None


async def _simulate(iid, user, persona, seed):
    from tests.interview_personas import simulate

    return await simulate(iid, user, persona, seed=seed)


def interview_personas(mode: str = "rules", personas: tuple[str, ...] = ("strong", "average", "weak", "rambler", "injector"),
                       duration: int = 15) -> dict:
    """Run complete interviews with simulated candidates. mode: rules (offline), openai (OpenAI API format against a
    local stub server), ollama (Ollama's OpenAI-compatible API against the same stub)."""
    from app.db import get_db
    from app.interview import service as iv
    from tests import llm_stub

    server = None
    if mode == "rules":
        fresh_environment()
    else:
        server, url = llm_stub.start()
        if mode == "openai":
            fresh_environment(llm_provider="openai", openai_api_key="sk-test-stub", openai_base_url=url,
                              openai_model="gpt-6-luna", openai_model_smart="gpt-6-luna")
        else:
            fresh_environment(llm_provider="ollama", ollama_base_url=url, ollama_model="qwen2.5:7b-instruct",
                              ollama_model_smart="qwen2.5:7b-instruct")
    calls_before = llm_stub.STATS["calls"]
    db = get_db()
    rows = []
    for i, persona in enumerate(personas):
        random.seed(100 + i)
        user, _ = _interview_user(f"{persona.title()} Candidate")
        from app.llm.providers import resolve

        cfg = resolve(user)
        st = iv.start(user, "text", duration, cfg.name, cfg.model or "deterministic")
        t0 = time.perf_counter()
        asyncio.run(_simulate(st["interview_id"], user, persona, 7 + i))
        drain()
        wall = time.perf_counter() - t0
        row = db.fetchone("SELECT * FROM interviews WHERE id = ?", (st["interview_id"],))
        turns = db.fetchall("SELECT speaker, t_ms, meta, text FROM interview_turns WHERE interview_id = ? ORDER BY seq", (row["id"],))
        res = row["result"] or {}
        actions = Counter((t["meta"] or {}).get("action") for t in turns if t["speaker"] == "candidate")
        rows.append({
            "persona": persona, "provider": cfg.name, "score": row["score"], "status": row["status"],
            "questions": sum(1 for t in turns if t["speaker"] == "interviewer") - 1,
            "minutes_used": round(max(t["t_ms"] for t in turns) / 60000, 1),
            "dimensions": {d["key"]: d["score"] for d in res.get("dimensions", [])},
            "flags": res.get("flags", []), "redirects": actions.get("redirect", 0), "follow_ups": actions.get("follow_up", 0),
            "hints": actions.get("hint", 0), "scorer": (res.get("scorer") or {}).get("provider"),
            "scorer_runs": (res.get("scorer") or {}).get("runs"), "wall_seconds": round(wall, 1),
            "has_transcript": len(turns) > 4, "weak_areas": res.get("weak_areas", [])[:2],
        })
    calls = llm_stub.STATS["calls"] - calls_before
    if server:
        server.shutdown()
    by = {r["persona"]: r for r in rows}
    return {"mode": mode, "interviews": len(rows), "llm_calls": calls, "rows": rows,
            "ordering_ok": all(k in by for k in ("strong", "average", "weak")) and by["strong"]["score"] > by["average"]["score"] > by["weak"]["score"]}


# ----------------------------------------------------------------------------- 5. job matching relevance
TITLE_FAMILY = {
    "Software Engineering Intern": "sde", "Software Development Engineer I": "sde", "Associate Software Engineer (Freshers)": "sde",
    "Frontend Developer Intern": "frontend", "Frontend Engineer": "frontend", "Backend Developer Intern": "backend",
    "Backend Engineer": "backend", "Senior Backend Engineer": "senior", "Full Stack Developer Intern (MERN)": "fullstack",
    "Data Science Intern": "data_science", "Machine Learning Intern": "data_science", "GenAI Engineering Intern": "genai",
    "Data Analyst Intern": "data_analyst", "Data Engineer": "data_engineer", "Android Developer Intern": "mobile",
    "Flutter Developer Intern": "mobile", "DevOps Intern": "devops", "QA Automation Intern": "qa",
}
RELEVANT = {  # which job families a human placement officer would call relevant for each target role
    "Full Stack Developer": {"fullstack", "frontend", "backend", "sde"},
    "Backend Developer": {"backend", "sde", "fullstack"},
    "Frontend Developer": {"frontend", "fullstack", "sde"},
    "Data Scientist": {"data_science", "genai", "data_analyst"},
    "Data Analyst": {"data_analyst", "data_science", "data_engineer"},
    "Android Developer": {"mobile"},
}
GOOD_MATCH = 50   # the Jobs page lists results below this under "Weaker matches"
PROFILES = [
    ("Full Stack Developer", ["React", "Node.js", "Express.js", "MongoDB", "JavaScript", "Git"]),
    ("Backend Developer", ["Java", "Spring Boot", "SQL", "REST APIs", "Docker"]),
    ("Frontend Developer", ["React", "TypeScript", "CSS", "HTML", "Tailwind CSS"]),
    ("Data Scientist", ["Python", "Pandas", "scikit-learn", "PyTorch", "SQL"]),
    ("Data Analyst", ["SQL", "Excel", "Power BI", "Python", "Pandas"]),
    ("Android Developer", ["Kotlin", "Java", "Android", "Firebase"]),
]


def job_matching(k: int = 10) -> dict:
    from app.db import get_db, now_iso
    from app.jobs.pipeline import search
    from app.security import hash_password
    from app.tasks import enqueue

    fresh_environment()
    enqueue("crawl_jobs", {"source": "demo"})
    drain()
    db = get_db()
    rows = []
    for role, skills in PROFILES:
        uid = db.insert("users", {"email": f"{role.replace(' ', '').lower()}@test.msot.edu", "password_hash": hash_password("x" * 10),
                                  "name": role, "role": "student", "created_at": now_iso(), "consent_at": now_iso(),
                                  "settings": {}, "target_role": role, "job_type": "internship", "target_locations": ["Bengaluru", "Remote"]})
        db.insert("profile_sources", {"user_id": uid, "kind": "resume", "label": "r.pdf", "input": {}, "status": "ready",
                                      "extracted": {"skills": skills, "projects": [], "experience": []}, "created_at": now_iso(),
                                      "updated_at": now_iso()})
        user = db.fetchone("SELECT * FROM users WHERE id = ?", (uid,))
        res = search(user, None, {"type": "all", "remote": False, "min_match": None}, 1, 50)
        ranked = sorted(res["results"], key=lambda r: -r["match"])

        def is_relevant(job: dict) -> bool:
            return TITLE_FAMILY.get(job["title"], "other") in RELEVANT[role] and job.get("employment_type") == "internship"

        judged = [{"title": r["job"]["title"], "company": r["job"]["company"], "match": r["match"], "relevant": is_relevant(r["job"]),
                   "has_reasons": bool(r.get("reasons"))} for r in ranked]
        good = [j for j in judged if j["match"] >= GOOD_MATCH]
        # Relevant openings that exist in the index for this student's locations (Bengaluru or remote).
        pool = [j for j in db.fetchall("SELECT * FROM jobs_index WHERE active = 1")
                if is_relevant(j) and (j.get("remote") or "bengaluru" in (j.get("location") or "").lower()
                                       or "bangalore" in (j.get("location") or "").lower())]
        found = {(j["title"], j["company"]) for j in good if j["relevant"]}
        rows.append({"role": role, "query": res.get("query"), "results": len(judged), "good_matches": len(good),
                     "judged": judged[:k],
                     "precision_at_5": round(sum(j["relevant"] for j in judged[:5]) / max(1, min(5, len(judged))), 2),
                     "good_match_precision": round(sum(j["relevant"] for j in good) / max(1, len(good)), 2),
                     "recall": round(len(found) / max(1, len(pool)), 2), "relevant_in_index": len(pool),
                     "all_have_reasons": all(j["has_reasons"] for j in judged), "deep_links": len(res.get("deep_links", []))})
    return {"k": k, "profiles": len(rows), "good_match_threshold": GOOD_MATCH,
            "mean_precision_at_5": round(statistics.mean(r["precision_at_5"] for r in rows), 3),
            "mean_good_match_precision": round(statistics.mean(r["good_match_precision"] for r in rows), 3),
            "mean_recall": round(statistics.mean(r["recall"] for r in rows), 3),
            "pct_relevant_all_results": round(sum(sum(j["relevant"] for j in r["judged"]) for r in rows)
                                              / max(1, sum(len(r["judged"]) for r in rows)), 3), "rows": rows}


def dedupe_check() -> dict:
    from app.db import get_db
    from app.jobs.pipeline import upsert_jobs

    fresh_environment()
    base = {"title": "Backend Developer Intern", "company": "Acme Labs", "location": "Bengaluru, India",
            "description": "Java Spring Boot SQL", "url": "https://boards.example.com/acme/1", "employment_type": "internship"}
    upsert_jobs([{**base, "source": "greenhouse", "source_job_id": "1"},
                 {**base, "source": "lever", "source_job_id": "abc", "url": "https://jobs.example.com/acme/abc",
                  "title": "Backend Developer Intern ", "location": "Bangalore"},
                 {**base, "source": "remotive", "source_job_id": "x9", "title": "Frontend Developer Intern"}])
    db = get_db()
    rows = db.fetchall("SELECT title, source, also_on FROM jobs_index ORDER BY id")
    return {"inserted": 3, "stored": len(rows), "rows": rows}


if __name__ == "__main__":
    import sys

    which = sys.argv[1:] or ["resume_accuracy", "resume_consistency", "repo_checks", "live_link_checks", "job_matching"]
    for name in which:
        t0 = time.perf_counter()
        out = globals()[name]()
        slim = {k: v for k, v in out.items() if k != "rows"}
        print(f"{name} ({time.perf_counter() - t0:.1f}s):", json.dumps(slim, default=str)[:600])
