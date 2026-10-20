"""LinkedIn benchmark: photo, headline, About, consistency with the resume, skills, URL.

Suggestions are returned as ready-to-paste text built from the student's own data
(resume, coding profiles, target role). Nothing is invented: numbers come from their data
or are left as [placeholders].
"""
from __future__ import annotations

import re

from ..intake.linkedin_parser import LinkedInProfile, profile_skills
from ..skills import ROLES, extract_skills, role_from_text, role_gap, role_skill_weights
from .common import Check, Evidence, plural, total_score

BENCHMARK_VERSION = "linkedin-2026.10"
ROLE_WORDS = re.compile(r"\b(developer|engineer|analyst|scientist|designer|intern|sde|programmer|architect|consultant|"
                        r"specialist|researcher|devops|full[- ]?stack|front[- ]?end|back[- ]?end|ml|ai|data)\b", re.I)
GENERIC_HEADLINE = re.compile(r"^(student|undergraduate|b\.?\s?tech|btech|engineering student|fresher|looking for|"
                              r"aspiring|actively looking|open to work)\b[^|]{0,60}(at|@|student|university|college|institute)?", re.I)
CLICHES = re.compile(r"(hard[- ]?working|passionate about technology|team player|quick learner|self[- ]motivated|"
                     r"looking for (new )?opportunities|seeking (a )?challenging|go[- ]getter|dedicated individual)", re.I)


def _norm_org(name: str) -> str:
    n = name.lower()
    n = re.sub(r"\b(pvt|private|ltd|limited|inc|llp|llc|technologies|technology|solutions|labs?|software|services|india|corp|"
               r"corporation|co)\b", " ", n)
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    return " ".join(n.split())


def _same_org(a: str, b: str) -> bool:
    x, y = _norm_org(a), _norm_org(b)
    if not x or not y:
        return False
    if x in y or y in x:
        return True
    xs, ys = set(x.split()), set(y.split())
    return len(xs & ys) / max(1, min(len(xs), len(ys))) >= 0.6


def _years(text: str) -> set[int]:
    return {int(y) for y in re.findall(r"(?:19|20)\d{2}", text or "")}


def headline_skills(skills: list[str], role_id: str, n: int = 3) -> list[str]:
    """Skills worth showing in a headline: role-relevant languages/frameworks/databases, not Git or DSA."""
    from ..skills import skill_category

    weights = role_skill_weights(role_id)
    bonus = {"language": 0.5, "backend": 0.6, "frontend": 0.6, "database": 0.4, "ml": 0.6, "data": 0.4, "cloud": 0.3,
             "devops": 0.4, "mobile": 0.6, "tools": -0.8, "cs_core": -0.8, "practices": -1.0, "testing": -0.3, "design": 0.3}
    ranked = sorted(dict.fromkeys(skills), key=lambda s: -(weights.get(s, 0.0) + bonus.get(skill_category(s), 0.0)))
    return ranked[:n]


def headline_options(ctx: dict, skills: list[str]) -> list[str]:
    role_id = role_from_text(ctx.get("target_role"))
    role = ctx.get("target_role") or ROLES[role_id]["title"]
    role = re.sub(r"\b(intern(ship)?)\b", "", role, flags=re.I).strip() or ROLES[role_id]["title"]
    ranked = headline_skills(skills, role_id) or [s for s in ROLES[role_id]["core"][:3]]
    proof = []
    if ctx.get("leetcode_solved"):
        proof.append(f"{ctx['leetcode_solved']}+ LeetCode")
    for exp in (ctx.get("resume") or {}).get("experience", [])[:1]:
        org = re.split(r"\s{3,}", exp.get("title", ""))[0]
        if org:
            proof.append(f"Ex-Intern @ {org}")
    grad = f"B.Tech {ctx.get('branch') or 'CSE'} '{str(ctx.get('batch_year') or '')[-2:]}" if ctx.get("batch_year") else ""
    college = ctx.get("college") or "MSOT"
    opts = [
        " | ".join(x for x in [role, " · ".join(ranked), proof[0] if proof else "", f"{grad} @ {college}".strip(" @")] if x),
        " | ".join(x for x in [f"{role} building with {', '.join(ranked[:2])}", proof[-1] if proof else "[your best result]", grad] if x),
        f"{role} (open to {'internships' if ctx.get('job_type', 'internship') != 'fulltime' else 'full-time roles'}) | "
        f"{' · '.join(ranked)} | [one proof: hackathon rank / users / LeetCode count]",
    ]
    return [o[:220] for o in opts]


