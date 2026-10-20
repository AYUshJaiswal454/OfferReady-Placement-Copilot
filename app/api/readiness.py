from __future__ import annotations

from ..db import get_db
from ..readiness.score import compute, snapshot
from ..web import Ctx, Router

router = Router("/api")


@router.get("/readiness")
def readiness(ctx: Ctx):
    result = compute(ctx.uid)
    history = get_db().fetchall("SELECT score, level, components, created_at FROM readiness_snapshots WHERE user_id = ? ORDER BY id",
                                (ctx.uid,))
    hist = [{"score": h["score"], "level": h["level"], "created_at": h["created_at"],
             "components": {k: v.get("score") for k, v in (h["components"] or {}).items()}} for h in history]
    return {**result, "history": hist}


@router.post("/readiness/recompute")
def recompute(ctx: Ctx):
    return snapshot(ctx.uid)
