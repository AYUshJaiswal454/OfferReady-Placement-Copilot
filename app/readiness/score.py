"""Placement readiness score (0–100) and the top 5 actions that would raise it most.

Formula (MSOT weights): resume 25, projects 25, mock interview 20, GitHub 10, coding 10,
LinkedIn 5, co-curricular 5. Each component is the deterministic score of its latest review;
projects = mean of the best 3 project reviews (at least 2 expected). The expected gain of an
action is computed exactly from this formula: fixing check i in component c adds
weight_c x (max_i - score_i) / (sum of applicable max in c).
"""
from __future__ import annotations

from ..db import get_db, iso_in, now_iso

FORMULA_VERSION = "readiness-2026.10"
WEIGHTS = {"resume": 25, "projects": 25, "interview": 20, "github": 10, "coding": 10, "linkedin": 5, "achievements": 5}
LABELS = {"resume": "Resume quality", "projects": "Projects", "interview": "Mock interview", "github": "GitHub profile",
          "coding": "Coding practice", "linkedin": "LinkedIn profile", "achievements": "Co-curricular"}
EFFORT_FACTOR = {"quick": 1.0, "medium": 1.6, "long": 2.6}
MISSING_ACTION = {
    "resume": ("Upload your resume", "It is 25% of your score and powers job matching.", "resume"),
    "projects": ("Add your projects (GitHub + live link)", "Projects are 25% of your score; add 2–3 with repo and live links.", "projects"),
    "interview": ("Take a 15-minute mock interview", "Interview performance is 20% of your score.", "interview"),
    "github": ("Connect your GitHub username", "Public profile, activity and repos (10%).", "github"),
    "coding": ("Add your LeetCode or Codeforces profile", "Coding practice is 10% of your score.", "coding"),
    "linkedin": ("Upload your LinkedIn PDF export", "LinkedIn is 5% of your score and gets ready-to-paste rewrites.", "linkedin"),
    "achievements": ("Add your achievements", "Hackathons, clubs, certifications (5%).", "achievements"),
}
TYPICAL = 0.65   # expected component score once a missing component is added (used only to rank actions)


def level_for(score: float) -> str:
    return "Placement ready" if score >= 75 else ("Almost ready" if score >= 50 else "Not ready")


def _latest_reviews(user_id: int) -> dict[str, list[dict]]:
    db = get_db()
    rows = db.fetchall(
        "SELECT r.* FROM reviews r JOIN (SELECT kind, COALESCE(source_id, 0) AS sid, MAX(id) AS mid FROM reviews WHERE user_id = ? "
        "GROUP BY kind, COALESCE(source_id, 0)) last ON last.mid = r.id ORDER BY r.id", (user_id,))
    live_sources = {r["id"] for r in db.fetchall("SELECT id FROM profile_sources WHERE user_id = ?", (user_id,))}
    out: dict[str, list[dict]] = {}
    for r in rows:
        if r["source_id"] and r["source_id"] not in live_sources:
            continue   # source deleted by the student
        out.setdefault(r["kind"], []).append(r)
    return out


def _check_actions(component: str, review: dict, weight: float, divisor: float = 1.0) -> list[dict]:
    checks = [c for c in review["checks"] if c.get("status") != "na"]
    total_max = sum(c["max"] for c in checks) or 1
    out = []
    for c in checks:
        missing = c["max"] - c["score"]
        if missing <= 0.01 or c.get("status") == "pass":
            continue
        gain = weight * missing / total_max / divisor
        fix = next((f for f in c.get("fixes", []) if not f.startswith("Ready-to-paste")), c.get("summary", ""))
        out.append({
            "component": component, "component_label": LABELS[component], "check_id": c["id"], "title": c["title"],
            "detail": fix, "gain": round(gain, 2), "effort": c.get("effort", "quick"), "review_id": review["id"],
            "source_id": review.get("source_id"),
        })
    return out


def _merge_same_fix(actions: list[dict]) -> list[dict]:
    """One fix that resolves several checks (e.g. "make the repository public") becomes one action whose gain is the sum."""
    merged: dict[tuple, dict] = {}
    out: list[dict] = []
    for a in actions:
        key = (a["component"], a.get("source_id"), (a.get("detail") or "").strip().lower())
        if not key[2] or a["check_id"] in ("MISSING", "PROJECT_COUNT", "INTERVIEW"):
            out.append(a)
            continue
        if key in merged:
            m = merged[key]
            m["gain"] = round(m["gain"] + a["gain"], 2)
            m.setdefault("also_fixes", []).append(a["title"].split(": ", 1)[-1])
            if EFFORT_FACTOR.get(a.get("effort", "quick"), 1) > EFFORT_FACTOR.get(m.get("effort", "quick"), 1):
                m["effort"] = a["effort"]
            continue
        merged[key] = a
        out.append(a)
    return out


