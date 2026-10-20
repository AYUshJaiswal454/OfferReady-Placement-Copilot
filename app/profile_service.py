"""Add / update / delete the student's profile data. Shared by the REST API and the chat copilot."""
from __future__ import annotations

import re

from .db import audit, get_db, now_iso
from .storage import delete_file, get_file_row, save_file
from .tasks import enqueue
from .web import ApiError

PDF_MAGIC = b"%PDF"
DOCX_MAGIC = b"PK\x03\x04"


def _source(user_id: int, kind: str, label: str, input_: dict, file_id: int | None = None, replace: bool = True) -> int:
    db = get_db()
    if replace:
        for old in db.fetchall("SELECT id, file_id FROM profile_sources WHERE user_id = ? AND kind = ?", (user_id, kind)):
            delete_source(user_id, old["id"], audit_it=False)
    sid = db.insert("profile_sources", {"user_id": user_id, "kind": kind, "label": label, "input": input_, "file_id": file_id,
                                        "status": "pending", "created_at": now_iso(), "updated_at": now_iso()})
    return sid


def upload_resume(user_id: int, filename: str, data: bytes, content_type: str, max_mb: int) -> dict:
    if len(data) > max_mb * 1024 * 1024:
        raise ApiError(413, f"File is larger than {max_mb} MB", "too_large")
    low = filename.lower()
    if data[:4] == PDF_MAGIC:
        kind_ok = True
    elif data[:4] == DOCX_MAGIC and low.endswith(".docx"):
        kind_ok = True
    else:
        kind_ok = False
    if not kind_ok:
        raise ApiError(415, "Please upload a PDF (recommended) or a DOCX file", "bad_type")
    f = save_file(user_id, "resume", filename, data, content_type)
    sid = _source(user_id, "resume", filename, {"filename": filename}, f["id"])
    task = enqueue("review_resume", {"source_id": sid}, user_id=user_id, dedupe_key=f"resume:{sid}")
    audit(user_id, "resume.upload", "source", sid, {"bytes": len(data)})
    return {"source_id": sid, "task_id": task}


def upload_linkedin(user_id: int, filename: str | None, data: bytes | None, text: str | None, photo: bool | None,
                    max_mb: int) -> dict:
    file_id = None
    if data:
        if len(data) > max_mb * 1024 * 1024:
            raise ApiError(413, f"File is larger than {max_mb} MB", "too_large")
        if data[:4] != PDF_MAGIC:
            raise ApiError(415, "Upload the PDF from LinkedIn → Profile → More → Save to PDF, or paste your profile text",
                           "bad_type")
        file_id = save_file(user_id, "linkedin", filename or "linkedin.pdf", data, "application/pdf")["id"]
    elif not text or len(text.strip()) < 40:
        raise ApiError(400, "Paste the text of your LinkedIn profile (at least a few lines) or upload the PDF export", "empty")
    sid = _source(user_id, "linkedin", "LinkedIn", {"text": (text or "")[:30000], "photo": photo}, file_id)
    task = enqueue("review_linkedin", {"source_id": sid}, user_id=user_id, dedupe_key=f"linkedin:{sid}")
    return {"source_id": sid, "task_id": task}


def set_linkedin_photo(user_id: int, has_photo: bool, detected: bool = False) -> dict | None:
    db = get_db()
    src = db.fetchone("SELECT * FROM profile_sources WHERE user_id = ? AND kind = 'linkedin' ORDER BY id DESC LIMIT 1", (user_id,))
    if not src:
        return None
    inp = dict(src["input"] or {})
    inp["photo"] = has_photo
    inp["photo_detected"] = detected
    db.update("profile_sources", src["id"], {"input": inp, "updated_at": now_iso()})
    task = enqueue("review_linkedin", {"source_id": src["id"]}, user_id=user_id, dedupe_key=f"linkedin:{src['id']}:photo")
    return {"source_id": src["id"], "task_id": task}


