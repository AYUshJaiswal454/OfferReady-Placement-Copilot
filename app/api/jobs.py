from __future__ import annotations

import re

from pydantic import BaseModel, Field

from ..config import get_settings
from ..db import get_db, now_iso
from ..jobs.connectors import REGISTRY
from ..jobs.pipeline import key_configured, public_job, search, source_config, student_profile
from ..jobs.ranker import msot_eligibility, score_job
from ..tracker import applications as apps
from ..web import ApiError, Ctx, Router

router = Router("/api")


class ImportIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    company: str = Field(min_length=1, max_length=160)
    url: str | None = Field(default=None, max_length=1000)
    description: str | None = Field(default=None, max_length=12000)
    location: str | None = Field(default=None, max_length=160)
    status: str = Field(default="saved", pattern="^(saved|applied)$")


class MsotApplyIn(BaseModel):
    share_report: bool = True


@router.get("/jobs")
def jobs(ctx: Ctx):
    filters = {"type": ctx.query.get("type") or "all", "remote": ctx.query.get("remote") in ("1", "true"),
               "min_match": ctx.query.get("min_match")}
    return search(ctx.user, ctx.query.get("q"), filters, ctx.qint("page", 1, 1, 200), ctx.qint("per_page", 20, 5, 50))


@router.get("/jobs/sources")
def sources(ctx: Ctx):
    cfg = source_config()
    health = {r["source"]: r for r in get_db().fetchall("SELECT * FROM source_health")}
    counts = {r["source"]: r["n"] for r in get_db().fetchall(
        "SELECT source, COUNT(*) n FROM jobs_index WHERE active = 1 GROUP BY source")}
    out = []
    for name, meta in REGISTRY.items():
        out.append({"name": name, "label": meta["label"], "kind": meta["kind"], "terms": meta["terms"],
                    "enabled": bool((cfg.get(name) or {}).get("enabled")), "needs_key": meta["needs_key"],
                    "configured": key_configured(name),
                    "health": health.get(name), "active_jobs": counts.get(name, 0)})
    not_scraped = ["LinkedIn", "Naukri", "Internshala", "Wellfound", "Indeed"]
    return {"sources": out, "not_scraped": not_scraped, "offline_mode": get_settings().offline_mode,
            "policy": "We only use official APIs, public job-board feeds intended for syndication and RSS. Sites whose terms "
                      "forbid scraping are offered as search links that you open yourself."}


@router.get("/jobs/{job_id:int}")
def job_detail(ctx: Ctx):
    job = get_db().fetchone("SELECT * FROM jobs_index WHERE id = ?", (ctx.path["job_id"],))
    if not job:
        raise ApiError(404, "Job not found", "not_found")
    profile = student_profile(ctx.user)
    out = public_job(job)
    out["description"] = job.get("description") or ""
    app = get_db().fetchone("SELECT id, status FROM applications WHERE user_id = ? AND job_id = ?", (ctx.uid, job["id"]))
    return {"job": out, **score_job(job, profile), "application": app}


@router.post("/jobs/import")
def import_job(ctx: Ctx):
    """A job the student found elsewhere (LinkedIn, Naukri, referral): pasted by them, never scraped."""
    from ..jobs.normalize import normalize
    from ..jobs.pipeline import upsert_jobs

    d = ctx.parse(ImportIn)
    url = d.url or f"https://manual.offerready.local/{ctx.uid}/{abs(hash((d.title, d.company))) % 10**8}"
    if d.description:
        upsert_jobs([{"source": "manual", "source_job_id": f"u{ctx.uid}:{url}", "url": url, "title": d.title, "company": d.company,
                      "location": d.location, "description": d.description, "posted_at": now_iso()}])
    job = get_db().fetchone("SELECT * FROM jobs_index WHERE source = 'manual' AND source_job_id = ?", (f"u{ctx.uid}:{url}",))
    match = score_job(job, student_profile(ctx.user)) if job else None
    app = apps.create(ctx.uid, {"job_id": job["id"] if job else None, "title": d.title, "company": d.company, "url": d.url,
                                "location": d.location, "source": "manual", "status": d.status,
                                "match_score": match["match"] if match else None})
    return {"application": app, "match": match}


@router.post("/msot/jobs/{job_id:int}/apply", consent=True)
def msot_apply(ctx: Ctx):
    d = ctx.parse(MsotApplyIn)
    job = get_db().fetchone("SELECT * FROM msot_jobs WHERE id = ? AND status = 'open'", (ctx.path["job_id"],))
    if not job:
        raise ApiError(404, "This job is closed or does not exist", "not_found")
    ok, reasons = msot_eligibility(job, student_profile(ctx.user))
    if not ok:
        raise ApiError(403, "Not eligible: " + "; ".join(reasons), "not_eligible")
    app = apps.create(ctx.uid, {"msot_job_id": job["id"], "title": job["title"], "company": job["company"],
                                "url": job.get("apply_url"), "location": job.get("location"), "source": "msot",
                                "status": "applied", "shared_report": d.share_report})
    if d.share_report:
        get_db().update("applications", app["id"], {"shared_report": 1})
    apps.notify(ctx.uid, "application", f"Applied to {job['company']} — {job['title']}",
                "The MSOT placement cell can now see your application" + (" and readiness report." if d.share_report else "."),
                "/tracker", f"msot-apply:{app['id']}")
    return {"application": apps.get(ctx.uid, app["id"])}
