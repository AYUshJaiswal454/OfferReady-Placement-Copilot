"""Interview lifecycle: start, take a turn, end. Used by the API (text and voice mode)."""
from __future__ import annotations

import random

from ..db import get_db, now_iso
from ..tasks import enqueue
from .engine import (TRANSITIONS, advance, phase_end, allowed_actions, assess_and_phrase, build_plan, closing_line, current_item,
                     elapsed_s, initial_state)


def _turns(interview_id: int) -> list[dict]:
    return get_db().fetchall("SELECT * FROM interview_turns WHERE interview_id = ? ORDER BY seq", (interview_id,))


def _add_turn(interview_id: int, speaker: str, text: str, t_ms: int, meta: dict | None = None) -> dict:
    db = get_db()
    seq = (db.scalar("SELECT MAX(seq) FROM interview_turns WHERE interview_id = ?", (interview_id,)) or 0) + 1
    db.insert("interview_turns", {"interview_id": interview_id, "seq": seq, "speaker": speaker, "text": text, "t_ms": t_ms,
                                  "meta": meta or {}})
    return {"seq": seq, "speaker": speaker, "text": text, "t_ms": t_ms, "meta": meta or {}}


def candidate_projects(user_id: int) -> list[dict]:
    db = get_db()
    rows = db.fetchall("SELECT input FROM profile_sources WHERE user_id = ? AND kind = 'project' ORDER BY id", (user_id,))
    projects = [r["input"] for r in rows if (r["input"] or {}).get("name")]
    if not projects:
        resume = db.fetchone("SELECT extracted FROM profile_sources WHERE user_id = ? AND kind = 'resume' AND status = 'ready' "
                             "ORDER BY id DESC LIMIT 1", (user_id,))
        import re

        for p in ((resume or {}).get("extracted") or {}).get("projects", [])[:3]:
            name = re.split(r"\s*\|\s*|\s{3,}", p.get("title", ""))[0].strip()
            if name:
                projects.append({"name": name, "tech": p.get("tech", []), "description": " ".join(p.get("bullets", []))})
    return projects


def start(user: dict, mode: str, duration: int, provider: str, model: str) -> dict:
    db = get_db()
    resume = db.fetchone("SELECT extracted FROM profile_sources WHERE user_id = ? AND kind = 'resume' AND status = 'ready' "
                         "ORDER BY id DESC LIMIT 1", (user["id"],))
    previous = db.fetchall("SELECT plan FROM interviews WHERE user_id = ? ORDER BY id DESC LIMIT 3", (user["id"],))
    seen = {i["id"] for p in previous for ph in (p["plan"] or {}).get("phases", []) for i in ph.get("items", [])}
    seed = random.randint(1, 10 ** 9)
    plan = build_plan(user, (resume or {}).get("extracted"), candidate_projects(user["id"]), duration, seed, seen)
    state = initial_state()
    iid = db.insert("interviews", {"user_id": user["id"], "mode": mode, "duration_min": duration, "target_role": plan["role"],
                                   "provider": provider, "model": model, "status": "live", "plan": plan, "state": state,
                                   "result": {}, "started_at": now_iso()})
    first = current_item(plan, state)
    name = (user.get("name") or "").split(" ")[0]
    greeting = (f"Hi {name}! I'm your interviewer for this {duration}-minute mock interview for a {plan['role']} role. "
                f"I'll ask one question at a time; take a moment to think before you answer. {first['question']}")
    turn = _add_turn(iid, "interviewer", greeting, 0, {"item_id": first["id"], "item_type": first["type"],
                                                         "phase": plan["phases"][0]["key"]})
    return {"interview_id": iid, "plan": public_plan(plan), "turn": turn, "state": public_state(plan, state, 0)}


def public_plan(plan: dict) -> dict:
    return {"role": plan["role"], "duration_min": plan["duration_min"],
            "phases": [{"key": p["key"], "label": p["label"], "budget_s": p["budget_s"], "questions": len(p["items"])}
                       for p in plan["phases"]]}