def detect_face(image_bytes: bytes) -> bool:
    """True if a face is visible in a profile screenshot (OpenCV Haar cascade, runs locally)."""
    try:
        import cv2  # type: ignore
        import numpy as np

        img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return False
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        faces = cascade.detectMultiScale(img, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
        return len(faces) > 0
    except Exception:
        return False


def add_github(user_id: int, username: str) -> dict:
    from .review.github_review import GitHubError, parse_username

    try:
        handle = parse_username(username)
    except GitHubError as exc:
        raise ApiError(400, str(exc), "bad_username")
    sid = _source(user_id, "github", f"@{handle}", {"username": handle})
    task = enqueue("review_github", {"source_id": sid}, user_id=user_id, dedupe_key=f"github:{sid}")
    return {"source_id": sid, "task_id": task, "username": handle}


def add_coding(user_id: int, platform: str, username: str | None, manual: dict | None = None) -> dict:
    from .review.coding_review import CodingProfileError, parse_handle

    if platform not in ("leetcode", "codeforces"):
        raise ApiError(400, "Supported platforms: leetcode, codeforces", "bad_platform")
    handle = None
    if username:
        try:
            handle = parse_handle(username, platform)
        except CodingProfileError as exc:
            raise ApiError(400, str(exc).replace("PERMANENT:", "").strip(), "bad_username")
    if not handle and not manual:
        raise ApiError(400, "Give a username or enter your numbers manually", "empty")
    clean_manual = None
    if manual:
        clean_manual = {k: max(0, int(manual.get(k) or 0)) for k in ("solved", "easy", "medium", "hard", "contests", "rating")}
    sid = _source(user_id, platform, f"{platform}: {handle or 'manual'}", {"username": handle, "manual": clean_manual})
    task = enqueue("review_coding", {"user_id": user_id}, user_id=user_id, dedupe_key=f"coding:{user_id}")
    return {"source_id": sid, "task_id": task}


def normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    if not url:
        return None
    if not re.match(r"https?://", url, re.I):
        url = "https://" + url
    return url[:500]


def add_project(user_id: int, name: str, repo_url: str | None, live_url: str | None, description: str = "",
                tech: list[str] | None = None) -> dict:
    from .skills import extract_skills

    name = (name or "").strip()[:80]
    if not name and repo_url:
        name = repo_url.rstrip("/").split("/")[-1].replace("-", " ").replace("_", " ").title()
    if not name:
        raise ApiError(400, "Give the project a name", "empty")
    if not repo_url and not live_url:
        raise ApiError(400, "Add at least a GitHub repo link or a live link", "empty")
    tech = tech or extract_skills(description, technical_context=False)
    proj = {"name": name, "repo_url": normalize_url(repo_url), "live_url": normalize_url(live_url),
            "description": (description or "")[:1500], "tech": tech[:12]}
    db = get_db()
    same = next((r for r in db.fetchall("SELECT id, input FROM profile_sources WHERE user_id = ? AND kind = 'project'", (user_id,))
                 if ((r["input"] or {}).get("name") or "").strip().lower() == name.lower()), None)
    if same:
        # Adding a project that already exists (e.g. one picked up from the resume) replaces it instead of duplicating it.
        delete_source(user_id, same["id"], audit_it=False)
    sid = _source(user_id, "project", name, proj, replace=False)
    task = enqueue("review_project", {"source_id": sid}, user_id=user_id, dedupe_key=f"project:{sid}")
    return {"source_id": sid, "task_id": task, "project": proj}


def update_project(user_id: int, source_id: int, fields: dict) -> dict:
    db = get_db()
    src = db.fetchone("SELECT * FROM profile_sources WHERE id = ? AND user_id = ? AND kind = 'project'", (source_id, user_id))
    if not src:
        raise ApiError(404, "Project not found", "not_found")
    proj = dict(src["input"] or {})
    for k in ("name", "description"):
        if k in fields and fields[k] is not None:
            proj[k] = str(fields[k])[:1500]
    for k in ("repo_url", "live_url"):
        if k in fields:
            proj[k] = normalize_url(fields[k])
    if "tech" in fields and fields["tech"] is not None:
        proj["tech"] = [str(t)[:40] for t in fields["tech"]][:12]
    db.update("profile_sources", source_id, {"input": proj, "label": proj.get("name"), "status": "pending", "updated_at": now_iso()})
    task = enqueue("review_project", {"source_id": source_id}, user_id=user_id, dedupe_key=f"project:{source_id}:{now_iso()}")
    return {"source_id": source_id, "task_id": task}


def add_achievement(user_id: int, text: str, category: str | None = None) -> dict:
    text = (text or "").strip()
    if len(text) < 6:
        raise ApiError(400, "Describe the achievement in a few words", "empty")
    sid = _source(user_id, "achievement", text[:60], {"text": text[:400], "category": category}, replace=False)
    get_db().update("profile_sources", sid, {"status": "ready"})
    task = enqueue("review_achievements", {"user_id": user_id}, user_id=user_id, dedupe_key=f"ach:{user_id}")
    return {"source_id": sid, "task_id": task}


def delete_source(user_id: int, source_id: int, audit_it: bool = True) -> bool:
    db = get_db()
    src = db.fetchone("SELECT * FROM profile_sources WHERE id = ? AND user_id = ?", (source_id, user_id))
    if not src:
        return False
    if src.get("file_id"):
        row = get_file_row(src["file_id"])
        if row:
            delete_file(row)
    reviews = db.fetchall("SELECT id, data FROM reviews WHERE source_id = ? AND user_id = ?", (source_id, user_id))
    for r in reviews:
        data = r.get("data") or {}
        for fid in list(data.get("page_files") or []) + list((data.get("screenshots") or {}).values()):
            row = get_file_row(fid)
            if row and row["user_id"] == user_id:
                delete_file(row)
    db.execute("DELETE FROM reviews WHERE source_id = ? AND user_id = ?", (source_id, user_id))
    db.execute("DELETE FROM profile_sources WHERE id = ?", (source_id,))
    if src["kind"] in ("leetcode", "codeforces"):
        enqueue("review_coding", {"user_id": user_id}, user_id=user_id, dedupe_key=f"coding:{user_id}")
    if src["kind"] == "achievement":
        enqueue("review_achievements", {"user_id": user_id}, user_id=user_id, dedupe_key=f"ach:{user_id}")
    enqueue("recompute_readiness", {"user_id": user_id}, user_id=user_id, dedupe_key=f"readiness:{user_id}")
    if audit_it:
        audit(user_id, "source.delete", "source", source_id, {"kind": src["kind"]})
    return True


def profile_overview(user_id: int) -> dict:
    db = get_db()
    sources = db.fetchall("SELECT id, kind, label, input, status, error, extracted, file_id, created_at, updated_at "
                          "FROM profile_sources WHERE user_id = ? ORDER BY id", (user_id,))
    by_kind: dict[str, list] = {}
    for s in sources:
        inp = dict(s["input"] or {})
        if s["kind"] != "achievement":
            inp.pop("text", None)   # pasted LinkedIn text can be long; the UI doesn't need it here
        by_kind.setdefault(s["kind"], []).append({**{k: s[k] for k in ("id", "kind", "label", "status", "error", "created_at",
                                                                      "updated_at")}, "input": inp, "extracted": s["extracted"]})
    checklist = [
        {"key": "resume", "label": "Resume", "done": bool(by_kind.get("resume"))},
        {"key": "linkedin", "label": "LinkedIn", "done": bool(by_kind.get("linkedin"))},
        {"key": "github", "label": "GitHub", "done": bool(by_kind.get("github"))},
        {"key": "coding", "label": "LeetCode / Codeforces", "done": bool(by_kind.get("leetcode") or by_kind.get("codeforces"))},
        {"key": "projects", "label": "Projects", "done": len(by_kind.get("project", [])) >= 2},
        {"key": "achievements", "label": "Achievements", "done": bool(by_kind.get("achievement")) or bool(
            ((by_kind.get("resume") or [{}])[0].get("extracted") or {}).get("achievements"))},
        {"key": "interview", "label": "Mock interview", "done": bool(db.fetchone(
            "SELECT id FROM interviews WHERE user_id = ? AND status = 'completed'", (user_id,)))},
    ]
    suggestions = []
    resume = (by_kind.get("resume") or [None])[0]
    if resume and resume.get("extracted"):
        links = resume["extracted"].get("links", [])
        gh = next((l["url"] for l in links if l["kind"] == "github_profile"), None)
        lc = next((l["url"] for l in links if l["kind"] == "leetcode"), None)
        if gh and not by_kind.get("github"):
            suggestions.append({"kind": "github", "value": gh.rstrip("/").split("/")[-1], "text": f"Found GitHub {gh} in your resume"})
        if lc and not by_kind.get("leetcode"):
            suggestions.append({"kind": "leetcode", "value": lc.rstrip("/").split("/")[-1], "text": f"Found LeetCode {lc} in your resume"})
    return {"sources": by_kind, "checklist": checklist, "suggestions": suggestions,
            "completeness": round(sum(c["done"] for c in checklist) / len(checklist), 2)}
