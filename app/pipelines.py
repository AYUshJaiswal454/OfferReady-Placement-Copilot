"""Background task handlers: every review runs here, never inside a web request."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import shutil
import time
import subprocess
import tempfile
from pathlib import Path

from starlette.concurrency import run_in_threadpool

from .config import get_settings
from .db import get_db, iso_in, now_iso
from .storage import read_file, save_file
from .tasks import enqueue, handler, schedule, set_progress

log = logging.getLogger("offerready.pipelines")


# ----------------------------------------------------------------------------- helpers
def user_row(user_id: int) -> dict:
    return get_db().fetchone("SELECT * FROM users WHERE id = ?", (user_id,))


def source_row(source_id: int) -> dict | None:
    return get_db().fetchone("SELECT * FROM profile_sources WHERE id = ?", (source_id,))


def latest_review(user_id: int, kind: str, source_id: int | None = None) -> dict | None:
    if source_id:
        return get_db().fetchone("SELECT * FROM reviews WHERE user_id = ? AND kind = ? AND source_id = ? ORDER BY id DESC LIMIT 1",
                                 (user_id, kind, source_id))
    return get_db().fetchone("SELECT * FROM reviews WHERE user_id = ? AND kind = ? ORDER BY id DESC LIMIT 1", (user_id, kind))


def save_review(user_id: int, kind: str, source_id: int | None, result: dict, input_hash: str = "") -> int:
    data = {k: v for k, v in result.items() if k not in ("checks", "score", "summary", "rewrites", "benchmark_version")}
    review_id = get_db().insert("reviews", {
        "user_id": user_id, "kind": kind, "source_id": source_id, "benchmark_version": result.get("benchmark_version", ""),
        "score": float(result["score"]), "checks": result["checks"], "summary": result.get("summary", ""),
        "rewrites": result.get("rewrites") or {}, "data": data, "input_hash": input_hash, "created_at": now_iso(),
    })
    enqueue("recompute_readiness", {"user_id": user_id}, user_id=user_id, dedupe_key=f"readiness:{user_id}")
    return review_id


def mark_source(source_id: int, status: str, error: str | None = None, extracted: dict | None = None) -> None:
    data = {"status": status, "error": error, "updated_at": now_iso()}
    if extracted is not None:
        data["extracted"] = extracted
    get_db().update("profile_sources", source_id, data)


def resume_context(user: dict) -> dict:
    """Facts other reviews reuse: resume extraction, coding stats, target role."""
    db = get_db()
    resume = db.fetchone("SELECT extracted FROM profile_sources WHERE user_id = ? AND kind = 'resume' AND status = 'ready' "
                         "ORDER BY id DESC LIMIT 1", (user["id"],))
    coding = latest_review(user["id"], "coding")
    lc = None
    if coding:
        for p in (coding.get("data") or {}).get("extracted", {}).get("profiles", []):
            if p.get("platform") == "leetcode":
                lc = p.get("solved")
    return {
        "target_role": user.get("target_role"), "resume": (resume or {}).get("extracted") or None, "leetcode_solved": lc,
        "name": user.get("name"), "email": user.get("email"), "branch": user.get("branch"), "batch_year": user.get("batch_year"),
        "job_type": user.get("job_type"), "college": "MSOT",
    }


def docx_to_pdf(data: bytes) -> bytes | None:
    """Convert DOCX to PDF with LibreOffice when available (layout checks need real pages)."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "resume.docx"
        src.write_bytes(data)
        try:
            subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", tmp, str(src)], capture_output=True,
                           timeout=90, env={"HOME": tmp, "PATH": "/usr/bin:/bin:/usr/local/bin"})
        except Exception:
            return None
        out = Path(tmp) / "resume.pdf"
        return out.read_bytes() if out.exists() else None