def public_state(plan: dict, state: dict, elapsed: float) -> dict:
    total = plan["duration_min"] * 60
    phase = plan["phases"][min(state["phase"], len(plan["phases"]) - 1)]
    return {"phase": phase["key"], "phase_label": phase["label"], "phase_index": state["phase"],
            "elapsed_s": int(elapsed), "remaining_s": max(0, int(total - elapsed)), "done": state.get("done", False)}


async def take_turn(interview: dict, user: dict, text: str) -> dict:
    db = get_db()
    plan, state = interview["plan"], interview["state"]
    if interview["status"] != "live" or state.get("done"):
        return {"done": True, "turns": []}
    elapsed = elapsed_s(interview)
    t_ms = int(elapsed * 1000)
    item = current_item(plan, state) or {"type": "wrap", "id": "WRAP", "question": "", "key_points": []}
    total_left = plan["duration_min"] * 60 - elapsed
    phase_left = phase_end(plan, min(state["phase"], len(plan["phases"]) - 1)) - elapsed
    allowed = allowed_actions(plan, state, item, total_left, phase_left)
    history = [{"speaker": t["speaker"], "text": t["text"]} for t in _turns(interview["id"])]
    decision = await assess_and_phrase(item, text, allowed, history[-8:] if len(history) > 8 else history, user,
                                       seed=interview["id"] * 1000 + len(history), followup_index=state["followups"])
    cand_meta = {"item_id": item["id"], "item_type": item["type"], "topic": item.get("topic") or item.get("project"),
                 "assessment": decision["assessment"], "covered": decision.get("covered", []),
                 "followup": state["followups"] > 0, "action": decision["action"],
                 "injection": bool(decision.get("injection")), "words": len(text.split())}
    cand_turn = _add_turn(interview["id"], "candidate", text.strip()[:6000], t_ms, cand_meta)
    state["assessments"].append({"item": item["id"], "assessment": decision["assessment"]})
    out_turns = [cand_turn]
    done = False
    if total_left <= 0 or item["type"] == "wrap":
        say = closing_line(user.get("name"))
        done = True
        meta = {"item_type": "close"}
    elif decision["action"] in ("follow_up", "hint", "rephrase", "redirect"):
        if decision["action"] in ("follow_up", "hint"):
            state["followups"] += 1
        if decision["action"] == "redirect":
            state["redirects"] = state.get("redirects", 0) + 1
        say = f"{decision['ack']} {decision['follow_up']}".strip()
        meta = {"item_id": item["id"], "item_type": item["type"], "followup": True, "action": decision["action"],
                "topic": item.get("topic")}
    else:
        nxt, transition = advance(plan, state, elapsed)
        if nxt is None:
            say = closing_line(user.get("name"))
            done = True
            meta = {"item_type": "close"}
        else:
            lead = decision["ack"] if decision["assessment"] != "dont_know" else "No problem, let's move on."
            say = " ".join(x for x in [lead, transition, nxt["question"]] if x)
            meta = {"item_id": nxt["id"], "item_type": nxt["type"], "topic": nxt.get("topic") or nxt.get("project"),
                    "phase": plan["phases"][state["phase"]]["key"]}
    out_turns.append(_add_turn(interview["id"], "interviewer", say, t_ms + 1, meta))
    state["done"] = done
    db.update("interviews", interview["id"], {"state": state, "plan": plan})   # plan may gain reserve questions
    if done:
        finish(interview["id"], interview["user_id"])
    return {"turns": out_turns, "done": done, "state": public_state(plan, state, elapsed), "decision": {
        "assessment": decision["assessment"], "action": decision["action"]}}


def finish(interview_id: int, user_id: int, reason: str = "completed") -> None:
    db = get_db()
    row = db.fetchone("SELECT status, state FROM interviews WHERE id = ?", (interview_id,))
    if not row or row["status"] != "live":
        return
    state = row["state"] or {}
    state["done"] = True
    state["end_reason"] = reason
    db.update("interviews", interview_id, {"status": "scoring", "ended_at": now_iso(), "state": state})
    enqueue("score_interview", {"interview_id": interview_id}, user_id=user_id, dedupe_key=f"interview:{interview_id}")
