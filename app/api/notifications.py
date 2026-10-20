from __future__ import annotations

from ..db import get_db, now_iso
from ..web import Ctx, Router

router = Router("/api")


@router.get("/notifications")
def list_notifications(ctx: Ctx):
    db = get_db()
    rows = db.fetchall("SELECT id, kind, title, body, link, read_at, created_at FROM notifications WHERE user_id = ? "
                       "ORDER BY id DESC LIMIT 50", (ctx.uid,))
    unread = db.scalar("SELECT COUNT(*) FROM notifications WHERE user_id = ? AND read_at IS NULL", (ctx.uid,))
    return {"notifications": rows, "unread": unread}


@router.post("/notifications/read")
def mark_read(ctx: Ctx):
    ids = [int(i) for i in (ctx.body or {}).get("ids", []) if str(i).isdigit()][:100]
    db = get_db()
    if ids:
        marks = ",".join("?" for _ in ids)
        db.execute(f"UPDATE notifications SET read_at = ? WHERE user_id = ? AND id IN ({marks})", (now_iso(), ctx.uid, *ids))
    else:
        db.execute("UPDATE notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL", (now_iso(), ctx.uid))
    return {"ok": True}