def compute(user_id: int) -> dict:
    latest = _latest_reviews(user_id)
    db = get_db()
    components: dict[str, dict] = {}
    actions: list[dict] = []

    def single(kind: str) -> None:
        rows = latest.get(kind) or []
        if rows:
            r = rows[-1]
            components[kind] = {"score": r["score"], "review_id": r["id"], "updated_at": r["created_at"]}
            actions.extend(_check_actions(kind, r, WEIGHTS[kind]))
        else:
            components[kind] = {"score": None}

    single("resume")
    single("github")
    single("linkedin")
    single("coding")
    single("achievements")
    projects = sorted(latest.get("project") or [], key=lambda r: -r["score"])[:3]
    if projects:
        divisor = max(2, len(projects))
        components["projects"] = {"score": round(sum(p["score"] for p in projects) / divisor, 1), "count": len(projects),
                                  "items": [{"review_id": p["id"], "score": p["score"],
                                             "name": (p.get("data") or {}).get("project", {}).get("name")} for p in projects]}
        for p in projects:
            name = (p.get("data") or {}).get("project", {}).get("name") or "project"
            for a in _check_actions("projects", p, WEIGHTS["projects"], divisor):
                a["title"] = f"{name}: {a['title']}"
                actions.append(a)
        if len(projects) < 2:
            actions.append({"component": "projects", "component_label": LABELS["projects"], "check_id": "PROJECT_COUNT",
                            "title": "Add a second project", "detail": "Two to three complete projects are expected; each "
                            "missing one costs you half of the Projects component.", "gain": round(WEIGHTS["projects"] * TYPICAL / 2, 2),
                            "effort": "long", "review_id": None, "source_id": None})
    else:
        components["projects"] = {"score": None}
    interview = db.fetchone("SELECT id, score, ended_at, result FROM interviews WHERE user_id = ? AND status = 'completed' "
                            "AND score IS NOT NULL ORDER BY id DESC LIMIT 1", (user_id,))
    if interview:
        components["interview"] = {"score": interview["score"], "interview_id": interview["id"], "updated_at": interview["ended_at"]}
        weak = (interview.get("result") or {}).get("weak_areas") or []
        gap = 100 - interview["score"]
        if gap > 10:
            actions.append({"component": "interview", "component_label": LABELS["interview"], "check_id": "INTERVIEW",
                            "title": "Improve your mock interview score", "detail": (weak[0] if weak else
                            "Practice explaining your projects and core concepts, then retake the mock interview."),
                            "gain": round(WEIGHTS["interview"] * gap / 100 * 0.5, 2), "effort": "medium",
                            "review_id": None, "source_id": None})
    else:
        components["interview"] = {"score": None}

    score = 0.0
    present = 0
    for kind, comp in components.items():
        comp["weight"] = WEIGHTS[kind]
        comp["label"] = LABELS[kind]
        if comp.get("score") is not None:
            present += 1
            comp["points"] = round(WEIGHTS[kind] * comp["score"] / 100, 2)
            score += comp["points"]
        else:
            comp["points"] = 0.0
            title, detail, target = MISSING_ACTION[kind]
            actions.append({"component": kind, "component_label": LABELS[kind], "check_id": "MISSING", "title": title,
                            "detail": detail, "gain": round(WEIGHTS[kind] * TYPICAL, 2), "max_gain": WEIGHTS[kind],
                            "effort": "quick" if kind in ("resume", "github", "coding", "linkedin", "achievements") else "medium",
                            "target": target, "review_id": None, "source_id": None})
    actions = _merge_same_fix(actions)
    for a in actions:
        a["priority"] = round(a["gain"] / EFFORT_FACTOR.get(a.get("effort", "quick"), 1.0), 3)
    actions.sort(key=lambda a: (-a["priority"], -a["gain"]))
    # Avoid five near-identical actions: at most two per component in the top list.
    top, per_comp = [], {}
    for a in actions:
        if per_comp.get(a["component"], 0) >= 2:
            continue
        top.append(a)
        per_comp[a["component"]] = per_comp.get(a["component"], 0) + 1
        if len(top) == 5:
            break
    score = round(score, 1)
    return {
        "score": score, "level": level_for(score), "components": components, "top_actions": top,
        "all_actions": actions[:40], "completeness": round(present / len(WEIGHTS), 2), "formula_version": FORMULA_VERSION,
        "potential": round(min(100.0, score + sum(a["gain"] for a in top)), 1),
    }


def snapshot(user_id: int) -> dict:
    result = compute(user_id)
    db = get_db()
    # History records settled states only: while a source is still being reviewed (e.g. a replaced resume) the
    # score would briefly dip, so we wait for the review to finish and its own recompute.
    if db.fetchone("SELECT id FROM profile_sources WHERE user_id = ? AND status = 'pending' AND updated_at > ? LIMIT 1",
                   (user_id, iso_in(minutes=-10))):
        return result
    last = db.fetchone("SELECT score, components FROM readiness_snapshots WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,))
    comp_scores = {k: v.get("score") for k, v in result["components"].items()}
    if not last or abs(last["score"] - result["score"]) >= 0.05 or {k: v.get("score") for k, v in (last["components"] or {}).items()} != comp_scores:
        db.insert("readiness_snapshots", {
            "user_id": user_id, "score": result["score"], "level": result["level"], "components": result["components"],
            "top_actions": result["top_actions"], "formula_version": FORMULA_VERSION, "created_at": now_iso(),
        })
    return result