# ----------------------------------------------------------------------------- resume
@handler("review_resume")
async def review_resume_task(task: dict) -> dict:
    from .intake.resume_parser import parse_resume_pdf, render_pages
    from .llm.features import rewrite_bullets
    from .review.project_review import project_from_resume_entry
    from .review.resume_checks import review_resume

    sid = task["payload"]["source_id"]
    src = source_row(sid)
    if not src:
        return {"skipped": "source deleted"}
    user = user_row(src["user_id"])
    file_row = get_db().fetchone("SELECT * FROM files WHERE id = ?", (src["file_id"],))
    raw = read_file(file_row)
    set_progress(task["id"], 10, "Reading your resume")
    pdf = raw
    note = None
    if file_row["filename"].lower().endswith(".docx"):
        pdf = await run_in_threadpool(docx_to_pdf, raw)
        if pdf is None:
            mark_source(sid, "error", "DOCX conversion is unavailable on this server; please upload a PDF.")
            return {"error": "docx"}
        note = "Converted from DOCX — Word may lay it out slightly differently; export a PDF for the most accurate check."
    try:
        parsed = await run_in_threadpool(parse_resume_pdf, pdf)
    except Exception as exc:
        mark_source(sid, "error", f"Could not read this PDF ({type(exc).__name__}). Try re-exporting it.")
        return {"error": str(exc)}
    set_progress(task["id"], 45, "Checking the benchmark")
    result = await run_in_threadpool(review_resume, parsed, file_row["filename"], user.get("target_role"))
    if note:
        result["warnings"].append(note)
    pages = await run_in_threadpool(render_pages, pdf)
    page_files = [save_file(user["id"], "resume_page", f"page{i + 1}.png", png, "image/png")["id"] for i, png in enumerate(pages)]
    result["page_files"] = page_files
    set_progress(task["id"], 70, "Writing suggested rewrites")
    try:
        result["rewrites"] = {"bullets": await rewrite_bullets(result["weak_bullets"], user.get("target_role"), user)}
    except Exception:
        log.exception("bullet rewrites failed")
        result["rewrites"] = {"bullets": [{"text": b["text"], "rewrite": b["suggestion"], "page": b["page"], "bbox": b["bbox"]}
                                          for b in result["weak_bullets"]]}
    mark_source(sid, "ready", None, result["extracted"])
    review_id = save_review(user["id"], "resume", sid, result, hashlib.sha256(pdf).hexdigest())
    # Projects with links found in the resume become reviewable project entries (only if the student has none yet).
    db = get_db()
    existing = db.fetchall("SELECT input FROM profile_sources WHERE user_id = ? AND kind = 'project'", (user["id"],))
    known_names = {(e["input"] or {}).get("name", "").lower() for e in existing}
    created = 0
    for entry in result["extracted"].get("projects", [])[:4]:
        proj = project_from_resume_entry(entry)
        if not proj["name"] or proj["name"].lower() in known_names or not (proj["repo_url"] or proj["live_url"]):
            continue
        new_id = db.insert("profile_sources", {
            "user_id": user["id"], "kind": "project", "label": proj["name"], "input": {**proj, "from_resume": True},
            "status": "pending", "created_at": now_iso(), "updated_at": now_iso()})
        enqueue("review_project", {"source_id": new_id}, user_id=user["id"], dedupe_key=f"project:{new_id}")
        created += 1
    # GitHub/LeetCode usernames found in the resume links are offered (not auto-added) in the UI.
    enqueue("review_achievements", {"user_id": user["id"]}, user_id=user["id"], dedupe_key=f"ach:{user['id']}")
    return {"review_id": review_id, "score": result["score"], "projects_created": created}


# ----------------------------------------------------------------------------- linkedin
@handler("review_linkedin")
async def review_linkedin_task(task: dict) -> dict:
    from .intake.linkedin_parser import parse_linkedin_pdf, parse_linkedin_text
    from .llm.features import polish_linkedin
    from .review.linkedin_checks import review_linkedin

    sid = task["payload"]["source_id"]
    src = source_row(sid)
    if not src:
        return {"skipped": "source deleted"}
    user = user_row(src["user_id"])
    inp = src["input"] or {}
    if src["file_id"]:
        raw = read_file(get_db().fetchone("SELECT * FROM files WHERE id = ?", (src["file_id"],)))
        profile = await run_in_threadpool(parse_linkedin_pdf, raw)
    else:
        profile = parse_linkedin_text(inp.get("text", ""))
    ctx = resume_context(user)
    ctx["photo"] = inp.get("photo")
    ctx["photo_detected"] = inp.get("photo_detected")
    result = await run_in_threadpool(review_linkedin, profile, ctx)
    set_progress(task["id"], 60, "Polishing your headline and About")
    try:
        result["rewrites"] = await polish_linkedin(result["rewrites"], profile.to_dict(), ctx, user)
    except Exception:
        log.exception("linkedin polish failed")
    mark_source(sid, "ready", None, profile.to_dict())
    review_id = save_review(user["id"], "linkedin", sid, result)
    return {"review_id": review_id, "score": result["score"]}


