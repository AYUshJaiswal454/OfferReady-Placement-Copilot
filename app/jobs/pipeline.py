"""Job index: crawl permitted sources on a schedule, dedupe, and search/rank for students."""
from __future__ import annotations

import json
import logging
import re

from ..config import get_settings
from ..db import get_db, iso_in, now_iso, parse_iso, utcnow
from ..skills import role_from_text
from ..tasks import handler, schedule
from .boolean import QueryError, _term_matches, build_query, parse
from .connectors import REGISTRY, deep_links
from .normalize import normalize
from .ranker import job_skill_weights, msot_eligibility, score_job

log = logging.getLogger("offerready.jobs")


def source_config() -> dict:
    path = get_settings().job_sources_file
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def cohort_queries(limit: int = 12) -> list[str]:
    """Search keywords for keyed APIs: built from the cohort's target roles (aggregate, no personal data)."""
    rows = get_db().fetchall("SELECT target_role, COUNT(*) n FROM users WHERE role = 'student' AND target_role IS NOT NULL "
                             "GROUP BY target_role ORDER BY n DESC LIMIT ?", (limit,))
    queries = []
    for r in rows:
        role = re.sub(r"\b(intern(ship)?)\b", "", r["target_role"], flags=re.I).strip()
        if role:
            queries += [f"{role} intern", f"{role} fresher"]
    defaults = ["software engineer intern", "software developer fresher", "data analyst intern", "frontend developer intern",
                "backend developer intern", "machine learning intern"]
    return list(dict.fromkeys(queries + defaults))[:limit]


def upsert_jobs(jobs: list[dict]) -> dict:
    db = get_db()
    added = updated = merged = 0
    now = now_iso()
    for raw in jobs:
        job = normalize(raw)
        if not job:
            continue
        existing = db.fetchone("SELECT id FROM jobs_index WHERE source = ? AND source_job_id = ?", (job["source"], job["source_job_id"]))
        job["skill_weights"] = job_skill_weights(job)        # computed once here instead of on every search
        if existing:
            db.update("jobs_index", existing["id"], {"title": job["title"], "description": job["description"],
                                                     "skills": job["skills"], "skill_weights": job["skill_weights"],
                                                     "fetched_at": now, "active": 1, "expires_at": iso_in(days=30)})
            updated += 1
            continue
        dup = db.fetchone("SELECT id, also_on, source FROM jobs_index WHERE dedupe_key = ? AND active = 1 AND source != ?",
                          (job["dedupe_key"], job["source"]))
        if dup:
            also = list(dup["also_on"] or [])
            if not any(a.get("source") == job["source"] for a in also):
                also.append({"source": job["source"], "url": job["url"]})
                db.update("jobs_index", dup["id"], {"also_on": also, "fetched_at": now})
            merged += 1
            continue
        db.insert("jobs_index", {**job, "also_on": [], "fetched_at": now, "expires_at": iso_in(days=30), "active": 1})
        added += 1
    return {"added": added, "updated": updated, "merged_duplicates": merged}


KEYED = {"adzuna": ("adzuna_app_id", "adzuna_app_key"), "jooble": ("jooble_api_key",)}


def key_configured(name: str) -> bool:
    s = get_settings()
    return all(getattr(s, k, "") for k in KEYED.get(name, ()))


def friendly_source_error(exc: Exception) -> str:
    kind, text = type(exc).__name__, str(exc)
    if kind in ("ProxyError", "ConnectError", "ConnectTimeout") or "403 Forbidden" in text and "Proxy" in kind:
        return "Could not reach this source's API from the server (network or proxy blocked the request)."
    if kind in ("ReadTimeout", "TimeoutException", "TimeoutError"):
        return "The source's API did not answer in time; it will be retried on the next refresh."
    if kind == "HTTPStatusError":
        m = re.search(r"\b(\d{3})\b", text)
        return f"The source's API answered HTTP {m.group(1) if m else 'error'}; it will be retried on the next refresh."
    return f"{kind}: {text[:180]}"


