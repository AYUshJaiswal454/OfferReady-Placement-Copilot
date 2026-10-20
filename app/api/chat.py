from __future__ import annotations

import json

from starlette.responses import StreamingResponse

from ..chat.agent import respond
from ..db import get_db
from ..web import ApiError, Ctx, Router

router = Router("/api")


@router.get("/chat/history")
def history(ctx: Ctx):
    rows = get_db().fetchall("SELECT id, role, content, cards, created_at FROM chat_messages WHERE user_id = ? ORDER BY id DESC "
                             "LIMIT 60", (ctx.uid,))
    return {"messages": list(reversed(rows))}


@router.delete("/chat/history")
def clear(ctx: Ctx):
    get_db().execute("DELETE FROM chat_messages WHERE user_id = ?", (ctx.uid,))
    return {"ok": True}


@router.post("/chat", consent=True, rate=(60, 600))
async def chat(ctx: Ctx):
    text = str((ctx.body or {}).get("message", "")).strip()[:4000]
    if not text:
        raise ApiError(400, "Message is empty", "empty")

    async def events():
        try:
            async for event in respond(ctx.user, text):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:  # pragma: no cover
            yield f"data: {json.dumps({'type': 'error', 'message': 'Something went wrong. Please try again.'})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"cache-control": "no-cache", "x-accel-buffering": "no"})
