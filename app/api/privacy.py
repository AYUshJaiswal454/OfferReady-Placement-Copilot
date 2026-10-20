from __future__ import annotations

import io
import json
import zipfile

from starlette.responses import JSONResponse, Response

from ..db import audit, get_db
from ..security import SESSION_COOKIE
from ..storage import delete_user_files, read_file
from ..web import ApiError, Ctx, Router, public_user

router = Router("/api")
USER_TABLES = ["profile_sources", "reviews", "readiness_snapshots", "interviews", "applications", "notifications",
               "chat_messages", "usage_ledger"]


@router.get("/me/export", rate=(5, 3600))
def export(ctx: Ctx):
    db = get_db()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("account.json", json.dumps(public_user(ctx.user), indent=2, default=str))
        for table in USER_TABLES:
            rows = db.fetchall(f"SELECT * FROM {table} WHERE user_id = ?", (ctx.uid,))
            z.writestr(f"{table}.json", json.dumps(rows, indent=2, default=str))
        turns = db.fetchall("SELECT t.* FROM interview_turns t JOIN interviews i ON i.id = t.interview_id WHERE i.user_id = ?", (ctx.uid,))
        z.writestr("interview_turns.json", json.dumps(turns, indent=2, default=str))
        for f in db.fetchall("SELECT * FROM files WHERE user_id = ? AND kind IN ('resume', 'linkedin', 'interview_audio')", (ctx.uid,)):
            try:
                z.writestr(f"files/{f['id']}_{f['filename']}", read_file(f))
            except OSError:
                pass
        z.writestr("README.txt", "Everything OfferReady stores about you. Files were decrypted for this export.")
    audit(ctx.uid, "privacy.export", "user", ctx.uid)
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"content-disposition": 'attachment; filename="offerready-my-data.zip"'})


def delete_user_data(user_id: int) -> dict:
    db = get_db()
    counts = {}
    with db.transaction():
        db.execute("DELETE FROM interview_turns WHERE interview_id IN (SELECT id FROM interviews WHERE user_id = ?)", (user_id,))
        for table in USER_TABLES + ["tasks"]:
            cur = db.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
            counts[table] = cur.rowcount
    counts["files"] = delete_user_files(user_id)
    return counts


@router.delete("/me", rate=(3, 3600))
def delete_me(ctx: Ctx):
    if (ctx.body or {}).get("confirm") != "DELETE":
        raise ApiError(400, "Type DELETE to confirm", "confirm")
    if ctx.is_admin:
        raise ApiError(403, "Admin accounts cannot be self-deleted here", "forbidden")
    counts = delete_user_data(ctx.uid)
    audit(None, "privacy.delete_account", "user", ctx.uid, {"rows": sum(v for v in counts.values() if isinstance(v, int))})
    get_db().execute("DELETE FROM users WHERE id = ?", (ctx.uid,))
    resp = JSONResponse({"ok": True, "deleted": counts})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp
