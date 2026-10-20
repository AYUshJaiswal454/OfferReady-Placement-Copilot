"""Rank jobs for a student and explain every match.

match = 100 x (0.45 skills + 0.20 role + 0.15 level + 0.10 location + 0.10 freshness),
x 0.75 when the job is in an unrelated role family.
Each part is shown to the student ("why this matched"), together with the skills they are
missing for that job — which feeds back into their readiness actions.
"""
from __future__ import annotations

import re

from ..db import parse_iso, utcnow
from ..skills import ROLES, role_from_text, skill_category
from .normalize import canonical_city

RELATED = {
    "sde": {"backend", "frontend", "fullstack", "mobile"}, "backend": {"sde", "fullstack", "devops"},
    "frontend": {"fullstack", "sde", "uiux"}, "fullstack": {"frontend", "backend", "sde"},
    "data_science": {"genai", "data_analyst"}, "genai": {"data_science", "backend"}, "data_analyst": {"data_science"},
    "devops": {"backend", "sde"}, "mobile": {"sde", "frontend"}, "qa": {"sde"}, "uiux": {"frontend"}, "security": {"devops"},
}
REQ_SECTION = re.compile(r"(requirements?|qualifications?|must have|what we('| a)re looking for|you have|skills)[:\s]", re.I)
NICE_SECTION = re.compile(r"(nice to have|good to have|bonus|preferred|plus)[:\s]", re.I)


def job_skill_weights(job: dict) -> dict[str, float]:
    """Skills in the requirements part of the description weigh more than 'nice to have' ones."""
    from ..skills import extract_skills

    desc = job.get("description") or ""
    weights = {s: 0.7 for s in job.get("skills") or []}
    nice = NICE_SECTION.search(desc)
    req = REQ_SECTION.search(desc)
    if req:
        end = nice.start() if nice and nice.start() > req.start() else len(desc)
        for s in extract_skills(desc[req.start():end], technical_context=True):
            weights[s] = 1.0
    if nice:
        for s in extract_skills(desc[nice.start():nice.start() + 600], technical_context=True):
            if weights.get(s, 0) < 1.0:
                weights[s] = 0.4
    for s in extract_skills(job.get("title") or "", technical_context=True):
        weights[s] = 1.0
    # Generic skills say little about fit.
    for s in list(weights):
        if skill_category(s) in ("tools", "practices") or s in ("Git", "GitHub", "Agile"):
            weights[s] = min(weights[s], 0.3)
    return weights


_FEATURES: dict[tuple, tuple] = {}


def _job_features(job: dict) -> tuple:
    """Skill weights and role family depend only on the job text, so they are computed once per job version
    (extracting skills from a description is the expensive part of ranking)."""
    key = (job.get("source"), job.get("id"), job.get("title"), len(job.get("description") or ""), job.get("updated_at"))
    hit = _FEATURES.get(key) if job.get("id") is not None else None
    if hit is None:
        hit = (job.get("skill_weights") or job_skill_weights(job), role_from_text(job.get("title")), canonical_city(job.get("location")),
               parse_iso(job.get("posted_at")))
        if job.get("id") is not None:
            if len(_FEATURES) > 50_000:
                _FEATURES.clear()
            _FEATURES[key] = hit
    return hit


