"""Chat copilot: the student talks to the app in plain language.

1. A deterministic router recognises the common things people type (GitHub/LeetCode/repo
   links, "my target role is…", achievements, "what should I fix first?", "find jobs") and
   acts immediately — instant, free, and reliable.
2. Everything else goes to the language model with read-only tools over the student's own
   data (readiness, reviews, jobs, applications) plus a few safe write tools.
Responses stream as text plus "cards" the UI renders (score, review, jobs, upload prompts).
"""
from __future__ import annotations

import json
import re
from typing import AsyncIterator

from ..db import get_db, now_iso
from ..llm.providers import chat, resolve, stream_chat
from ..skills import ROLES, role_from_text
from ..web import ApiError

HELP = ("I can review your **resume**, **LinkedIn**, **GitHub**, **projects** and **coding profiles**, run a **mock interview**, "
        "give you a **placement readiness score**, and find and track **jobs**.\n\nTry:\n"
        "• Upload your resume (PDF) with the 📎 button\n• \"My GitHub is github.com/yourname\"\n"
        "• \"leetcode.com/u/yourname\"\n• \"I want a backend developer internship in Bangalore\"\n"
        "• \"What should I fix first?\"\n• \"Find jobs for me\"")
ROLE_RE = re.compile(r"\b(?:target role|i want (?:to be|a|an)|looking for (?:a|an)?|aiming for|interested in|my role is|"
                     r"apply(?:ing)? for)\s+(?:a |an )?([a-z /+&().-]{3,60}?)(?:\s+(?:role|job|position|internship|intern))?"
                     r"(?:\s+in\s+([a-z ,]+))?(?:[.!?]|$)", re.I)
ACHIEVEMENT_RE = re.compile(r"\b(i (?:won|was|am|got|secured|ranked|cleared|led|organi[sz]ed|completed|earned|received|"
                            r"qualified|became|have been)|we won|hackathon|finalist|certif|rank(?:ed)? \d|prize|"
                            r"(?:lead|head|president|captain) of)\b", re.I)
CITIES = ["bangalore", "bengaluru", "hyderabad", "pune", "mumbai", "delhi", "noida", "gurgaon", "gurugram", "chennai",
          "kolkata", "ahmedabad", "remote", "jaipur", "kochi", "indore", "chandigarh"]