# ----------------------------------------------------------------------------- github profile
@handler("review_github")
async def review_github_task(task: dict) -> dict:
    from .review.github_review import GitHubError, fetch_profile, parse_username, review_github_profile

    sid = task["payload"]["source_id"]
    src = source_row(sid)
    if not src:
        return {"skipped": "source deleted"}
    user = user_row(src["user_id"])
    try:
        username = parse_username((src["input"] or {}).get("username", ""))
        data = await fetch_profile(username)
    except GitHubError as exc:
        msg = str(exc).replace("PERMANENT:", "").strip()
        if "PERMANENT" in str(exc) or "doesn't look like" in str(exc):
            mark_source(sid, "error", msg)
            return {"error": msg}
        raise
    except Exception as exc:
        mark_source(sid, "error", f"Could not reach GitHub ({type(exc).__name__}); we'll retry.")
        raise
    result = review_github_profile(data, resume_context(user))
    mark_source(sid, "ready", None, result["extracted"])
    review_id = save_review(user["id"], "github", sid, result)
    return {"review_id": review_id, "score": result["score"]}


# ----------------------------------------------------------------------------- project (repo + live link)
@handler("review_project")
async def review_project_task(task: dict) -> dict:
    from .llm.features import review_code
    from .review.github_review import parse_repo
    from .review.livelink import check_live_link
    from .review.project_review import review_project
    from .review.repo_analyzer import analyze_repo, clone_repo, read_excerpt

    sid = task["payload"]["source_id"]
    src = source_row(sid)
    if not src:
        return {"skipped": "source deleted"}
    user = user_row(src["user_id"])
    proj = dict(src["input"] or {})
    repo_result, repo_error, live = None, None, None
    workdir = get_settings().work_dir / f"task{task['id']}"
    try:
        if proj.get("repo_url"):
            parsed = parse_repo(proj["repo_url"])
            if not parsed:
                repo_error = "That is not a GitHub repository URL (expected github.com/<user>/<repo>)."
            else:
                set_progress(task["id"], 15, "Cloning the repository")
                ok, err = await run_in_threadpool(clone_repo, f"https://github.com/{parsed[0]}/{parsed[1]}.git", workdir / "repo")
                if ok:
                    set_progress(task["id"], 35, "Analysing code, commits and secrets")
                    repo_result = await run_in_threadpool(analyze_repo, workdir / "repo", parsed[0])
                    excerpts = [(f, read_excerpt(workdir / "repo", f)) for f in repo_result["code"]["main_files"]]
                    try:
                        repo_result["llm_review"] = await review_code(proj.get("name", parsed[1]), excerpts, user)
                    except Exception:
                        log.exception("LLM code review failed")
                    if not proj.get("live_url"):
                        lives = repo_result["readme"].get("live_links") or []
                        if lives:
                            proj["live_url"] = lives[0]
                            proj["live_from_readme"] = True
                else:
                    repo_error = err
        if proj.get("live_url"):
            set_progress(task["id"], 70, "Opening the live link (desktop and mobile)")
            claims = {"name": proj.get("name"), "description": proj.get("description"), "tech": proj.get("tech"),
                      "readme_intro": (repo_result or {}).get("readme", {}).get("excerpt", "")[:600]}
            try:
                live = await asyncio.wait_for(check_live_link(proj["live_url"], claims), timeout=120)
            except Exception as exc:
                live = {"engine": "none", "desktop": {"error": f"Live check failed: {type(exc).__name__}"}, "mobile": {"skipped": True}}
        result = review_project(proj, repo_result, live, repo_error)
        shots = {}
        for key in ("desktop", "mobile"):
            png = ((live or {}).get(key) or {}).get("screenshot")
            if png:
                shots[key] = save_file(user["id"], "screenshot", f"{key}.jpg", png, "image/jpeg")["id"]
        result["screenshots"] = shots
        result["repo"] = {"error": repo_error, "readme": (repo_result or {}).get("readme", {}).get("path"),
                          "languages": (repo_result or {}).get("code", {}).get("languages"),
                          "ai_review": (repo_result or {}).get("llm_review")}
        get_db().update("profile_sources", sid, {"input": proj, "updated_at": now_iso()})
        mark_source(sid, "ready" if not repo_error or live else "error", repo_error,
                    {"score": result["score"], "live": result.get("live"), "languages": result["repo"]["languages"]})
        review_id = save_review(user["id"], "project", sid, result)
        return {"review_id": review_id, "score": result["score"]}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ----------------------------------------------------------------------------- coding + achievements