def score_job(job: dict, profile: dict) -> dict:
    student_skills = set(profile.get("skills") or [])
    weights, job_role, city, posted = _job_features(job)
    total = sum(weights.values())
    matched = sorted([s for s in weights if s in student_skills], key=lambda s: -weights[s])
    missing = sorted([s for s in weights if s not in student_skills and weights[s] >= 0.7], key=lambda s: -weights[s])
    skill_score = (sum(weights[s] for s in matched) / total) if total else 0.3

    role_id = profile.get("role_id") or role_from_text(profile.get("target_role"))
    if job_role == role_id:
        role_score, role_reason = 1.0, f"Matches your target role ({ROLES[role_id]['title']})"
    elif job_role in RELATED.get(role_id, set()):
        role_score, role_reason = 0.6, f"Related role ({ROLES[job_role]['title']})"
    else:
        role_score, role_reason = 0.2, f"Different role ({ROLES[job_role]['title']})"

    wants = profile.get("job_type") or "internship"
    etype = job.get("employment_type") or "fulltime"
    exp_min = job.get("experience_min")
    if etype == "internship":
        level_score = 1.0 if wants in ("internship", "both") else 0.5
        level_reason = "Internship"
    elif exp_min is None:
        level_score = 0.7 if wants in ("fulltime", "both") else 0.4
        level_reason = "Experience not specified"
    elif exp_min <= 1:
        level_score = 1.0 if wants in ("fulltime", "both") else 0.6
        level_reason = "Open to freshers"
    elif exp_min <= 2:
        level_score, level_reason = 0.4, f"Asks for {exp_min:g}+ years"
    else:
        level_score, level_reason = 0.05, f"Needs {exp_min:g}+ years — likely out of reach now"

    locs = [l.lower() for l in profile.get("locations") or []]
    loc_text = (job.get("location") or "").lower()
    if job.get("remote") and ("remote" in locs or not locs):
        loc_score, loc_reason = 1.0, "Remote"
    elif city and any(canonical_city(l) == city or l in loc_text for l in locs if l != "remote"):
        loc_score, loc_reason = 1.0, f"In {city}"
    elif job.get("remote"):
        loc_score, loc_reason = 0.8, "Remote"
    elif city:
        loc_score, loc_reason = 0.55, f"In {city} (not in your locations)"
    elif re.search(r"india", loc_text):
        loc_score, loc_reason = 0.6, "India"
    elif loc_text:
        loc_score, loc_reason = 0.15, f"Outside India ({job.get('location')})"
    else:
        loc_score, loc_reason = 0.5, "Location not specified"

    age = (utcnow() - posted).days if posted else None
    fresh = 1.0 if age is not None and age <= 7 else 0.7 if age is not None and age <= 21 else 0.4 if age is not None else 0.5

    score = 100 * (0.45 * skill_score + 0.20 * role_score + 0.15 * level_score + 0.10 * loc_score + 0.10 * fresh)
    if role_score <= 0.2:
        score *= 0.75   # shared skills alone (e.g. Java for a QA role) shouldn't make an unrelated role look like a fit
    reasons = []
    if matched:
        reasons.append(f"You have {', '.join(matched[:5])}")
    reasons += [role_reason, level_reason, loc_reason]
    if age is not None:
        reasons.append("Posted today" if age == 0 else f"Posted {age} day{'s' if age != 1 else ''} ago")
    return {
        "match": round(score), "matched_skills": matched[:8], "missing_skills": missing[:5], "reasons": reasons,
        "parts": {"skills": round(skill_score, 2), "role": role_score, "level": level_score, "location": loc_score,
                  "freshness": fresh},
    }


def msot_eligibility(job: dict, profile: dict) -> tuple[bool, list[str]]:
    rules = job.get("eligibility") or {}
    reasons = []
    min_score = rules.get("min_score")
    if min_score and (profile.get("readiness") or 0) < float(min_score):
        reasons.append(f"Needs readiness ≥ {min_score:g} (you're at {profile.get('readiness') or 0:g})")
    batches = rules.get("batches") or []
    if batches and profile.get("batch_year") not in [int(b) for b in batches]:
        reasons.append(f"Open to batch {', '.join(str(b) for b in batches)}")
    branches = [b.lower() for b in rules.get("branches") or []]
    if branches and (profile.get("branch") or "").lower() not in branches:
        reasons.append(f"Open to {', '.join(rules['branches'])}")
    req = rules.get("skills") or []
    have = set(profile.get("skills") or [])
    lacking = [s for s in req if s not in have]
    if req and len(lacking) > len(req) / 2:
        reasons.append(f"Requires {', '.join(lacking)}")
    return (not reasons), reasons
