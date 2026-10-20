"""Prompts for the parts of a review that are written (never scored) by a language model.

Rule: the model may rephrase and explain, but must not invent facts or numbers. Unknown
numbers become [placeholders] the student fills in. Each function has a deterministic
fallback so the product works fully offline.
"""
from __future__ import annotations

import json
import re

from .providers import chat

PROMPT_VERSION = "2026.10.1"
SYSTEM_COACH = (
    "You are a placement coach for Indian engineering students applying to tech internships and jobs. "
    "You write specific, concrete, honest suggestions. Never invent facts, companies, numbers or results that are not "
    "in the student's text; when a number would help but is unknown, write a placeholder in square brackets such as "
    "[N users] or [X% faster]. Use simple, professional English."
)


async def rewrite_bullets(bullets: list[dict], role: str | None, user: dict | None) -> list[dict]:
    """bullets: [{text, suggestion}] (suggestion = deterministic template). Returns [{text, rewrite}]."""
    if not bullets:
        return []
    items = [{"id": i, "text": b["text"]} for i, b in enumerate(bullets[:10])]

    def fallback():
        return {"rewrites": [{"id": i, "rewrite": b.get("suggestion") or b["text"]} for i, b in enumerate(bullets[:10])]}

    prompt = (
        f"Target role: {role or 'Software Engineer'}.\n"
        "Rewrite each resume bullet so it starts with a strong past-tense action verb, says what was built/done, with what "
        "technology, and the measurable result. Keep every fact from the original; do not add tools or results that are not "
        "there — use [placeholders] for unknown numbers. Max 30 words each.\n"
        'Return JSON: {"rewrites": [{"id": <id>, "rewrite": "<text>"}]}\n\n'
        f"Bullets: {json.dumps(items, ensure_ascii=False)}"
    )
    res = await chat([{"role": "system", "content": SYSTEM_COACH}, {"role": "user", "content": prompt}],
                     feature="resume_rewrite", user=user, json_mode=True, mock=fallback, max_tokens=900)
    data = res.data if isinstance(res.data, dict) else fallback()
    by_id = {r.get("id"): r.get("rewrite") for r in data.get("rewrites", []) if isinstance(r, dict)}
    out = []
    for i, b in enumerate(bullets[:10]):
        rw = by_id.get(i) or b.get("suggestion") or b["text"]
        out.append({"text": b["text"], "rewrite": rw.strip(), "page": b.get("page"), "bbox": b.get("bbox"),
                    "source": res.provider})
    return out


async def polish_linkedin(rewrites: dict, profile: dict, ctx: dict, user: dict | None) -> dict:
    """Improve the deterministic headline/About drafts with the model (same facts, better wording)."""
    def fallback():
        return rewrites

    facts = {
        "name": profile.get("name"), "current_headline": profile.get("headline"), "current_about": (profile.get("about") or "")[:1500],
        "target_role": ctx.get("target_role"), "skills": (ctx.get("resume") or {}).get("skills", [])[:15],
        "projects": [p.get("title") for p in (ctx.get("resume") or {}).get("projects", [])[:3]],
        "experience": [e.get("title") for e in (ctx.get("resume") or {}).get("experience", [])[:2]],
        "draft_headlines": rewrites.get("headline"), "draft_about": rewrites.get("about"),
    }
    prompt = (
        "Improve these LinkedIn drafts for the student. Use only the facts given. Headline: max 220 characters, format "
        "'Role | 3 skills | one proof'. About: 4 short paragraphs, first person, under 1,200 characters, ends with what they "
        'are looking for. Return JSON: {"headline": ["...", "...", "..."], "about": "..."}\n\n'
        f"Facts: {json.dumps(facts, ensure_ascii=False)}"
    )
    res = await chat([{"role": "system", "content": SYSTEM_COACH}, {"role": "user", "content": prompt}],
                     feature="linkedin_rewrite", user=user, json_mode=True, mock=fallback, max_tokens=900)
    data = res.data if isinstance(res.data, dict) else rewrites
    heads = [h for h in data.get("headline", []) if isinstance(h, str) and 10 < len(h) <= 240] or rewrites.get("headline")
    about = data.get("about") if isinstance(data.get("about"), str) and len(data["about"]) > 80 else rewrites.get("about")
    return {**rewrites, "headline": heads[:3], "about": about, "source": res.provider}


async def review_code(name: str, excerpts: list[tuple[str, str]], user: dict | None) -> dict | None:
    """Ask the model to read the main files. Returns {summary, comments:[{file,line,severity,issue,suggestion}]}."""
    if not excerpts:
        return None

    def fallback():
        return None

    files = "\n\n".join(f"=== {path} ===\n{code}" for path, code in excerpts)[:24000]
    prompt = (
        f"Project: {name}. Review these files like a senior engineer interviewing a fresher. Comment only on real, "
        "specific issues you can point to by file and line: readability, structure, error handling, security, and obvious "
        "bugs. Max 6 comments, most important first. Also give a 2-sentence overall summary.\n"
        'Return JSON: {"summary": "...", "comments": [{"file": "...", "line": 12, "severity": "high|medium|low", '
        '"issue": "...", "suggestion": "..."}]}\n\n' + files
    )
    res = await chat([{"role": "system", "content": "You are a precise code reviewer. Never invent code that is not shown."},
                      {"role": "user", "content": prompt}], feature="code_review", user=user, json_mode=True, smart=True,
                     mock=fallback, max_tokens=1200)
    if not isinstance(res.data, dict):
        return None
    comments = [c for c in res.data.get("comments", []) if isinstance(c, dict) and c.get("issue")][:6]
    shown = {p for p, _ in excerpts}
    comments = [c for c in comments if c.get("file") in shown]   # drop hallucinated file names
    return {"summary": str(res.data.get("summary", ""))[:500], "comments": comments, "model": res.model}


async def narrative_summary(kind: str, review: dict, user: dict | None) -> str:
    """Two friendly sentences on top of the review (optional polish)."""
    failing = [c for c in review.get("checks", []) if c.get("status") in ("fail", "warn")]
    base = review.get("summary", "")

    def fallback():
        return base

    if not failing:
        return base
    brief = [{"check": c["title"], "summary": c["summary"], "fix": (c.get("fixes") or [""])[0][:200]} for c in failing[:5]]
    prompt = (f"Write a 2-sentence summary of this {kind} review for the student: what is good, and the single most "
              f"important fix first. Score {review.get('score')}/100. Use only these facts: {json.dumps(brief, ensure_ascii=False)}")
    res = await chat([{"role": "system", "content": SYSTEM_COACH}, {"role": "user", "content": prompt}],
                     feature=f"{kind}_summary", user=user, mock=fallback, max_tokens=220)
    text = re.sub(r"\s+", " ", res.text).strip()
    return text if 20 < len(text) < 700 else base
