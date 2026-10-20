"""Application tracker: statuses, history, follow-up dates, notifications."""
from __future__ import annotations

from ..db import get_db, iso_in, now_iso, parse_iso, utcnow

STATUSES = ["saved", "applied", "shortlisted", "interview", "offer", "rejected"]
LABELS = {"saved": "Saved", "applied": "Applied", "shortlisted": "Shortlisted", "interview": "Interview", "offer": "Offer",
          "rejected": "Rejected"}
FOLLOW_UP_DAYS = {"applied": 7, "shortlisted": 4}


def notify(user_id: int, kind: str, title: str, body: str = "", link: str = "", dedupe_key: str | None = None) -> int | None:
    db = get_db()
    if dedupe_key and db.fetchone("SELECT id FROM notifications WHERE user_id = ? AND dedupe_key = ?", (user_id, dedupe_key)):
        return None
    nid = db.insert("notifications", {"user_id": user_id, "kind": kind, "title": title[:200], "body": body[:1000], "link": link,
                                      "dedupe_key": dedupe_key, "created_at": now_iso()})
    from .reminders import maybe_email

    maybe_email(user_id, title, body)
    return nid


def next_follow_up(status: str, interview_at: str | None = None) -> str | None:
    if status == "interview" and interview_at:
        dt = parse_iso(interview_at)
        if dt:
            return (dt.replace(microsecond=0)).isoformat()
    days = FOLLOW_UP_DAYS.get(status)
    return iso_in(days=days) if days else None


def create(user_id: int, data: dict) -> dict:
    db = get_db()
    status = data.get("status") or "saved"
    now = now_iso()
    if data.get("job_id"):
        dup = db.fetchone("SELECT id FROM applications WHERE user_id = ? AND job_id = ?", (user_id, data["job_id"]))
        if dup:
            return update_status(user_id, dup["id"], status) if status != "saved" else get(user_id, dup["id"])
    if data.get("msot_job_id"):
        dup = db.fetchone("SELECT id FROM applications WHERE user_id = ? AND msot_job_id = ?", (user_id, data["msot_job_id"]))
        if dup:
            return get(user_id, dup["id"])
    aid = db.insert("applications", {
        "user_id": user_id, "job_id": data.get("job_id"), "msot_job_id": data.get("msot_job_id"), "title": data["title"][:200],
        "company": data["company"][:160], "url": data.get("url"), "source": data.get("source") or "manual",
        "location": data.get("location"), "status": status, "status_history": [{"status": status, "at": now}],
        "notes": data.get("notes"), "match_score": data.get("match_score"), "applied_at": now if status == "applied" else None,
        "next_follow_up_at": next_follow_up(status), "last_movement_at": now, "shared_report": int(bool(data.get("shared_report"))),
        "created_at": now, "updated_at": now,
    })
    return get(user_id, aid)


def get(user_id: int, app_id: int) -> dict | None:
    return get_db().fetchone("SELECT * FROM applications WHERE id = ? AND user_id = ?", (app_id, user_id))


def update_status(user_id: int, app_id: int, status: str, by: str = "student", note: str | None = None,
                  interview_at: str | None = None) -> dict | None:
    db = get_db()
    app = get(user_id, app_id)
    if not app or status not in STATUSES:
        return app
    now = now_iso()
    history = list(app["status_history"] or [])
    if app["status"] != status:
        history.append({"status": status, "at": now, "by": by, **({"note": note} if note else {})})
    fields = {"status": status, "status_history": history, "updated_at": now, "last_movement_at": now,
              "next_follow_up_at": next_follow_up(status, interview_at or app.get("interview_at"))}
    if status == "applied" and not app.get("applied_at"):
        fields["applied_at"] = now
    if interview_at:
        fields["interview_at"] = interview_at
    db.update("applications", app_id, fields)
    if by != "student" and app["status"] != status:
        notify(user_id, "application", f"{app['company']}: you're now '{LABELS[status]}' for {app['title']}",
               note or "The MSOT placement cell updated your application.", "/tracker", f"app:{app_id}:{status}")
    return get(user_id, app_id)


def board(user_id: int) -> dict:
    db = get_db()
    apps = db.fetchall("SELECT * FROM applications WHERE user_id = ? ORDER BY updated_at DESC", (user_id,))
    now = utcnow()
    columns = {s: [] for s in STATUSES}
    due, stale, moving = [], [], []
    for a in apps:
        columns[a["status"]].append(a)
        fu = parse_iso(a.get("next_follow_up_at"))
        if fu and fu <= now and a["status"] in ("applied", "shortlisted"):
            due.append(a)
        moved = parse_iso(a.get("last_movement_at"))
        if moved and (now - moved).days >= 14 and a["status"] in ("applied", "shortlisted"):
            stale.append(a)
        if moved and (now - moved).days <= 7 and a["status"] not in ("saved",):
            moving.append(a)
    counts = {s: len(v) for s, v in columns.items()}
    funnel = {"applied_or_later": sum(counts[s] for s in STATUSES[1:]),
              "responses": sum(counts[s] for s in ("shortlisted", "interview", "offer", "rejected"))}
    return {"columns": columns, "counts": counts, "due_follow_ups": due, "stale": stale, "recent_movement": moving,
            "funnel": funnel, "statuses": [{"key": s, "label": LABELS[s]} for s in STATUSES]}


def ics(user_id: int) -> str:
    rows = get_db().fetchall("SELECT * FROM applications WHERE user_id = ? AND interview_at IS NOT NULL", (user_id,))
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//OfferReady//Tracker//EN"]
    for r in rows:
        dt = parse_iso(r["interview_at"])
        if not dt:
            continue
        stamp = dt.strftime("%Y%m%dT%H%M%SZ")
        lines += ["BEGIN:VEVENT", f"UID:app-{r['id']}@offerready", f"DTSTAMP:{stamp}", f"DTSTART:{stamp}",
                  f"SUMMARY:Interview — {r['company']} ({r['title']})", f"URL:{r.get('url') or ''}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
