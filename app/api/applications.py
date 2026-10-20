from __future__ import annotations

from pydantic import BaseModel, Field
from starlette.responses import Response

from ..db import get_db
from ..tracker import applications as apps
from ..web import ApiError, Ctx, Router

router = Router("/api")


class AppIn(BaseModel):
    job_id: int | None = None
    title: str | None = Field(default=None, max_length=200)
    company: str | None = Field(default=None, max_length=160)
    url: str | None = Field(default=None, max_length=1000)
    location: str | None = Field(default=None, max_length=160)
    status: str = Field(default="saved", pattern="^(saved|applied|shortlisted|interview|offer|rejected)$")
    notes: str | None = Field(default=None, max_length=2000)


class AppPatch(BaseModel):
    status: str | None = Field(default=None, pattern="^(saved|applied|shortlisted|interview|offer|rejected)$")
    notes: str | None = Field(default=None, max_length=2000)
    interview_at: str | None = Field(default=None, max_length=40)
    next_follow_up_at: str | None = Field(default=None, max_length=40)


@router.get("/applications")
def board(ctx: Ctx):
    return apps.board(ctx.uid)


@router.post("/applications")
def create(ctx: Ctx):
    d = ctx.parse(AppIn)
    data = d.model_dump()
    if d.job_id:
        from ..jobs.pipeline import student_profile
        from ..jobs.ranker import score_job

        job = get_db().fetchone("SELECT * FROM jobs_index WHERE id = ?", (d.job_id,))
        if not job:
            raise ApiError(404, "Job not found", "not_found")
        data.update({"title": job["title"], "company": job["company"], "url": job["url"], "location": job["location"],
                     "source": job["source"], "match_score": score_job(job, student_profile(ctx.user))["match"]})
    elif not (d.title and d.company):
        raise ApiError(422, "Title and company are required", "validation_error")
    return {"application": apps.create(ctx.uid, data)}


@router.patch("/applications/{aid:int}")
def update(ctx: Ctx):
    d = ctx.parse(AppPatch)
    app = apps.get(ctx.uid, ctx.path["aid"])
    if not app:
        raise ApiError(404, "Application not found", "not_found")
    if app.get("msot_job_id") and d.status and d.status not in ("saved", "applied"):
        raise ApiError(403, "The placement cell updates the status of MSOT applications", "managed")
    if d.status:
        app = apps.update_status(ctx.uid, app["id"], d.status, interview_at=d.interview_at)
    fields = {}
    if d.notes is not None:
        fields["notes"] = d.notes
    if d.interview_at:
        fields["interview_at"] = d.interview_at
    if d.next_follow_up_at:
        fields["next_follow_up_at"] = d.next_follow_up_at
    if fields:
        get_db().update("applications", app["id"], fields)
    return {"application": apps.get(ctx.uid, app["id"])}


@router.delete("/applications/{aid:int}")
def delete(ctx: Ctx):
    cur = get_db().execute("DELETE FROM applications WHERE id = ? AND user_id = ? AND msot_job_id IS NULL",
                           (ctx.path["aid"], ctx.uid))
    if not cur.rowcount:
        raise ApiError(404, "Not found (MSOT applications can't be deleted, ask the placement cell to withdraw)", "not_found")
    return {"ok": True}


@router.get("/applications.ics")
def calendar(ctx: Ctx):
    return Response(apps.ics(ctx.uid), media_type="text/calendar",
                    headers={"content-disposition": 'attachment; filename="interviews.ics"'})
