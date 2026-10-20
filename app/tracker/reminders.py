"""Follow-up and interview reminders (in-app notifications, optional email)."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from ..config import get_settings
from ..db import get_db, iso_in, now_iso, parse_iso, utcnow
from ..tasks import handler, schedule

log = logging.getLogger("offerready.reminders")


def maybe_email(user_id: int, subject: str, body: str) -> None:
    s = get_settings()
    if not s.smtp_host:
        return
    user = get_db().fetchone("SELECT email, settings FROM users WHERE id = ?", (user_id,))
    if not user or not (user.get("settings") or {}).get("email_reminders", True):
        return
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_from, user["email"], f"[OfferReady] {subject}"
    msg.set_content(f"{body}\n\nOpen your tracker: {s.base_url}/tracker")
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
            smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)
    except Exception as exc:  # pragma: no cover - depends on SMTP server
        log.warning("email failed: %s", exc)


@handler("send_reminders")
def send_reminders(task: dict) -> dict:
    from .applications import notify

    db = get_db()
    now = now_iso()
    sent = 0
    for a in db.fetchall("SELECT * FROM applications WHERE next_follow_up_at IS NOT NULL AND next_follow_up_at <= ? "
                         "AND status IN ('applied', 'shortlisted')", (now,)):
        applied = parse_iso(a.get("applied_at") or a["created_at"])
        days = (utcnow() - applied).days if applied else 0
        nid = notify(a["user_id"], "follow_up", f"Follow up with {a['company']} about {a['title']}",
                     f"You applied {days} days ago and the status hasn't changed. A short, polite email to the recruiter "
                     f"or a LinkedIn message can move it forward.", "/tracker", f"fu:{a['id']}:{a['next_follow_up_at'][:10]}")
        sent += nid is not None
    for a in db.fetchall("SELECT * FROM applications WHERE status = 'interview' AND interview_at IS NOT NULL "
                         "AND interview_at BETWEEN ? AND ?", (now, iso_in(hours=26))):
        nid = notify(a["user_id"], "interview", f"Interview with {a['company']} soon",
                     f"Your interview for {a['title']} is at {a['interview_at']}. Take a mock interview today to warm up.",
                     "/interview", f"iv:{a['id']}:{a['interview_at'][:13]}")
        sent += nid is not None
    for a in db.fetchall("SELECT a.*, m.deadline FROM applications a JOIN msot_jobs m ON m.id = a.msot_job_id "
                         "WHERE a.status = 'saved' AND m.deadline IS NOT NULL AND m.deadline BETWEEN ? AND ?",
                         (now[:10], iso_in(days=2)[:10])):
        nid = notify(a["user_id"], "deadline", f"Deadline soon: {a['company']} — {a['title']}",
                     f"Applications close on {a['deadline']}. You saved this job but haven't applied yet.", "/jobs",
                     f"dl:{a['id']}")
        sent += nid is not None
    return {"sent": sent}


schedule("send_reminders", 15 * 60, "send_reminders")
