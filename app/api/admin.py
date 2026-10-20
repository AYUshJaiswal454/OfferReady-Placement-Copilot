"""MSOT placement cell: job board, applicants, cohort analytics, sources, costs."""
from __future__ import annotations

import statistics
from collections import Counter

from pydantic import BaseModel, Field

from ..db import audit, get_db, now_iso
from ..readiness.score import LABELS, compute, level_for
from ..tasks import enqueue
from ..tracker import applications as apps
from ..web import ApiError, Ctx, Router

KIND_LABEL = {"resume": "Resume", "linkedin": "LinkedIn", "github": "GitHub", "project": "Projects"}
router = Router("/api/admin")


class JobIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    company: str = Field(min_length=1, max_length=160)
    location: str | None = Field(default=None, max_length=160)
    employment_type: str = Field(default="internship", pattern="^(internship|fulltime|contract)$")
    stipend: str | None = Field(default=None, max_length=80)
    description: str = Field(min_length=20, max_length=12000)
    apply_url: str | None = Field(default=None, max_length=1000)
    skills: list[str] = Field(default_factory=list, max_length=20)
    min_score: float | None = Field(default=None, ge=0, le=100)
    batches: list[int] = Field(default_factory=list, max_length=6)
    branches: list[str] = Field(default_factory=list, max_length=12)
    deadline: str | None = Field(default=None, max_length=10)
    status: str = Field(default="open", pattern="^(open|closed)$")


class StatusIn(BaseModel):
    status: str = Field(pattern="^(applied|shortlisted|interview|offer|rejected)$")
    note: str | None = Field(default=None, max_length=500)
    interview_at: str | None = Field(default=None, max_length=40)


def _job_row(d: JobIn, user_id: int) -> dict:
    from ..skills import extract_skills

    skills = d.skills or extract_skills(d.description, technical_context=True)[:12]
    return {"title": d.title, "company": d.company, "location": d.location, "employment_type": d.employment_type,
            "stipend": d.stipend, "description": d.description, "apply_url": d.apply_url, "skills": skills,
            "eligibility": {"min_score": d.min_score, "batches": d.batches, "branches": d.branches, "skills": d.skills},
            "deadline": d.deadline, "status": d.status, "posted_by": user_id, "updated_at": now_iso()}


@router.get("/jobs", auth="admin")
def list_jobs(ctx: Ctx):
    rows = get_db().fetchall("SELECT j.*, (SELECT COUNT(*) FROM applications a WHERE a.msot_job_id = j.id) AS applicants "
                             "FROM msot_jobs j ORDER BY j.id DESC")
    return {"jobs": rows}


@router.post("/jobs", auth="admin")
def create_job(ctx: Ctx):
    d = ctx.parse(JobIn)
    jid = get_db().insert("msot_jobs", {**_job_row(d, ctx.uid), "created_at": now_iso()})
    audit(ctx.uid, "admin.job_create", "msot_job", jid)
    _notify_eligible(jid)
    return {"job": get_db().fetchone("SELECT * FROM msot_jobs WHERE id = ?", (jid,))}


def _notify_eligible(job_id: int) -> int:
    from ..jobs.pipeline import student_profile
    from ..jobs.ranker import msot_eligibility

    db = get_db()
    job = db.fetchone("SELECT * FROM msot_jobs WHERE id = ?", (job_id,))
    n = 0
    for u in db.fetchall("SELECT * FROM users WHERE role = 'student'"):
        ok, _ = msot_eligibility(job, student_profile(u))
        if ok:
            apps.notify(u["id"], "msot_job", f"New from MSOT: {job['title']} at {job['company']}",
                        f"You're eligible. Apply before {job['deadline'] or 'it closes'}.", "/jobs", f"msot-job:{job_id}")
            n += 1
    return n