@handler("crawl_jobs")
async def crawl_jobs(task: dict) -> dict:
    cfg = source_config()
    only = (task.get("payload") or {}).get("source")
    queries = cohort_queries()
    db = get_db()
    summary = {}
    for name, meta in REGISTRY.items():
        scfg = cfg.get(name) or {}
        if only and name != only:
            continue
        if not scfg.get("enabled", False):
            continue
        if get_settings().offline_mode and name != "demo":
            continue
        db.insert_ignore("source_health", {"source": name})
        if not key_configured(name):
            db.execute("UPDATE source_health SET last_error = ? WHERE source = ?",
                       ("Skipped: add " + " and ".join(k.upper() for k in KEYED[name]) + " to .env to enable.", name))
            continue
        try:
            jobs = await meta["fetch"](scfg, queries)
            result = upsert_jobs(jobs)
            db.execute("UPDATE source_health SET last_run_at = ?, last_ok_at = ?, jobs_found = ?, last_error = NULL WHERE source = ?",
                       (now_iso(), now_iso(), len(jobs), name))
            summary[name] = {"fetched": len(jobs), **result}
        except Exception as exc:  # one broken source must not stop the others
            log.warning("source %s failed: %s", name, exc)
            db.execute("UPDATE source_health SET last_run_at = ?, last_error = ? WHERE source = ?",
                       (now_iso(), friendly_source_error(exc), name))
            summary[name] = {"error": str(exc)[:200]}
    db.execute("UPDATE jobs_index SET active = 0 WHERE active = 1 AND expires_at < ? AND msot_job_id IS NULL", (now_iso(),))
    return summary


schedule("crawl_jobs", get_settings().job_refresh_hours * 3600, "crawl_jobs")