def about_draft(profile: LinkedInProfile, ctx: dict, skills: list[str]) -> str:
    resume = ctx.get("resume") or {}
    role_id = role_from_text(ctx.get("target_role"))
    role = ctx.get("target_role") or ROLES[role_id]["title"]
    name_first = (profile.name or ctx.get("name") or "").split(" ")[0]
    projects = resume.get("projects", [])[:2]
    exp = resume.get("experience", [])[:1]
    lines = []
    year = ctx.get("batch_year")
    domain = role.lower()
    for a, b in (("developer", "development"), ("engineer", "engineering"), ("analyst", "analytics"),
                 ("scientist", "science"), ("designer", "design")):
        domain = re.sub(rf"\b{a}\b", b, domain)
    top = headline_skills(skills, role_id, 4)
    lines.append(f"I'm a {('final-year ' if year else '')}{ctx.get('branch') or 'Computer Science'} student at "
                 f"{ctx.get('college') or 'MSOT'} focused on {domain}, mostly with {', '.join(top) or '[your main skills]'}.")
    if projects:
        bits = []
        for p in projects:
            name = re.split(r"\s*\|\s*|\s{3,}", p.get("title", ""))[0]
            first = (p.get("bullets") or [""])[0]
            bits.append(f"{name} — {first[:140].rstrip('.')}" if first else name)
        lines.append("Recent projects: " + "; ".join(bits) + ".")
    if exp:
        org = re.split(r"\s{3,}", exp[0].get("title", ""))[0]
        first = (exp[0].get("bullets") or [""])[0]
        lines.append(f"During my internship at {org}, I {first[:1].lower() + first[1:160].rstrip('.') if first else '[what you built]'}.")
    proof = []
    if ctx.get("leetcode_solved"):
        proof.append(f"solved {ctx['leetcode_solved']}+ problems on LeetCode")
    if resume.get("achievements"):
        a = resume["achievements"][0][:120].rstrip(".")
        proof.append(a[:1].lower() + a[1:] if a[:1].isupper() and not a[:2].isupper() else a)
    if proof:
        lines.append("Outside coursework I have " + " and ".join(proof) + ".")
    when = "internships" if ctx.get("job_type", "internship") != "fulltime" else "full-time roles"
    contact = ctx.get("email") or "[your email]"
    lines.append(f"I'm looking for {role.lower()} {when}. Reach me at {contact}.")
    return "\n\n".join(lines) if name_first else "\n\n".join(lines)


ACTION_PHRASE = {"L1": "add a clear, professional photo", "L2": "make the headline name your role and stack",
                 "L3": "rewrite the About section around your projects", "L4": "make LinkedIn and your resume agree",
                 "L5": "add the core skills for your target role", "L6": "claim a custom profile URL",
                 "L7": "fill in education, location and certifications"}


def _summary(score: float, checks: list) -> str:
    todo = [c for c in sorted(checks, key=lambda c: c.score - c.max) if c.status in ("fail", "warn")]
    if not todo:
        return f"LinkedIn scores {score:.0f}/100 and every check passes."
    steps = [ACTION_PHRASE.get(c.id, c.title.lower()) for c in todo[:3]]
    joined = steps[0] if len(steps) == 1 else ", ".join(steps[:-1]) + " and " + steps[-1]
    return f"LinkedIn scores {score:.0f}/100. The biggest gains: {joined}."