@router.patch("/jobs/{job_id:int}", auth="admin")
def update_job(ctx: Ctx):
    """Partial update: fields that are not sent keep their current values."""
    current = get_db().fetchone("SELECT * FROM msot_jobs WHERE id = ?", (ctx.path["job_id"],))
    if not current:
        raise ApiError(404, "Job not found", "not_found")
    elig = current.get("eligibility") or {}
    merged = {k: current.get(k) for k in JobIn.model_fields if k in current}
    merged.update({"min_score": elig.get("min_score"), "batches": elig.get("batches") or [], "branches": elig.get("branches") or []})
    merged = {k: v for k, v in merged.items() if v is not None}
    merged.update(ctx.body if isinstance(ctx.body, dict) else {})
    ctx.body = merged
    d = ctx.parse(JobIn)
    row = _job_row(d, ctx.uid)
    row.pop("posted_by")                         # keep the original poster
    if not get_db().update("msot_jobs", ctx.path["job_id"], row):
        raise ApiError(404, "Job not found", "not_found")
    audit(ctx.uid, "admin.job_update", "msot_job", ctx.path["job_id"])
    return {"job": get_db().fetchone("SELECT * FROM msot_jobs WHERE id = ?", (ctx.path["job_id"],))}


@router.get("/jobs/{job_id:int}/applicants", auth="admin")
def applicants(ctx: Ctx):
    db = get_db()
    job = db.fetchone("SELECT * FROM msot_jobs WHERE id = ?", (ctx.path["job_id"],))
    if not job:
        raise ApiError(404, "Job not found", "not_found")
    rows = db.fetchall("SELECT a.id, a.status, a.applied_at, a.status_history, a.shared_report, a.updated_at, u.id AS student_id, "
                       "u.name, u.email, u.roll_no, u.batch_year, u.branch FROM applications a JOIN users u ON u.id = a.user_id "
                       "WHERE a.msot_job_id = ? ORDER BY a.applied_at", (job["id"],))
    for r in rows:
        snap = db.fetchone("SELECT score, level FROM readiness_snapshots WHERE user_id = ? ORDER BY id DESC LIMIT 1", (r["student_id"],))
        r["readiness"] = snap["score"] if snap else None
        r["level"] = snap["level"] if snap else None
    audit(ctx.uid, "admin.view_applicants", "msot_job", job["id"])
    return {"job": job, "applicants": rows}


@router.patch("/applications/{aid:int}", auth="admin")
def update_application(ctx: Ctx):
    d = ctx.parse(StatusIn)
    row = get_db().fetchone("SELECT * FROM applications WHERE id = ? AND msot_job_id IS NOT NULL", (ctx.path["aid"],))
    if not row:
        raise ApiError(404, "Application not found", "not_found")
    app = apps.update_status(row["user_id"], row["id"], d.status, by="admin", note=d.note, interview_at=d.interview_at)
    audit(ctx.uid, "admin.application_status", "application", row["id"], {"status": d.status})
    return {"application": app}


@router.get("/students", auth="admin")
def students(ctx: Ctx):
    db = get_db()
    q = (ctx.query.get("q") or "").strip().lower()
    rows = db.fetchall("SELECT id, name, email, roll_no, batch_year, branch, target_role, created_at, last_seen_at FROM users "
                       "WHERE role = 'student' ORDER BY name")
    out = []
    for u in rows:
        if q and q not in f"{u['name']} {u['email']} {u['roll_no'] or ''}".lower():
            continue
        snap = db.fetchone("SELECT score, level, created_at FROM readiness_snapshots WHERE user_id = ? ORDER BY id DESC LIMIT 1", (u["id"],))
        shared = bool(db.fetchone("SELECT id FROM applications WHERE user_id = ? AND shared_report = 1", (u["id"],)))
        out.append({**u, "readiness": snap["score"] if snap else None, "level": snap["level"] if snap else "No data",
                    "report_shared": shared})
    return {"students": out}


@router.get("/students/{sid:int}/report", auth="admin")
def student_report(ctx: Ctx):
    from .reviews import build_report

    db = get_db()
    if not db.fetchone("SELECT id FROM applications WHERE user_id = ? AND shared_report = 1", (ctx.path["sid"],)):
        raise ApiError(403, "This student has not shared their report with the placement cell", "not_shared")
    audit(ctx.uid, "admin.view_report", "user", ctx.path["sid"])
    return build_report(ctx.path["sid"])