# ----------------------------------------------------------------------------- student search
def student_profile(user: dict) -> dict:
    db = get_db()
    skills: list[str] = []
    resume = db.fetchone("SELECT extracted FROM profile_sources WHERE user_id = ? AND kind = 'resume' AND status = 'ready' "
                         "ORDER BY id DESC LIMIT 1", (user["id"],))
    if resume:
        skills += (resume["extracted"] or {}).get("skills", [])
    for row in db.fetchall("SELECT input, extracted, kind FROM profile_sources WHERE user_id = ? AND kind IN ('project', 'linkedin')",
                           (user["id"],)):
        for s in (row["input"] or {}).get("tech") or (row["extracted"] or {}).get("skills") or []:
            if s not in skills:
                skills.append(s)
    for s in (user.get("settings") or {}).get("extra_skills", []):
        if s not in skills:
            skills.append(s)
    snap = db.fetchone("SELECT score FROM readiness_snapshots WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user["id"],))
    return {"skills": skills, "target_role": user.get("target_role"), "role_id": role_from_text(user.get("target_role")),
            "job_type": user.get("job_type") or "internship", "locations": user.get("target_locations") or [],
            "readiness": snap["score"] if snap else 0, "batch_year": user.get("batch_year"), "branch": user.get("branch")}


_JOBS_CACHE: dict = {"stamp": None, "rows": []}


WORD_RE = re.compile(r"[a-z0-9+#.]+")
SIMPLE_TERM = re.compile(r"^[a-z0-9+#.]+$")


def _active_jobs() -> list[tuple[dict, str, frozenset]]:
    """Active jobs with their lower-cased search text, cached in memory until the index changes
    (a cheap COUNT/MAX query detects crawls, imports and expiry)."""
    db = get_db()
    stamp = (get_settings().database_url,) + tuple(db.fetchone(
        "SELECT COUNT(*) AS n, MAX(fetched_at) AS f, MAX(id) AS i FROM jobs_index WHERE active = 1 AND msot_job_id IS NULL").values())
    if stamp != _JOBS_CACHE["stamp"]:
        rows = db.fetchall("SELECT * FROM jobs_index WHERE active = 1 AND msot_job_id IS NULL ORDER BY posted_at DESC LIMIT 5000")
        out = []
        for job in rows:
            doc = " ".join([job["title"], job["company"], job.get("location") or "", job.get("employment_type") or "",
                            "remote" if job["remote"] else "", " ".join(job.get("skills") or []), job.get("description") or ""]).lower()
            out.append((job, doc, frozenset(t.rstrip(".") for t in WORD_RE.findall(doc))))
        _JOBS_CACHE["rows"] = out
        _JOBS_CACHE["stamp"] = stamp
    return _JOBS_CACHE["rows"]


_TERM_HITS: dict[tuple, frozenset] = {}


def _matching(tree, jobs: list[tuple[dict, str, frozenset]]) -> set[int]:
    """Evaluate a boolean query over the whole index with set operations. Each term's matching jobs are computed
    once per index version and shared by every student whose query uses that term (React, intern, Bengaluru...)."""
    stamp = _JOBS_CACHE["stamp"]

    def hits(node) -> frozenset | set:
        if node.op == "TERM":
            key = (stamp, node.term)
            found = _TERM_HITS.get(key)
            if found is None:
                if SIMPLE_TERM.match(node.term):          # single word: exact token lookup (same boundaries as the regex)
                    found = frozenset(i for i, (_, _, toks) in enumerate(jobs) if node.term in toks)
                else:                                     # phrases: cheap substring test, then the exact regex
                    plain = node.term.split()[0] if node.term else ""
                    found = frozenset(i for i, (_, doc, _) in enumerate(jobs) if plain in doc and _term_matches(node.term, doc))
                if len(_TERM_HITS) > 20_000:
                    _TERM_HITS.clear()
                _TERM_HITS[key] = found
            return found
        if node.op == "NOT":
            return set(range(len(jobs))) - hits(node.children[0])
        parts = [hits(c) for c in node.children]
        if node.op == "AND":
            return set.intersection(*map(set, parts)) if parts else set()
        return set().union(*parts)

    return set(hits(tree))


def warm_job_index() -> None:
    """Load the job index into memory at startup so the first search is fast."""
    try:
        from .ranker import _job_features

        for job, _, _ in _active_jobs():
            _job_features(job)
    except Exception:  # pragma: no cover - warming is best effort
        log.exception("job index warm-up failed")


def search(user: dict, query: str | None = None, filters: dict | None = None, page: int = 1, per_page: int = 20) -> dict:
    db = get_db()
    filters = filters or {}
    profile = student_profile(user)
    default = build_query(profile["skills"], profile["target_role"], profile["job_type"], profile["locations"])
    q = (query or "").strip() or default["query"]
    try:
        tree = parse(q)
    except QueryError as exc:
        return {"error": f"Query error: {exc}", "query": q, "default_query": default}
    saved = {r["job_id"]: r for r in db.fetchall("SELECT id, job_id, status FROM applications WHERE user_id = ? AND job_id IS NOT NULL",
                                                 (user["id"],))}
    jobs = _active_jobs()
    scored = []
    for idx in sorted(_matching(tree, jobs)):
        job = jobs[idx][0]
        if filters.get("type") and filters["type"] != "all" and job["employment_type"] != filters["type"]:
            continue
        if filters.get("remote") and not job["remote"]:
            continue
        s = score_job(job, profile)
        if filters.get("min_match") and s["match"] < int(filters["min_match"]):
            continue
        scored.append((job, s))
    scored.sort(key=lambda r: r[0]["posted_at"] or "", reverse=True)   # newest first among equal matches
    scored.sort(key=lambda r: -r[1]["match"])
    total = len(scored)
    start = (page - 1) * per_page
    results = [{"job": public_job(job), **s, "application": saved.get(job["id"])} for job, s in scored[start:start + per_page]]
    msot = msot_for_student(user, profile)
    return {"query": q, "default_query": default, "total": total, "page": page, "per_page": per_page,
            "results": results, "msot": msot, "deep_links": deep_links(default, profile["locations"],
                                                                                                profile["job_type"]),
            "profile": {"skills": profile["skills"][:20], "role": profile["target_role"], "job_type": profile["job_type"],
                        "locations": profile["locations"]}}


def public_job(job: dict) -> dict:
    meta = REGISTRY.get(job["source"], {})
    return {
        "id": job["id"], "title": job["title"], "company": job["company"], "location": job["location"], "remote": bool(job["remote"]),
        "employment_type": job["employment_type"], "experience_min": job.get("experience_min"), "salary": job.get("salary"),
        "url": job["url"], "source": job["source"], "source_label": meta.get("label", job["source"]),
        "posted_at": job.get("posted_at"), "skills": job.get("skills") or [], "also_on": job.get("also_on") or [],
        "description": (job.get("description") or "")[:1500],
    }


def msot_for_student(user: dict, profile: dict) -> dict:
    db = get_db()
    rows = db.fetchall("SELECT * FROM msot_jobs WHERE status = 'open' AND (deadline IS NULL OR deadline >= ?) ORDER BY id DESC",
                       (now_iso()[:10],))
    applied = {r["msot_job_id"]: r for r in db.fetchall("SELECT id, msot_job_id, status FROM applications WHERE user_id = ? "
                                                        "AND msot_job_id IS NOT NULL", (user["id"],))}
    eligible, ineligible = [], []
    for j in rows:
        ok, reasons = msot_eligibility(j, profile)
        fake = {"title": j["title"], "description": j["description"], "skills": j["skills"], "employment_type": j["employment_type"],
                "location": j["location"], "remote": "remote" in (j["location"] or "").lower(), "posted_at": j["created_at"]}
        s = score_job(fake, profile)
        item = {"job": {**{k: j[k] for k in ("id", "title", "company", "location", "employment_type", "stipend", "deadline",
                                             "apply_url", "created_at")}, "skills": j["skills"], "description": j["description"][:1500],
                        "eligibility": j["eligibility"], "source": "msot", "source_label": "MSOT Placement Cell"},
                **s, "eligible": ok, "ineligible_reasons": reasons, "application": applied.get(j["id"])}
        (eligible if ok else ineligible).append(item)
    return {"eligible": eligible, "ineligible": ineligible}
