from __future__ import annotations

from pydantic import BaseModel, Field

from .. import profile_service as ps
from ..config import get_settings
from ..db import audit, get_db
from ..web import ApiError, Ctx, Router

router = Router("/api")


class GithubIn(BaseModel):
    username: str = Field(min_length=1, max_length=120)


class CodingIn(BaseModel):
    platform: str = Field(pattern="^(leetcode|codeforces)$")
    username: str | None = Field(default=None, max_length=120)
    manual: dict | None = None


class ProjectIn(BaseModel):
    name: str = Field(default="", max_length=80)
    repo_url: str | None = Field(default=None, max_length=500)
    live_url: str | None = Field(default=None, max_length=500)
    description: str = Field(default="", max_length=1500)
    tech: list[str] | None = Field(default=None, max_length=12)


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    repo_url: str | None = Field(default=None, max_length=500)
    live_url: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=1500)
    tech: list[str] | None = Field(default=None, max_length=12)


class AchievementIn(BaseModel):
    text: str = Field(min_length=6, max_length=400)
    category: str | None = Field(default=None, max_length=40)


class LinkedinTextIn(BaseModel):
    text: str = Field(min_length=40, max_length=30000)
    photo: bool | None = None


class PhotoIn(BaseModel):
    has_photo: bool


@router.get("/profile")
def get_profile(ctx: Ctx):
    return ps.profile_overview(ctx.uid)


@router.post("/profile/resume", consent=True, rate=(20, 3600))
def upload_resume(ctx: Ctx):
    f = ctx.files.get("file")
    if not f:
        raise ApiError(400, "Attach the resume file in the 'file' field", "no_file")
    return ps.upload_resume(ctx.uid, f["filename"], f["data"], f["content_type"], get_settings().max_upload_mb)


@router.post("/profile/linkedin", consent=True, rate=(20, 3600))
def upload_linkedin(ctx: Ctx):
    f = ctx.files.get("file")
    if f:
        photo = ctx.form.get("photo")
        return ps.upload_linkedin(ctx.uid, f["filename"], f["data"], None,
                                  None if photo in (None, "") else photo in ("true", "1", "yes"), get_settings().max_upload_mb)
    data = ctx.parse(LinkedinTextIn)
    return ps.upload_linkedin(ctx.uid, None, None, data.text, data.photo, get_settings().max_upload_mb)


@router.post("/profile/linkedin/photo", consent=True)
def linkedin_photo(ctx: Ctx):
    f = ctx.files.get("file")
    if f:
        if len(f["data"]) > 8 * 1024 * 1024:
            raise ApiError(413, "Screenshot too large", "too_large")
        detected = ps.detect_face(f["data"])
        res = ps.set_linkedin_photo(ctx.uid, detected, detected=True)
        return {"detected": detected, **(res or {})}
    data = ctx.parse(PhotoIn)
    res = ps.set_linkedin_photo(ctx.uid, data.has_photo)
    if res is None:
        raise ApiError(404, "Add your LinkedIn profile first", "no_linkedin")
    return res


@router.post("/profile/github", consent=True, rate=(30, 3600))
def add_github(ctx: Ctx):
    return ps.add_github(ctx.uid, ctx.parse(GithubIn).username)


@router.post("/profile/coding", consent=True, rate=(30, 3600))
def add_coding(ctx: Ctx):
    d = ctx.parse(CodingIn)
    return ps.add_coding(ctx.uid, d.platform, d.username, d.manual)


@router.post("/profile/projects", consent=True, rate=(40, 3600))
def add_project(ctx: Ctx):
    d = ctx.parse(ProjectIn)
    return ps.add_project(ctx.uid, d.name, d.repo_url, d.live_url, d.description, d.tech)


@router.patch("/profile/projects/{source_id:int}", consent=True, rate=(60, 3600))
def patch_project(ctx: Ctx):
    d = ctx.parse(ProjectPatch)
    return ps.update_project(ctx.uid, ctx.path["source_id"], d.model_dump(exclude_unset=True))


@router.post("/profile/achievements", consent=True)
def add_achievement(ctx: Ctx):
    d = ctx.parse(AchievementIn)
    return ps.add_achievement(ctx.uid, d.text, d.category)


@router.delete("/profile/sources/{source_id:int}")
def delete_source(ctx: Ctx):
    if not ps.delete_source(ctx.uid, ctx.path["source_id"]):
        raise ApiError(404, "Not found", "not_found")
    return {"ok": True}


@router.post("/profile/sources/{source_id:int}/rerun", consent=True, rate=(30, 3600))
def rerun_source(ctx: Ctx):
    from ..tasks import enqueue

    src = get_db().fetchone("SELECT * FROM profile_sources WHERE id = ? AND user_id = ?", (ctx.path["source_id"], ctx.uid))
    if not src:
        raise ApiError(404, "Not found", "not_found")
    kind_task = {"resume": "review_resume", "linkedin": "review_linkedin", "github": "review_github", "project": "review_project"}
    if src["kind"] in kind_task:
        tid = enqueue(kind_task[src["kind"]], {"source_id": src["id"]}, user_id=ctx.uid, dedupe_key=f"rerun:{src['id']}")
    elif src["kind"] in ("leetcode", "codeforces"):
        tid = enqueue("review_coding", {"user_id": ctx.uid}, user_id=ctx.uid, dedupe_key=f"coding:{ctx.uid}")
    else:
        tid = enqueue("review_achievements", {"user_id": ctx.uid}, user_id=ctx.uid, dedupe_key=f"ach:{ctx.uid}")
    get_db().update("profile_sources", src["id"], {"status": "pending", "error": None})
    audit(ctx.uid, "source.rerun", "source", src["id"])
    return {"task_id": tid}