def _history(user_id: int, limit: int = 12) -> list[dict]:
    rows = get_db().fetchall("SELECT role, content FROM chat_messages WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit))
    return list(reversed(rows))


def save_message(user_id: int, role: str, content: str, cards: list | None = None) -> int:
    return get_db().insert("chat_messages", {"user_id": user_id, "role": role, "content": content[:8000], "cards": cards or [],
                                             "created_at": now_iso()})


def state_summary(user: dict) -> dict:
    from ..profile_service import profile_overview
    from ..readiness.score import compute

    r = compute(user["id"])
    ov = profile_overview(user["id"])
    return {
        "name": user.get("name"), "target_role": user.get("target_role"), "job_type": user.get("job_type"),
        "locations": user.get("target_locations"),
        "readiness": {"score": r["score"], "level": r["level"],
                      "components": {k: v.get("score") for k, v in r["components"].items()},
                      "top_actions": [{"title": a["title"], "gain": a["gain"], "detail": a["detail"][:220]} for a in r["top_actions"]]},
        "checklist": {c["key"]: c["done"] for c in ov["checklist"]},
    }


def readiness_card(user: dict) -> dict:
    from ..readiness.score import compute

    r = compute(user["id"])
    return {"type": "readiness", "data": {"score": r["score"], "level": r["level"], "potential": r["potential"],
                                          "top_actions": r["top_actions"][:5],
                                          "components": {k: {"score": v.get("score"), "weight": v["weight"], "label": v["label"]}
                                                         for k, v in r["components"].items()}}}


def jobs_card(user: dict, limit: int = 3) -> dict:
    from ..jobs.pipeline import search

    res = search(user, None, {}, 1, limit)
    return {"type": "jobs", "data": {"results": res.get("results", [])[:limit], "total": res.get("total", 0),
                                     "query": res.get("query"), "msot": len(res.get("msot", {}).get("eligible", []))}}


async def route(user: dict, text: str) -> tuple[str, list[dict]] | None:
    """Deterministic handling. Returns (reply, cards) or None to fall through to the model."""
    from .. import profile_service as ps

    t = text.strip()
    low = t.lower()
    uid = user["id"]
    cards: list[dict] = []
    replies: list[str] = []

    for m in re.finditer(r"(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9-]+)(?:/([A-Za-z0-9._-]+))?", t):
        owner, repo = m.group(1), m.group(2)
        if repo and repo.lower() not in ("", "repositories", "tab=repositories"):
            live = re.search(r"(https?://(?!(?:www\.)?github\.com)[^\s,]+)", t)
            res = ps.add_project(uid, repo.replace("-", " ").replace("_", " ").title(), f"https://github.com/{owner}/{repo}",
                                 live.group(1) if live else None)
            replies.append(f"Added project **{res['project']['name']}** — I'm cloning the repo to check the README, code, "
                           f"commits and secrets{', and testing the live link' if live else ''}.")
            cards.append({"type": "task", "data": {"task_id": res["task_id"], "label": f"Reviewing {res['project']['name']}"}})
            if not live:
                replies.append("If it's deployed, send me the live link too.")
        else:
            res = ps.add_github(uid, owner)
            replies.append(f"Got it — reviewing GitHub profile **@{res['username']}** (README, pins, activity, repos).")
            cards.append({"type": "task", "data": {"task_id": res["task_id"], "label": "Reviewing GitHub"}})
    for m in re.finditer(r"(?:https?://)?(?:www\.)?leetcode\.com/(?:u/)?([A-Za-z0-9_.-]+)", t):
        res = ps.add_coding(uid, "leetcode", m.group(1))
        replies.append(f"Added LeetCode **{m.group(1)}** — fetching your solved count, difficulty mix and contests.")
        cards.append({"type": "task", "data": {"task_id": res["task_id"], "label": "Checking LeetCode"}})
    for m in re.finditer(r"(?:https?://)?(?:www\.)?codeforces\.com/profile/([A-Za-z0-9_.-]+)", t):
        res = ps.add_coding(uid, "codeforces", m.group(1))
        replies.append(f"Added Codeforces **{m.group(1)}** (official API).")
        cards.append({"type": "task", "data": {"task_id": res["task_id"], "label": "Checking Codeforces"}})
    if re.search(r"linkedin\.com/in/", low):
        replies.append("For privacy and LinkedIn's terms I don't open LinkedIn pages. Please upload your profile PDF "
                       "(LinkedIn → your profile → **More → Save to PDF**) or paste the profile text.")
        cards.append({"type": "upload", "data": {"kind": "linkedin"}})
    if replies:
        return "\n\n".join(replies), cards

    live_only = re.fullmatch(r"(?:live(?: link)?(?: is)?:?\s*)?(https?://\S+)", t, re.I)
    if live_only:
        db = get_db()
        proj = db.fetchone("SELECT id, input FROM profile_sources WHERE user_id = ? AND kind = 'project' ORDER BY id DESC LIMIT 1", (uid,))
        if proj and not (proj["input"] or {}).get("live_url"):
            res = ps.update_project(uid, proj["id"], {"live_url": live_only.group(1)})
            return (f"Added the live link to **{proj['input'].get('name')}** — opening it on desktop and mobile now.",
                    [{"type": "task", "data": {"task_id": res["task_id"], "label": "Testing live link"}}])
        return ("Is this a project's live link? Tell me the project name and its GitHub repo, e.g. "
                "\"DevConnect github.com/me/devconnect live: " + live_only.group(1) + "\"", [])

    m = ROLE_RE.search(t)
    if m and not re.search(r"\b(job|jobs|find|search)\b.*\b(for me|now)\b", low):
        role_txt = m.group(1).strip(" .")
        if len(role_txt.split()) <= 6 and role_from_text(role_txt) != "sde" or re.search(r"\b(sde|software|developer|engineer)\b", role_txt, re.I):
            locs = [c.title() for c in CITIES if c in low]
            job_type = "internship" if re.search(r"intern", low) else ("fulltime" if re.search(r"full[- ]?time|job\b", low) else None)
            fields = {"target_role": role_txt.title()[:80]}
            if locs:
                fields["target_locations"] = locs
            if job_type:
                fields["job_type"] = job_type
            get_db().update("users", uid, fields)
            role_id = role_from_text(role_txt)
            core = ", ".join(ROLES[role_id]["core"][:5])
            return (f"Saved your target: **{fields['target_role']}**"
                    + (f" in {', '.join(locs)}" if locs else "") + (f" ({job_type})" if job_type else "") +
                    f". Recruiters for this role look for {core}. I'll use this for reviews, interview questions and job "
                    "matching.", [jobs_card({**user, **fields})])

    if ACHIEVEMENT_RE.search(t) and len(t.split()) >= 4 and not t.endswith("?"):
        res = ps.add_achievement(uid, t)
        return ("Added to your achievements. Tip: include the result (rank, prize, or 'finalist out of N teams') — "
                "it makes the line much stronger.", [{"type": "task", "data": {"task_id": res["task_id"], "label": "Updating achievements"}}])

    if re.search(r"\b(help|what can you do|how does this work)\b", low):
        return HELP, [{"type": "upload", "data": {"kind": "resume"}}]
    if re.search(r"\b(score|readiness|ready|fix first|improve|top actions|what should i (do|fix|work on))\b", low):
        card = readiness_card(user)
        d = card["data"]
        if not d["top_actions"]:
            return "Your profile is in great shape — nothing urgent to fix. Try a mock interview to keep sharp.", [card]
        first = d["top_actions"][0]
        return (f"Your placement readiness is **{d['score']:.0f}/100 — {d['level']}**. The biggest win right now: "
                f"**{first['title']}** (≈ +{first['gain']:.1f} points). {first['detail']}", [card])
    if re.search(r"\b(find|search|show|recommend)\b.*\b(jobs?|internships?|openings?|roles?)\b|^jobs?$", low):
        card = jobs_card(user, 3)
        n = card["data"]["total"]
        return (f"I found **{n}** matching openings" + (f" plus **{card['data']['msot']}** from the MSOT placement cell" if card['data']['msot'] else "")
                + ". Here are the best matches — open the Jobs tab for all of them and to edit the search query.", [card])
    if re.search(r"\b(mock interview|interview practice|practice interview|start (an )?interview)\b", low):
        return ("Let's do it. Choose 15 or 20 minutes and voice or text mode — questions will be based on your projects "
                "and target role.", [{"type": "interview", "data": {}}])
    if re.search(r"\b(review|check|analy[sz]e)\b.*\bresume\b|\bupload\b.*\bresume\b", low):
        return "Upload your resume as a PDF (DOCX also works) and I'll check it against the MSOT benchmark.", [
            {"type": "upload", "data": {"kind": "resume"}}]
    if re.search(r"\b(applications?|tracker|applied)\b", low) and re.search(r"\b(my|status|show|how many)\b", low):
        from ..tracker.applications import board

        b = board(uid)
        return (f"You have {b['counts']['applied']} applied, {b['counts']['shortlisted']} shortlisted, "
                f"{b['counts']['interview']} interviews and {b['counts']['offer']} offers. "
                f"{len(b['due_follow_ups'])} follow-ups are due.", [{"type": "applications", "data": {"counts": b["counts"]}}])
    if re.search(r"\bdelete (all )?my data\b|\bdelete my account\b", low):
        return ("You can delete everything we store about you from **Settings → Privacy → Delete my data**. "
                "It removes your files, reviews, interviews and applications permanently.", [])
    return None


TOOLS = [
    {"type": "function", "function": {"name": "get_readiness", "description": "The student's readiness score, components and top actions.",
                                      "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_review", "description": "Latest review of one area with failing checks and fixes.",
                                      "parameters": {"type": "object", "properties": {"kind": {"type": "string", "enum": [
                                          "resume", "linkedin", "github", "project", "coding", "achievements"]}}, "required": ["kind"]}}},
    {"type": "function", "function": {"name": "search_jobs", "description": "Best matching jobs for the student (optional boolean query).",
                                      "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "list_applications", "description": "The student's application tracker summary.",
                                      "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "set_target", "description": "Save the student's target role / locations / job type.",
                                      "parameters": {"type": "object", "properties": {"role": {"type": "string"},
                                                     "locations": {"type": "array", "items": {"type": "string"}},
                                                     "job_type": {"type": "string", "enum": ["internship", "fulltime", "both"]}}}}},
    {"type": "function", "function": {"name": "add_achievement", "description": "Record an achievement the student mentioned.",
                                      "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}},
]


async def run_tool(user: dict, name: str, args: dict) -> tuple[dict, dict | None]:
    from .. import profile_service as ps
    from ..pipelines import latest_review

    if name == "get_readiness":
        card = readiness_card(user)
        return card["data"], card
    if name == "get_review":
        r = latest_review(user["id"], args.get("kind", "resume"))
        if not r:
            return {"error": "No review yet for this area."}, None
        failing = [{"title": c["title"], "summary": c["summary"], "fixes": c["fixes"][:3]} for c in r["checks"]
                   if c["status"] in ("fail", "warn")][:8]
        return {"score": r["score"], "summary": r["summary"], "failing_checks": failing}, \
            {"type": "review", "data": {"kind": r["kind"], "score": r["score"], "summary": r["summary"], "review_id": r["id"]}}
    if name == "search_jobs":
        from ..jobs.pipeline import search

        res = search(user, args.get("query"), {}, 1, 5)
        brief = [{"title": x["job"]["title"], "company": x["job"]["company"], "match": x["match"],
                  "missing": x["missing_skills"]} for x in res.get("results", [])[:5]]
        return {"total": res.get("total"), "top": brief, "query": res.get("query")}, \
            {"type": "jobs", "data": {"results": res.get("results", [])[:3], "total": res.get("total", 0), "query": res.get("query")}}
    if name == "list_applications":
        from ..tracker.applications import board

        b = board(user["id"])
        return {"counts": b["counts"], "due_follow_ups": len(b["due_follow_ups"])}, {"type": "applications", "data": {"counts": b["counts"]}}
    if name == "set_target":
        fields = {}
        if args.get("role"):
            fields["target_role"] = str(args["role"])[:80]
        if args.get("locations"):
            fields["target_locations"] = [str(l)[:40] for l in args["locations"]][:6]
        if args.get("job_type") in ("internship", "fulltime", "both"):
            fields["job_type"] = args["job_type"]
        if fields:
            get_db().update("users", user["id"], fields)
        return {"saved": fields}, None
    if name == "add_achievement":
        try:
            ps.add_achievement(user["id"], args.get("text", ""))
            return {"saved": True}, None
        except ApiError as exc:
            return {"error": exc.message}, None
    return {"error": f"unknown tool {name}"}, None


SYSTEM = (
    "You are OfferReady, a placement-readiness copilot for engineering students at MSOT (India). Be warm, direct and "
    "specific. Use the tools to look at the student's real data before giving advice; never invent scores, companies or "
    "facts. Keep answers short (under 150 words) unless asked for detail; use bullet points for steps. If they ask for "
    "something the app does (reviews, interview, jobs), tell them where to click. Do not write their resume for them from "
    "scratch; improve what they have."
)


async def respond(user: dict, text: str) -> AsyncIterator[dict]:
    """Yields {"type": "delta", "text"} ... {"type": "cards", "cards"} ... {"type": "done", "message_id"}."""
    if not text.strip():
        yield {"type": "done", "message_id": None}
        return
    save_message(user["id"], "user", text)
    fresh_user = get_db().fetchone("SELECT * FROM users WHERE id = ?", (user["id"],))
    routed = await route(fresh_user, text)
    if routed:
        reply, cards = routed
        for chunk in re.findall(r"\S+\s*", reply):
            yield {"type": "delta", "text": chunk}
        if cards:
            yield {"type": "cards", "cards": cards}
        mid = save_message(user["id"], "assistant", reply, cards)
        yield {"type": "done", "message_id": mid}
        return

    cfg = resolve(fresh_user)
    cards: list[dict] = []
    state = state_summary(fresh_user)
    messages = [{"role": "system", "content": SYSTEM + "\n\nStudent snapshot (JSON): " + json.dumps(state, ensure_ascii=False)}]
    messages += [{"role": m["role"], "content": m["content"]} for m in _history(user["id"], 10)]
    if not cfg.is_mock:
        for _ in range(3):   # tool loop
            res = await chat(messages, feature="chat_tools", user=fresh_user, tools=TOOLS, temperature=0.3, max_tokens=500,
                             mock=lambda: "", cache=False)
            if not res.tool_calls:
                break
            messages.append({"role": "assistant", "content": res.text or None, "tool_calls": [
                {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])}}
                for tc in res.tool_calls]})
            for tc in res.tool_calls:
                output, card = await run_tool(fresh_user, tc["name"], tc["arguments"])
                if card:
                    cards.append(card)
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(output, ensure_ascii=False)[:6000]})

    def fallback() -> str:
        r = state["readiness"]
        if r["top_actions"]:
            a = r["top_actions"][0]
            return (f"I'm running in offline mode, so I can't answer free-form questions in detail. Here's what matters most "
                    f"for you right now: your readiness is {r['score']:.0f}/100 ({r['level']}), and the biggest improvement is "
                    f"**{a['title']}** (≈ +{a['gain']:.1f} points): {a['detail']}\n\n{HELP}")
        return HELP

    full = []
    async for chunk in stream_chat(messages, feature="chat", user=fresh_user, mock=fallback):
        full.append(chunk)
        yield {"type": "delta", "text": chunk}
    if cards:
        yield {"type": "cards", "cards": cards}
    mid = save_message(user["id"], "assistant", "".join(full), cards)
    yield {"type": "done", "message_id": mid}