@router.get("/overview", auth="admin")
def overview(ctx: Ctx):
    db = get_db()
    students = db.fetchall("SELECT id, batch_year, branch FROM users WHERE role = 'student'")
    scores, levels, comp = [], Counter(), {k: [] for k in LABELS}
    failing = Counter()
    for s in students:
        snap = db.fetchone("SELECT score, level, components FROM readiness_snapshots WHERE user_id = ? ORDER BY id DESC LIMIT 1", (s["id"],))
        if not snap:
            levels["No data"] += 1
            continue
        scores.append(snap["score"])
        levels[snap["level"]] += 1
        for k, v in (snap["components"] or {}).items():
            if v.get("score") is not None and k in comp:
                comp[k].append(v["score"])
    titles: dict[str, str] = {}
    who: dict[str, set] = {}
    for r in db.fetchall("SELECT r.user_id, r.kind, r.checks FROM reviews r JOIN (SELECT user_id, kind, COALESCE(source_id, 0) sid, "
                         "MAX(id) mid FROM reviews WHERE kind IN ('resume', 'linkedin', 'github', 'project') "
                         "GROUP BY user_id, kind, COALESCE(source_id, 0)) x ON x.mid = r.id"):
        for c in r["checks"]:
            if c.get("status") in ("fail", "warn"):
                key = f"{r['kind']}:{c['id']}"
                who.setdefault(key, set()).add(r["user_id"])      # a student counts once, even with 3 failing projects
                titles[key] = f"{KIND_LABEL.get(r['kind'], r['kind'])}: {c['title']}"
    for key, users in who.items():
        failing[key] = len(users)
    reviewed = max(1, len({r["user_id"] for r in db.fetchall("SELECT DISTINCT user_id FROM reviews WHERE kind = 'resume'")}))
    buckets = Counter(min(9, int(s // 10)) for s in scores)
    funnel = {r["status"]: r["n"] for r in db.fetchall("SELECT status, COUNT(*) n FROM applications GROUP BY status")}
    usage = db.fetchone("SELECT COUNT(DISTINCT user_id) users, COALESCE(SUM(cost_usd), 0) cost, COALESCE(SUM(input_tokens), 0) tin, "
                        "COALESCE(SUM(output_tokens), 0) tout, COALESCE(SUM(estimated), 0) est, COUNT(*) calls "
                        "FROM usage_ledger WHERE user_id IS NOT NULL")
    by_feature = db.fetchall("SELECT feature, provider, COUNT(*) calls, SUM(input_tokens) tin, SUM(output_tokens) tout, "
                             "SUM(cost_usd) cost, AVG(latency_ms) latency FROM usage_ledger GROUP BY feature, provider ORDER BY cost DESC")
    return {
        "students": len(students), "with_score": len(scores),
        "average": round(statistics.mean(scores), 1) if scores else None,
        "median": round(statistics.median(scores), 1) if scores else None,
        "levels": dict(levels), "distribution": [{"bucket": f"{b * 10}–{b * 10 + 9}", "count": buckets.get(b, 0)} for b in range(10)],
        "components": {k: {"label": LABELS[k], "average": round(statistics.mean(v), 1) if v else None, "n": len(v)} for k, v in comp.items()},
        "common_gaps": [{"key": k, "title": titles[k], "students": n, "share": round(n / reviewed, 2)} for k, n in failing.most_common(10)],
        "funnel": funnel,
        "usage": {"students": usage["users"], "total_cost_usd": round(usage["cost"], 4),
                  "cost_per_student_usd": round(usage["cost"] / usage["users"], 4) if usage["users"] else 0,
                  "projected": bool(usage["calls"]) and usage["est"] == usage["calls"],
                  "by_feature": by_feature},
    }


@router.get("/sources", auth="admin")
def admin_sources(ctx: Ctx):
    from .jobs import sources

    return sources(ctx)


@router.post("/sources/refresh", auth="admin")
def refresh_sources(ctx: Ctx):
    source = (ctx.body or {}).get("source")
    tid = enqueue("crawl_jobs", {"source": source} if source else {}, dedupe_key=f"crawl:{source or 'all'}")
    return {"task_id": tid}
