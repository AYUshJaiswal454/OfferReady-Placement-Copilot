"""Per-project review: documentation, live link, code quality, secrets, commits, structure, tests."""
from __future__ import annotations

import re

from ..skills import extract_skills
from .common import Check, Evidence, plural, total_score
from .livelink import summarize

BENCHMARK_VERSION = "project-2026.10"
LANG_SKILL = {"JavaScript": {"JavaScript", "React", "Node.js", "Express.js", "Next.js", "Vue.js", "Angular"},
              "TypeScript": {"TypeScript", "React", "Next.js", "Angular", "Node.js", "NestJS"},
              "Python": {"Python", "Django", "Flask", "FastAPI", "Machine Learning", "Pandas", "PyTorch", "TensorFlow"},
              "Java": {"Java", "Spring Boot"}, "Kotlin": {"Kotlin", "Android"}, "Dart": {"Dart", "Flutter"},
              "Go": {"Go"}, "C++": {"C++"}, "C#": {"C#", "ASP.NET"}, "PHP": {"PHP", "Laravel"}, "Jupyter Notebook": {"Python",
              "Machine Learning", "Pandas", "Jupyter"}, "HTML": {"HTML", "CSS", "JavaScript"}, "Swift": {"Swift", "iOS"}}


def review_project(project: dict, repo: dict | None, live: dict | None, repo_error: str | None = None) -> dict:
    """project: {name, repo_url, live_url, description, tech}; repo: analyze_repo() output; live: check_live_link() output."""
    name = project.get("name") or "Project"
    checks: list[Check] = []
    has_repo = repo is not None

    def no_repo(c: Check) -> Check:
        if project.get("repo_url"):
            c.fixes.append(f"We couldn't open the repository ({repo_error or 'unknown error'}). Make it public and re-run the review.")
        else:
            c.fixes.append("Add the GitHub repository link for this project.")
        return c.finish(0, "No repository to check.")

    # PR1 README ----------------------------------------------------------------------------
    c = Check("PR1", "README with setup steps and screenshots", "Documentation", 20,
              why="A README is how a recruiter understands your project in 30 seconds and how anyone can run it.")
    if not has_repo:
        checks.append(no_repo(c))
    else:
        rd = repo["readme"]
        if not rd.get("present"):
            c.fixes.append("Add a README.md: one-line pitch, screenshot/GIF, live link, tech stack, and 'Getting started' "
                           "commands (clone, install, env vars, run).")
            checks.append(c.finish(0, "No README."))
        else:
            score = 5
            if rd.get("default_template"):
                c.evidence.append(Evidence(text="README is the framework's default template", label="Template"))
                c.fixes.append("Replace the auto-generated README (Create React App / Vite / Next.js) with your own.")
            elif rd["words"] >= 80:
                score += 3
            else:
                c.fixes.append(f"README has only {rd['words']} words — describe what the project does, who it's for and how it works.")
            if rd.get("has_setup"):
                score += 7
            else:
                c.fixes.append("Add a 'Getting started' section with the exact commands to install and run it "
                               "(e.g. `npm install` / `pip install -r requirements.txt`, then the run command).")
            if rd.get("screenshots"):
                score += 5
            else:
                c.fixes.append("Add 1–2 screenshots or a short GIF of the app working (put them in /docs or /assets).")
            if not rd.get("live_links") and project.get("live_url"):
                c.fixes.append(f"Put the live link at the top of the README: {project['live_url']}")
            c.details = {k: rd.get(k) for k in ("words", "has_setup", "commands", "screenshots", "live_links")}
            checks.append(c.finish(score, "README is complete." if score >= 18 else f"README scores {score}/20."))

    # PR2-PR4 live link --------------------------------------------------------------------------
    s = summarize(live) if live else None
    c = Check("PR2", "Live link opens without errors", "Live", 15,
              why="A broken live link is worse than none: it is the first thing an interviewer clicks.")
    if not project.get("live_url"):
        c.fixes.append("Deploy the project and add the live link (free options: Vercel/Netlify for frontends, Render/Railway "
                       "for APIs, Streamlit Cloud or Hugging Face Spaces for ML demos).")
        checks.append(c.finish(0, "No live link."))
    elif not live:
        checks.append(c.na("Live link not checked yet."))
    else:
        d = live["desktop"]
        score = 0.0
        if d.get("error"):
            c.evidence.append(Evidence(text=d["error"], label="Unreachable"))
            c.fixes.append(f"The live link {project['live_url']} doesn't open: {d['error']} Redeploy it or update the link.")
        elif (d.get("status") or 0) >= 400:
            c.evidence.append(Evidence(text=f"HTTP {d['status']} at {d.get('final_url')}", label="HTTP error"))
            c.fixes.append(f"The live link returns HTTP {d['status']}. Check the deployment logs and the URL.")
        elif live.get("placeholder"):
            c.evidence.append(Evidence(text=live["placeholder"], label="Placeholder"))
            c.fixes.append(live["placeholder"])
            score = 5
        else:
            score = 10
            errs = d.get("console_errors") or []
            failed = [f for f in d.get("failed_requests") or [] if f.get("status", 500) >= 400 or f.get("error")]
            for e in errs[:3]:
                c.evidence.append(Evidence(text=f"Console error: {e[:160]}", label="JS error"))
            for f in failed[:3]:
                c.evidence.append(Evidence(text=f"Failed to load {f['url']} ({f.get('status') or f.get('error')})", label="Asset"))
            if not errs and not failed:
                score += 5
            else:
                score += 2 if len(errs) + len(failed) <= 2 else 0
                c.fixes.append("Open the browser console on your live site and fix the errors shown above "
                               "(missing files, failing API calls, undefined variables).")
            if (d.get("load_ms") or 0) > 6000:
                c.fixes.append(f"The page took {d['load_ms'] / 1000:.1f}s to load; compress images and lazy-load heavy parts.")
        if live.get("spa_refresh_404"):
            c.fixes.append("Deep links 404 on refresh: add a SPA rewrite (Netlify `_redirects`: `/* /index.html 200`, "
                           "or `rewrites` in vercel.json).")
        c.details = {"status": d.get("status"), "load_ms": d.get("load_ms"), "engine": live.get("engine"),
                     "console_errors": len(d.get("console_errors") or [])}
        checks.append(c.finish(score, "Live site loads cleanly." if score >= 14 else "Live site has problems."))

    c = Check("PR3", "Live site works on mobile", "Live", 5,
              why="Many recruiters open links on their phone first.")
    if not project.get("live_url") or not live or live["desktop"].get("error"):
        checks.append(c.na("No working live link to test on mobile."))
    else:
        m = live.get("mobile") or {}
        if m.get("skipped"):
            ok = bool(live["desktop"].get("viewport_meta"))
            if not ok:
                c.fixes.append("Add <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"> to your HTML head.")
            checks.append(c.finish(3 if ok else 0, "Viewport meta present (full mobile render not available)." if ok
                                   else "No mobile viewport meta tag."))
        else:
            problems = []
            if not m.get("viewport_meta"):
                problems.append("no viewport meta tag (the page renders zoomed-out on phones)")
                c.fixes.append("Add <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">.")
            if (m.get("overflow_px") or 0) > 4:
                problems.append(f"content is {m['overflow_px']}px wider than the screen")
                c.fixes.append("Fix horizontal scrolling on mobile: avoid fixed widths (use max-width: 100%, flex-wrap, "
                               "and responsive breakpoints).")
            if m.get("body_font_px") and m["body_font_px"] < 12:
                problems.append(f"text is {m['body_font_px']:.0f}px")
                c.fixes.append("Use at least 14–16px body text on mobile.")
            c.evidence.extend(Evidence(text=p, label="Mobile") for p in problems)
            checks.append(c.finish(5 - 2.5 * len(problems), "Works on a phone-sized screen." if not problems
                                   else "Mobile issues: " + "; ".join(problems) + "."))

    c = Check("PR4", "Live site matches what the resume/README claims", "Live", 5,
              why="Interviewers check that the link shows the project you describe, not another site.")
    claims = (live or {}).get("claims") or {}
    verdict = claims.get("verdict")
    if not verdict or verdict == "unknown":
        checks.append(c.na("Not enough description to compare against the live page."))
    else:
        c.details = claims
        if verdict == "mismatch":
            c.evidence.append(Evidence(text=f"The page doesn't mention {', '.join(claims.get('checked_terms', [])[:5])}", label="Mismatch"))
            c.fixes.append("The live link seems to point to a different site. Check you linked the right deployment.")
        elif verdict == "partial":
            c.fixes.append("Make the live page clearly show the project name and its main feature on the first screen.")
        checks.append(c.finish({"match": 5, "partial": 3, "mismatch": 0}[verdict],
                               {"match": "Live page matches the description.", "partial": "Live page partly matches.",
                                "mismatch": "Live page doesn't match the description."}[verdict]))

    # PR5 code quality -----------------------------------------------------------------------------
    c = Check("PR5", "Readable, well-structured code", "Code", 20, effort="medium",
              why="Interviewers open your main files. Long functions, debug prints and hard-coded URLs signal unfinished work.")
    if not has_repo:
        checks.append(no_repo(c))
    else:
        code = repo["code"]
        score = 20.0
        for f in code["long_files"][:3]:
            score -= 2
            c.evidence.append(Evidence(text=f"{f['file']} has {f['lines']} lines", label="Long file"))
        for f in code["long_functions"][:3]:
            score -= 2
            c.evidence.append(Evidence(text=f"{f['file']}:{f['line']} {f['name']}() is {f['lines']} lines", label="Long function"))
        if code["long_files"] or code["long_functions"]:
            c.fixes.append("Split long files/functions into smaller ones with clear names (aim for functions under ~40 lines).")
        if code["debug_prints"] > 5:
            score -= 2
            c.fixes.append(f"Remove {code['debug_prints']} leftover console.log/print debug statements (use a logger).")
        if code["commented_code"] > 10:
            score -= 2
            c.fixes.append("Delete commented-out code — git history keeps it.")
        for h in code["hardcoded_localhost"][:1]:
            score -= 3
            c.evidence.append(Evidence(text=f"{h['file']}:{h['line']} calls http://localhost", label="Hard-coded URL"))
            c.fixes.append("Replace hard-coded localhost API URLs with an environment variable (e.g. VITE_API_URL) — "
                           "otherwise the deployed site calls your laptop.")
        if code["deep_nesting"]:
            score -= 2
            c.fixes.append("Reduce deep nesting with early returns and helper functions.")
        if code["todos"] > 10:
            score -= 1
        if code["source_files"] == 0:
            score = 0
            c.fixes.append("No source code found in the repository.")
        c.details = {k: code[k] for k in ("languages", "source_files", "lines", "debug_prints", "todos", "main_files")}
        llm = repo.get("llm_review")
        if llm:
            c.details["ai_review"] = llm
            for comment in (llm.get("comments") or [])[:5]:
                c.evidence.append(Evidence(text=f"{comment.get('file')}:{comment.get('line')} — {comment.get('issue')}",
                                           label=f"AI review ({comment.get('severity', 'info')})", suggestion=comment.get("suggestion")))
        checks.append(c.finish(score, f"Code quality heuristics: {score:.0f}/20 across {plural(code['source_files'], 'source file')}."))

    # PR6 secrets -----------------------------------------------------------------------------
    c = Check("PR6", "No secrets committed", "Security", 15,
              why="A leaked API key can be abused within minutes of being pushed, and it is an instant red flag in interviews.")
    if not has_repo:
        checks.append(no_repo(c))
    else:
        sec = repo["secrets"]
        for f in sec["findings"][:8]:
            where = f"{f['file']}:{f['line']}" + (f" (commit {f['commit']})" if f.get("commit") else "")
            c.evidence.append(Evidence(text=f"{f['title']} in {where}: {f['redacted']}", label=f["severity"],
                                       suggestion=f.get("note") or None))
        if sec["high"]:
            c.fixes.append("Rotate (revoke and re-create) every leaked key NOW — deleting the file is not enough, it stays in git history.")
            c.fixes.append("Remove it from history with `git filter-repo --invert-paths --path <file>` or BFG, then force-push.")
            c.fixes.append("Load secrets from environment variables, add .env to .gitignore, and commit a .env.example.")
            checks.append(c.finish(0, f"{plural(sec['high'], 'high-risk secret')} committed."))
        elif sec["count"]:
            c.fixes.append("Move hard-coded tokens/passwords into environment variables.")
            checks.append(c.finish(7, f"{plural(sec['count'], 'possible secret')} found."))
        else:
            checks.append(c.finish(15, "No secrets found in the code or recent history."))

    # PR7 commits -----------------------------------------------------------------------------
    c = Check("PR7", "Meaningful commit history", "Git", 10,
              why="Commit messages show how you work. 'update' x20 or one 'Add files via upload' suggests copied code.")
    if not has_repo:
        checks.append(no_repo(c))
    else:
        cm = repo["commits"]
        ratio_score = min(1.0, cm["ratio"] / 0.7)
        volume = min(1.0, cm["count"] / 5)
        score = 10 * ratio_score * (0.5 + 0.5 * volume)
        if cm["web_uploads"]:
            score -= 3
            c.evidence.append(Evidence(text="Code was uploaded through GitHub's web UI ('Add files via upload')", label="Upload"))
            c.fixes.append("Commit from your machine in small steps with git, so the history shows how you built it.")
        if cm["junk_examples"]:
            c.evidence.append(Evidence(text="Vague messages: " + ", ".join(f"\"{m}\"" for m in cm["junk_examples"][:4]), label="Commits"))
            c.fixes.append("Write messages that say what changed and why, e.g. 'Add JWT login and signup routes' or "
                           "'fix(chat): reconnect socket after network drop'.")
        if cm["count"] < 5:
            c.fixes.append(f"Only {plural(cm['count'], 'commit')} — commit as you build (each feature or fix separately).")
        c.details = {k: cm[k] for k in ("count", "meaningful", "ratio", "conventional", "active_days", "web_uploads")}
        checks.append(c.finish(score, f"{cm['meaningful']} of {plural(cm['count'], 'recent commit')} have meaningful messages."))

    # PR8 structure ------------------------------------------------------------------------------
    c = Check("PR8", "Clean folder structure", "Git", 5, why="A tidy repo is easier to read; committed dependencies and build output look careless.")
    if not has_repo:
        checks.append(no_repo(c))
    else:
        st = repo["structure"]
        score = 5.0
        for j in st["junk"]:
            score -= 2
            c.evidence.append(Evidence(text=f"Committed {j['what']} ({j['count']} files, e.g. {j['example']})", label="Junk"))
        if st["junk"]:
            c.fixes.append("Delete committed dependencies/build output (`git rm -r --cached node_modules dist`) and add them to .gitignore.")
        if not st["gitignore"]:
            score -= 1
            c.fixes.append("Add a .gitignore (GitHub has templates for Node, Python, Java…).")
        if st["root_source_files"] > 12 and not st["organized"]:
            score -= 2
            c.fixes.append(f"{st['root_source_files']} source files sit in the root — group them into folders (src/, components/, routes/…).")
        checks.append(c.finish(score, "Clean structure." if score >= 4.5 else "Structure needs cleanup."))

    # PR9 tests ----------------------------------------------------------------------------------
    c = Check("PR9", "Tests or CI where reasonable", "Git", 5, why="Even a few tests show engineering maturity, and they're a great interview talking point.")
    if not has_repo:
        checks.append(no_repo(c))
    elif repo["code"]["lines"] < 300:
        checks.append(c.na("Small project — tests are optional."))
    else:
        t = repo["tests"]
        score = (3 if t["test_files"] else 0) + (2 if t["ci"] else 0)
        if not t["test_files"]:
            c.fixes.append("Add a few tests for your core logic (Jest/Vitest for JS, pytest for Python, JUnit for Java).")
        if not t["ci"]:
            c.fixes.append("Add a GitHub Actions workflow that runs the tests on every push.")
        checks.append(c.finish(score, f"{plural(t['test_files'], 'test file')}; CI {'configured' if t['ci'] else 'not configured'}."))

    insights = []
    if has_repo and project.get("tech"):
        repo_langs = set(repo["code"]["languages"])
        claimed = set(project.get("tech") or [])
        supported = set().union(*(LANG_SKILL.get(l, set()) for l in repo_langs)) if repo_langs else set()
        lang_claims = {t for t in claimed if t in {"JavaScript", "TypeScript", "Python", "Java", "Kotlin", "Go", "C++", "C#",
                                                    "PHP", "Dart", "Swift", "React", "Node.js", "Django", "Flask", "Spring Boot",
                                                    "FastAPI", "Next.js", "Flutter"}}
        unsupported = sorted(t for t in lang_claims if t not in supported)
        if repo_langs and unsupported and len(unsupported) >= max(1, len(lang_claims) // 2):
            insights.append({"kind": "stack_mismatch", "title": "Claimed stack vs repository",
                             "text": f"The resume lists {', '.join(unsupported)} for {name}, but the repo is "
                                     f"{', '.join(list(repo_langs)[:3])}. Make sure the claim and the code agree."})
    score = total_score(checks)
    return {
        "benchmark_version": BENCHMARK_VERSION,
        "score": score,
        "checks": [c.to_dict() for c in checks],
        "summary": f"{name}: {score:.0f}/100.",
        "insights": insights,
        "project": {k: project.get(k) for k in ("name", "repo_url", "live_url", "description", "tech")},
        "live": {k: v for k, v in (live or {}).items() if k not in ("desktop", "mobile")} | (
            {"status": live["desktop"].get("status"), "title": live["desktop"].get("title"),
             "load_ms": live["desktop"].get("load_ms")} if live else {}),
    }


def project_from_resume_entry(entry: dict) -> dict:
    """Turn a parsed resume project into a project source (links detected from the PDF)."""
    title = entry.get("title", "")
    name = re.split(r"\s*\|\s*|\s{3,}", title)[0].strip()
    repo = next((l for l in entry.get("links", []) if re.search(r"github\.com/[^/]+/[^/]+", l)), None)
    live = next((l for l in entry.get("links", []) if not re.search(r"github\.com|gitlab\.com|linkedin\.com|mailto:", l)), None)
    desc = " ".join(entry.get("bullets", []))
    return {"name": name, "repo_url": repo, "live_url": live, "description": desc,
            "tech": entry.get("tech") or extract_skills(desc)}
