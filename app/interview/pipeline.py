"""Background scoring of finished interviews."""
from __future__ import annotations

from ..db import get_db, now_iso
from ..tasks import enqueue, handler
from .scorer import score_interview


@handler("score_interview")
async def score_interview_task(task: dict) -> dict:
    db = get_db()
    iid = task["payload"]["interview_id"]
    interview = db.fetchone("SELECT * FROM interviews WHERE id = ?", (iid,))
    if not interview:
        return {"skipped": "deleted"}
    user = db.fetchone("SELECT * FROM users WHERE id = ?", (interview["user_id"],))
    turns = db.fetchall("SELECT * FROM interview_turns WHERE interview_id = ? ORDER BY seq", (iid,))
    answered = [t for t in turns if t["speaker"] == "candidate"]
    if len(answered) < 2:
        db.update("interviews", iid, {"status": "abandoned", "result": {"reason": "Too few answers to score."}})
        return {"abandoned": True}
    result = await score_interview(interview["plan"], turns, user)
    db.update("interviews", iid, {"status": "completed", "score": result["score"], "result": result,
                                  "ended_at": interview["ended_at"] or now_iso()})
    enqueue("recompute_readiness", {"user_id": interview["user_id"]}, user_id=interview["user_id"],
            dedupe_key=f"readiness:{interview['user_id']}")
    return {"score": result["score"]}