def review_linkedin(profile: LinkedInProfile, ctx: dict) -> dict:
    """ctx: {target_role, resume (extracted summary), leetcode_solved, name, email, branch, batch_year, job_type, photo}"""
    checks: list[Check] = []
    skills = profile_skills(profile)
    rewrite_skills = list(dict.fromkeys(skills + list((ctx.get("resume") or {}).get("skills", []))))

    # L1 photo ---------------------------------------------------------------------------
    c = Check("L1", "Professional profile photo", "Profile", 10,
              why="Profiles with a photo get far more profile views and connection accepts; recruiters skip faceless profiles.")
    photo = ctx.get("photo")   # True / False / None (unknown)
    if photo is True:
        c.finish(10, "Profile photo present" + (" (detected in your screenshot)." if ctx.get("photo_detected") else " (self-reported)."))
    elif photo is False:
        c.fixes.append("Add a clear, front-facing photo: plain background, good light, face filling ~60% of the frame.")
        c.finish(0, "No profile photo.")
    else:
        c.fixes.append("We can't see photos in the PDF export. Upload a screenshot of your profile, or confirm you have a photo.")
        c.na("Photo not verifiable from the PDF export.")
    checks.append(c)

    # L2 headline --------------------------------------------------------------------------
    c = Check("L2", "Specific headline", "Profile", 20,
              why="The headline is shown next to your name everywhere (search, comments, applications). "
                  "'Student at X' tells a recruiter nothing; role + skills + proof does.")
    h = profile.headline.strip()
    score = 0.0
    if len(h.split()) >= 3:
        score += 5
        role_ok = bool(ROLE_WORDS.search(h))
        h_skills = extract_skills(h, technical_context=True)
        proof = bool(re.search(r"\d", h)) or bool(re.search(r"(intern|hackathon|winner|rank|gsoc|@)", h, re.I))
        generic = bool(GENERIC_HEADLINE.match(h)) and not role_ok
        score += 5 if role_ok else 0
        score += 5 if len(h_skills) >= 2 or (h_skills and proof) else 0
        score += 5 if not generic and (proof or len(h_skills) >= 3) else (2.5 if not generic else 0)
        c.evidence.append(Evidence(text=f"Current headline: \"{h}\""))
        if not role_ok:
            c.fixes.append("State the role you want (e.g. 'Backend Developer', 'Data Analyst') in the headline.")
        if len(h_skills) < 2:
            c.fixes.append("Add your 2–3 strongest technologies to the headline.")
        if not proof:
            c.fixes.append("Add one proof point: internship, LeetCode count, hackathon rank, or project users.")
    else:
        c.evidence.append(Evidence(text="Headline missing or too short"))
        c.fixes.append("Write a headline: Role | 3 core skills | one proof point.")
    options = headline_options(ctx, rewrite_skills)
    c.details = {"rewrites": options}
    c.fixes.append("Ready-to-paste options:\n" + "\n".join(f"• {o}" for o in options))
    checks.append(c.finish(score, "Headline is specific." if score >= 18 else f"Headline scores {score:.0f}/20."))

    # L3 About -----------------------------------------------------------------------------
    c = Check("L3", "About section present and specific", "Profile", 20, effort="medium",
              why="The About section is your pitch. Recruiters read the first 2–3 lines before deciding to scroll.")
    about = profile.about.strip()
    score = 0.0
    if about:
        score += 5
        n = len(about)
        score += 5 if 300 <= n <= 2600 else (2.5 if n >= 150 else 0)
        a_skills = extract_skills(about, technical_context=False)
        score += 5 if len(a_skills) >= 3 else (2.5 if a_skills else 0)
        has_proof = bool(re.search(r"\d", about)) or bool(re.search(r"(built|developed|intern|won|ranked|led)", about, re.I))
        has_cta = bool(re.search(r"(reach|contact|email|open to|looking for|@|connect)", about, re.I))
        score += 2.5 * has_proof + 2.5 * has_cta
        if CLICHES.search(about):
            score -= 3
            c.evidence.append(Evidence(text=f"Generic phrase: \"{CLICHES.search(about).group(0)}\""))
            c.fixes.append("Replace generic phrases (hardworking, passionate, team player) with evidence: what you built and the result.")
        if n < 300:
            c.fixes.append(f"Your About is {n} characters; write 3–5 short sentences (300–1,200 characters).")
        if len(a_skills) < 3:
            c.fixes.append("Mention the technologies you actually use (3–6), ideally the ones in your target job descriptions.")
        if not has_proof:
            c.fixes.append("Add at least one concrete achievement with a number.")
        if not has_cta:
            c.fixes.append("End with what you're looking for and how to reach you.")
    else:
        c.evidence.append(Evidence(text="No About / Summary section"))
        c.fixes.append("Add an About section — a ready-to-paste draft is below.")
    draft = about_draft(profile, ctx, rewrite_skills)
    c.details = {"rewrite": draft, "length": len(about)}
    checks.append(c.finish(score, "About section is specific." if score >= 18 else
                           ("No About section." if not about else f"About section scores {score:.0f}/20.")))

    # L4 consistency with resume --------------------------------------------------------------
    c = Check("L4", "Experience and projects match the resume", "Consistency", 20,
              why="Recruiters compare LinkedIn with your resume. Missing internships or different dates look like fabrication.")
    resume = ctx.get("resume")
    if not resume:
        checks.append(c.na("Upload your resume to compare it with LinkedIn."))
    else:
        r_exp = resume.get("experience", [])
        problems = 0
        for e in r_exp:
            org = re.split(r"\s{3,}", e.get("title", ""))[0]
            match = next((x for x in profile.experience if _same_org(org, x.org) or _same_org(org, x.title)), None)
            if not match:
                problems += 1
                when = " – ".join(e.get("dates", [])[:2])
                c.evidence.append(Evidence(text=f"'{org}' is on your resume but not on LinkedIn", label="Missing"))
                c.fixes.append(f"Add '{org}' to LinkedIn Experience" + (f" ({when})" if when else "") + " with the same title and dates.")
            else:
                ry = _years(" ".join(e.get("dates", [])))
                ly = _years(match.dates)
                if ry and ly and not (ry & ly):
                    problems += 1
                    c.evidence.append(Evidence(text=f"Dates for '{org}' differ: resume {sorted(ry)} vs LinkedIn {match.dates}", label="Dates"))
                    c.fixes.append(f"Make the dates for '{org}' identical on both.")
        r_projects = resume.get("projects", [])
        if r_projects and profile.source == "text" and not profile.projects:
            names = [re.split(r"\s*\|\s*|\s{3,}", p.get("title", ""))[0] for p in r_projects[:3]]
            c.fixes.append("Add a Projects section on LinkedIn with: " + ", ".join(names) + " (link each to GitHub/live).")
            problems += 0.5
        elif r_projects and profile.source == "pdf":
            names = [re.split(r"\s*\|\s*|\s{3,}", p.get("title", ""))[0] for p in r_projects[:3]]
            c.fixes.append("The PDF export omits Projects — make sure LinkedIn lists " + ", ".join(names) + ".")
        li_only = [x for x in profile.experience if not any(_same_org(re.split(r'\s{3,}', e.get('title', ''))[0], x.org or x.title) for e in r_exp)]
        if li_only:
            c.details["linkedin_only"] = [x.org or x.title for x in li_only]
        score = 20 * max(0.0, 1 - problems / max(1, len(r_exp) + 1)) if r_exp else 20 - 5 * (problems > 0)
        checks.append(c.finish(score, "LinkedIn matches your resume." if problems == 0 else
                               f"{plural(int(problems + 0.5), 'mismatch', 'mismatches')} between LinkedIn and your resume."))

    # L5 skills -----------------------------------------------------------------------------
    c = Check("L5", "Skills listed and relevant to target role", "Skills", 15,
              why="Recruiters filter LinkedIn search by skills. Skills that match the role put you in their results.")
    role_id = role_from_text(ctx.get("target_role"))
    gap = role_gap(role_id, skills)
    resume_skills = (resume or {}).get("skills", [])
    if not profile.skills and not skills:
        c.fixes.append("Add a Skills section with 10–15 relevant skills.")
        checks.append(c.finish(0, "No skills listed."))
    else:
        n_listed = len(profile.skills)
        count_score = 7 if (n_listed >= 5 or profile.top_skills_only) else 7 * n_listed / 5
        rel = gap["coverage"]
        score = count_score + 8 * rel
        missing = gap["missing_core"] + [g[0] for g in gap["missing_any_of"]]
        in_resume_not_li = [s for s in resume_skills if s not in skills][:8]
        if profile.top_skills_only:
            c.evidence.append(Evidence(text=f"Top skills: {', '.join(profile.skills)}"))
            weights = role_skill_weights(role_id)
            off_role = [s for s in profile.skills if s not in weights]
            better = [s for s in dict.fromkeys(resume_skills + skills) if s in weights and s not in profile.skills][:3] \
                or [s for s in ROLES[role_id]["core"] if s not in profile.skills][:3]
            if off_role:
                c.fixes.append(f"Your top skills include {', '.join(off_role)}; pin role-relevant ones instead "
                               f"(e.g. {', '.join(better)}).")
        if missing:
            c.fixes.append(f"For {gap['role']} roles, add (if you have them): {', '.join(missing[:6])}.")
        if in_resume_not_li:
            c.fixes.append(f"Skills on your resume but not on LinkedIn: {', '.join(in_resume_not_li)} — add them.")
        c.details = {"skills": skills, "coverage": rel, "missing_for_role": missing}
        checks.append(c.finish(score, f"{plural(n_listed, 'skill')} listed; {round(rel * 100)}% coverage of core {gap['role']} skills."))

    # L6 custom URL ---------------------------------------------------------------------------
    c = Check("L6", "Custom profile URL", "Profile", 10,
              why="linkedin.com/in/firstname-lastname looks professional on a resume; random numbers look auto-generated.")
    if not profile.handle:
        c.fixes.append("Include your profile URL (Contact info → profile link) so we can check it.")
        checks.append(c.na("Profile URL not found in the export/text."))
    else:
        auto = bool(re.search(r"-[0-9a-f]{6,}$|\d{5,}$|-[a-z0-9]{8,}$", profile.handle))
        name_part = re.sub(r"[^a-z]", "", (profile.name or "").lower().split(" ")[0]) if profile.name else ""
        if auto:
            base = re.sub(r"-[0-9a-f]{6,}$|-?\d{5,}$|-[a-z0-9]{8,}$", "", profile.handle)
            c.evidence.append(Evidence(text=f"linkedin.com/in/{profile.handle}"))
            c.fixes.append(f"Edit your public profile URL to linkedin.com/in/{base or name_part} (Profile → Edit public profile & URL).")
            checks.append(c.finish(4, "Your URL has an auto-generated suffix."))
        else:
            checks.append(c.finish(10, f"Clean custom URL: linkedin.com/in/{profile.handle}"))

    # L7 completeness ---------------------------------------------------------------------------
    c = Check("L7", "Education and basics complete", "Profile", 5,
              why="Campus recruiters filter by college, degree and graduation year.")
    score = 0
    if profile.education:
        score += 3
    else:
        c.fixes.append("Add your college, degree and graduation year under Education.")
    if profile.location:
        score += 1
    else:
        c.fixes.append("Add your city (recruiters search by location).")
    if profile.certifications or profile.honors:
        score += 1
    else:
        c.fixes.append("Add Licenses & Certifications or Honors & Awards (hackathons, NPTEL, AWS).")
    checks.append(c.finish(score, "Education, location and credentials present." if score >= 5 else f"{5 - score} basics missing."))

    score = total_score(checks)
    return {
        "benchmark_version": BENCHMARK_VERSION,
        "score": score,
        "checks": [c.to_dict() for c in checks],
        "summary": _summary(score, checks),
        "rewrites": {"headline": options, "about": draft,
                     "skills_to_add": (role_gap(role_id, skills)["missing_core"] + role_gap(role_id, skills)["missing_nice"])[:8]},
        "extracted": profile.to_dict(),
    }
