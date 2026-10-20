from __future__ import annotations

from starlette.responses import Response

from ..db import audit, get_db
from ..storage import get_file_row, read_file
from ..web import ApiError, Ctx, Router

router = Router("/api")
KINDS = ("resume", "linkedin", "github", "project", "coding", "achievements")


def latest_reviews(user_id: int) -> dict:
    db = get_db()
    rows = db.fetchall(
        "SELECT r.id, r.kind, r.source_id, r.score, r.summary, r.created_at, r.benchmark_version FROM reviews r JOIN "
        "(SELECT kind, COALESCE(source_id, 0) sid, MAX(id) mid FROM reviews WHERE user_id = ? GROUP BY kind, COALESCE(source_id, 0)) x "
        "ON x.mid = r.id ORDER BY r.id", (user_id,))
    live = {r["id"] for r in db.fetchall("SELECT id FROM profile_sources WHERE user_id = ?", (user_id,))}
    out: dict[str, list] = {k: [] for k in KINDS}
    for r in rows:
        if r["source_id"] and r["source_id"] not in live:
            continue
        out[r["kind"]].append(r)
    return out


def full_review(review_id: int, user_id: int | None, as_admin: bool = False) -> dict:
    db = get_db()
    r = db.fetchone("SELECT * FROM reviews WHERE id = ?", (review_id,))
    if not r or (not as_admin and r["user_id"] != user_id):
        raise ApiError(404, "Review not found", "not_found")
    history = db.fetchall("SELECT id, score, created_at FROM reviews WHERE user_id = ? AND kind = ? AND COALESCE(source_id, 0) = ? "
                          "ORDER BY id", (r["user_id"], r["kind"], r["source_id"] or 0))
    r["history"] = history
    return r


@router.get("/reviews")
def list_reviews(ctx: Ctx):
    return {"latest": latest_reviews(ctx.uid)}


@router.get("/reviews/{review_id:int}")
def get_review(ctx: Ctx):
    return full_review(ctx.path["review_id"], ctx.uid, ctx.is_admin and False)


@router.get("/report")
def report(ctx: Ctx):
    return build_report(ctx.uid)


def build_report(user_id: int) -> dict:
    from ..readiness.score import compute
    from ..web import public_user

    db = get_db()
    user = db.fetchone("SELECT * FROM users WHERE id = ?", (user_id,))
    latest = latest_reviews(user_id)
    full = {}
    for kind, rows in latest.items():
        full[kind] = [full_review(r["id"], user_id) for r in rows]
    readiness = compute(user_id)
    history = db.fetchall("SELECT score, level, created_at FROM readiness_snapshots WHERE user_id = ? ORDER BY id", (user_id,))
    interview = db.fetchone("SELECT id, score, result, ended_at, duration_min, mode FROM interviews WHERE user_id = ? AND "
                            "status = 'completed' ORDER BY id DESC LIMIT 1", (user_id,))
    return {"user": public_user(user), "readiness": readiness, "history": history, "reviews": full, "interview": interview}


@router.get("/files/{file_id:int}")
def get_file(ctx: Ctx):
    row = get_file_row(ctx.path["file_id"])
    if not row or (row["user_id"] != ctx.uid and not ctx.is_admin):
        raise ApiError(404, "File not found", "not_found")
    if ctx.is_admin and row["user_id"] != ctx.uid:
        shared = get_db().fetchone("SELECT id FROM applications WHERE user_id = ? AND shared_report = 1 LIMIT 1", (row["user_id"],))
        if not shared:
            raise ApiError(403, "The student has not shared their report", "not_shared")
        audit(ctx.uid, "admin.view_file", "file", row["id"])
    data = read_file(row)
    headers = {"cache-control": "private, max-age=600", "content-disposition": f'inline; filename="{row["filename"]}"'}
    return Response(data, media_type=row.get("mime") or "application/octet-stream", headers=headers)
