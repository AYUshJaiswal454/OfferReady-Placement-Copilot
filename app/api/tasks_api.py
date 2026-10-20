from __future__ import annotations

from ..db import get_db, iso_in
from ..web import Ctx, Router

router = Router("/api")
LABELS = {"review_resume": "Resume review", "review_linkedin": "LinkedIn review", "review_github": "GitHub review",
          "review_project": "Project review", "review_coding": "Coding profiles", "review_achievements": "Achievements",
          "recompute_readiness": "Readiness score", "score_interview": "Interview scoring", "crawl_jobs": "Job refresh"}


@router.get("/tasks")
def tasks(ctx: Ctx):
    ids = [int(x) for x in (ctx.query.get("ids") or "").split(",") if x.strip().isdigit()][:50]
    db = get_db()
    if ids:
        marks = ",".join("?" for _ in ids)
        rows = db.fetchall(f"SELECT id, kind, status, progress, message, error, created_at, finished_at FROM tasks "
                           f"WHERE user_id = ? AND id IN ({marks})", (ctx.uid, *ids))
    else:
        rows = db.fetchall("SELECT id, kind, status, progress, message, error, created_at, finished_at FROM tasks WHERE user_id = ? "
                           "AND (status IN ('queued', 'running') OR finished_at >= ?) AND kind != 'recompute_readiness' "
                           "ORDER BY id DESC LIMIT 20", (ctx.uid, iso_in(minutes=-2)))
    for r in rows:
        r["label"] = LABELS.get(r["kind"], r["kind"])
        if r["error"]:
            r["error"] = r["error"].split("\n")[0][:200]
    return {"tasks": rows}