@handler("review_coding")
async def review_coding_task(task: dict) -> dict:
    from .review.coding_review import CodingProfileError, fetch_codeforces, fetch_leetcode, parse_handle, review_coding

    user_id = task["payload"]["user_id"]
    rows = get_db().fetchall("SELECT * FROM profile_sources WHERE user_id = ? AND kind IN ('leetcode', 'codeforces')", (user_id,))
    profiles = []
    for src in rows:
        inp = src["input"] or {}
        if inp.get("manual"):
            stats = {"platform": src["kind"], "username": inp.get("username") or "manual", **inp["manual"], "manual": True}
            stats.setdefault("active_days_90", None)
            profiles.append(stats)
            mark_source(src["id"], "ready", None, stats)
            continue
        try:
            handle = parse_handle(inp.get("username", ""), src["kind"])
            stats = await (fetch_leetcode(handle) if src["kind"] == "leetcode" else fetch_codeforces(handle))
            profiles.append(stats)
            mark_source(src["id"], "ready", None, stats)
        except CodingProfileError as exc:
            mark_source(src["id"], "error", str(exc).replace("PERMANENT:", "").strip() +
                        " You can enter your numbers manually instead.")
        except Exception as exc:
            mark_source(src["id"], "error", f"Could not reach {src['kind']} ({type(exc).__name__}). "
                                            "You can enter your numbers manually.")
    result = review_coding(profiles)
    review_id = save_review(user_id, "coding", None, result)
    return {"review_id": review_id, "score": result["score"]}


@handler("review_achievements")
def review_achievements_task(task: dict) -> dict:
    from .review.coding_review import review_achievements

    user_id = task["payload"]["user_id"]
    db = get_db()
    items: list[str] = []
    resume = db.fetchone("SELECT extracted FROM profile_sources WHERE user_id = ? AND kind = 'resume' AND status = 'ready' "
                         "ORDER BY id DESC LIMIT 1", (user_id,))
    if resume:
        items += (resume["extracted"] or {}).get("achievements", [])
        items += (resume["extracted"] or {}).get("certifications", [])
    for row in db.fetchall("SELECT input FROM profile_sources WHERE user_id = ? AND kind = 'achievement'", (user_id,)):
        text = (row["input"] or {}).get("text")
        if text and text not in items:
            items.append(text)
    if not items and not resume:
        return {"skipped": "nothing to review"}
    result = review_achievements(items)
    review_id = save_review(user_id, "achievements", None, result)
    return {"review_id": review_id, "score": result["score"]}


@handler("recompute_readiness")
def recompute_readiness_task(task: dict) -> dict:
    from .readiness.score import snapshot

    result = snapshot(task["payload"]["user_id"])
    return {"score": result["score"], "level": result["level"]}


@handler("cleanup")
def cleanup_task(task: dict) -> dict:
    work = get_settings().work_dir
    removed = 0
    cutoff = time.time() - 2 * 3600          # never touch a clone a running review may still be using
    for p in work.iterdir():
        try:
            if p.stat().st_mtime < cutoff:
                shutil.rmtree(p, ignore_errors=True)
                removed += 1
        except OSError:
            pass
    get_db().execute("DELETE FROM tasks WHERE status IN ('done', 'failed') AND finished_at < ?", (iso_in(days=-14),))
    get_db().execute("DELETE FROM http_cache WHERE fetched_at < ?", (iso_in(days=-3),))
    return {"removed_workdirs": removed}


schedule("cleanup", 6 * 3600, "cleanup")

# Interview scoring, job crawling and reminders register their handlers on import.
from .interview import pipeline as _interview_pipeline  # noqa: E402,F401
from .jobs import pipeline as _jobs_pipeline  # noqa: E402,F401
from .tracker import reminders as _reminders  # noqa: E402,F401
