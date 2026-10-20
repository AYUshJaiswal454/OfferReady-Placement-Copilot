"""GitHub profile review via the official REST/GraphQL APIs (public data only).

We never ask for the student's GitHub login. An optional server-side token
(GITHUB_TOKEN_FOR_REVIEWS) only raises the rate limit and enables pinned repos and the
contribution calendar, both of which are public on the profile page anyway.
"""
from __future__ import annotations

import base64
import re
from collections import Counter
from datetime import timedelta

from ..config import get_settings
from ..db import parse_iso, utcnow
from ..net.http import client, get_json_cached
from .common import Check, Evidence, plural, total_score

BENCHMARK_VERSION = "github-2026.10"
USERNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
DEFAULT_PROFILE_README = re.compile(r"(Hi there 👋|<!--\s*\*\*\w+/\w+\*\* is a ✨ _special_ ✨ repository|"
                                    r"Here are some ideas to get you started)", re.I)


class GitHubError(Exception):
    pass


class RateLimited(GitHubError):
    pass


def parse_username(value: str) -> str:
    v = value.strip().rstrip("/")
    v = re.sub(r"^(https?://)?(www\.)?github\.com/", "", v, flags=re.I).split("/")[0].lstrip("@")
    if not USERNAME_RE.match(v):
        raise GitHubError("That doesn't look like a GitHub username.")
    return v


def parse_repo(url: str) -> tuple[str, str] | None:
    m = re.search(r"github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9._-]+?)(?:\.git)?(?:/|$|#|\?)", url.strip() + "/")
    if not m:
        return None
    return m.group(1), m.group(2)


def _headers() -> dict:
    h = {"accept": "application/vnd.github+json", "x-github-api-version": "2022-11-28"}
    token = get_settings().github_token
    if token:
        h["authorization"] = f"Bearer {token}"
    return h


async def gh_get(path: str, max_age_s: int = 900) -> tuple[int, object]:
    url = get_settings().github_api_url.rstrip("/") + path
    status, body = await get_json_cached(url, headers=_headers(), max_age_s=max_age_s, rate=8.0)
    if status in (403, 429) and isinstance(body, dict) and "rate limit" in str(body.get("message", "")).lower():
        raise RateLimited("GitHub API rate limit reached; the review will retry automatically.")
    return status, body


async def gh_graphql(query: str, variables: dict) -> dict | None:
    token = get_settings().github_token
    if not token:
        return None
    url = get_settings().github_api_url.rstrip("/") + "/graphql"
    resp = await client().post(url, json={"query": query, "variables": variables},
                               headers={"authorization": f"Bearer {token}"})
    if resp.status_code != 200:
        return None
    data = resp.json()
    return data.get("data")


PROFILE_QUERY = """
query($login: String!) {
  user(login: $login) {
    pinnedItems(first: 6, types: REPOSITORY) { nodes { ... on Repository { name description url stargazerCount
      primaryLanguage { name } } } }
    contributionsCollection { contributionCalendar { totalContributions
      weeks { contributionDays { date contributionCount } } } }
  }
}"""


async def fetch_profile(username: str) -> dict:
    status, user = await gh_get(f"/users/{username}")
    if status == 404:
        raise GitHubError(f"PERMANENT: GitHub user '{username}' not found.")
    if status != 200:
        raise GitHubError(f"GitHub API returned {status} for /users/{username}")
    _, repos = await gh_get(f"/users/{username}/repos?per_page=100&type=owner&sort=updated")
    repos = repos if isinstance(repos, list) else []
    readme_text = ""
    st, readme = await gh_get(f"/repos/{username}/{username}/readme")
    if st == 200 and isinstance(readme, dict) and readme.get("content"):
        try:
            readme_text = base64.b64decode(readme["content"]).decode("utf-8", errors="ignore")
        except ValueError:
            readme_text = ""
    _, events = await gh_get(f"/users/{username}/events/public?per_page=100", max_age_s=1800)
    events = events if isinstance(events, list) else []
    gql = await gh_graphql(PROFILE_QUERY, {"login": username})
    pinned = None
    calendar = None
    if gql and gql.get("user"):
        pinned = [n for n in gql["user"]["pinnedItems"]["nodes"] if n]
        weeks = gql["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
        calendar = [d for w in weeks for d in w["contributionDays"]]
    return {"user": user, "repos": repos, "profile_readme": readme_text, "events": events, "pinned": pinned, "calendar": calendar}


def activity_weeks(data: dict, weeks: int = 12) -> tuple[int, int, str]:
    """Number of active weeks in the last `weeks` weeks, total contributions, and the data source used."""
    cutoff = utcnow() - timedelta(weeks=weeks)
    active: set[int] = set()
    total = 0
    if data.get("calendar"):
        for day in data["calendar"]:
            d = parse_iso(day["date"] + "T00:00:00+00:00")
            if d and d >= cutoff and day["contributionCount"] > 0:
                active.add((d - cutoff).days // 7)
                total += day["contributionCount"]
        return len(active), total, "contribution calendar"
    for ev in data.get("events", []):
        d = parse_iso(ev.get("created_at"))
        if not d or d < cutoff:
            continue
        if ev.get("type") in ("PushEvent", "PullRequestEvent", "CreateEvent", "IssuesEvent", "PullRequestReviewEvent"):
            active.add((d - cutoff).days // 7)
            total += int((ev.get("payload") or {}).get("size", 1) or 1)
    return len(active), total, "public events (last 90 days)"


def review_github_profile(data: dict, ctx: dict | None = None) -> dict:
    ctx = ctx or {}
    user = data["user"]
    repos = [r for r in data["repos"] if not r.get("archived")]
    own = [r for r in repos if not r.get("fork")]
    forks = [r for r in repos if r.get("fork")]
    login = user.get("login", "")
    checks: list[Check] = []

    # G1 profile README
    c = Check("G1", "Profile README", "Profile", 20, why="A profile README is the first thing on your GitHub page — "
              "use it to say what you build, your stack and your best projects.")
    text = data.get("profile_readme") or ""
    if not text:
        c.fixes.append(f"Create a public repo named '{login}' with a README.md: 2-line intro, tech stack, 3 featured "
                       "projects with links, and how to reach you.")
        checks.append(c.finish(0, "No profile README."))
    else:
        words = len(re.findall(r"\w+", re.sub(r"<[^>]+>|!\[[^\]]*\]\([^)]+\)", " ", text)))
        default = bool(DEFAULT_PROFILE_README.search(text)) and words < 120
        score = 20 if words >= 80 and not default else (10 if words >= 30 else 5)
        if default:
            c.fixes.append("Your profile README is still GitHub's template — replace it with your own intro and projects.")
        elif words < 80:
            c.fixes.append("Expand the profile README: what you're focused on, your stack, and links to 2–3 best projects.")
        if not re.search(r"\]\(https?://|https?://", text):
            c.fixes.append("Link your best projects (repo + live demo) from the profile README.")
            score = min(score, 15)
        checks.append(c.finish(score, f"Profile README present ({words} words)." if score >= 18 else "Profile README needs work."))

    # G2 pinned repos
    c = Check("G2", "Pinned repositories", "Profile", 15, why="Pinned repos are your portfolio; without pins GitHub "
              "shows random popular or recent repos.")
    pinned = data.get("pinned")
    if pinned is None:
        top = sorted(own, key=lambda r: (r.get("stargazers_count", 0), r.get("pushed_at") or ""), reverse=True)[:4]
        c.fixes.append("Pin your 3–6 best repositories (Profile → Customize your pins). Suggested: "
                       + ", ".join(r["name"] for r in top) + ".")
        checks.append(c.na("Pinned repos can only be read with a GitHub token; please confirm you have pinned 3+ repos."))
    else:
        n = len(pinned)
        c.details["pinned"] = [p["name"] for p in pinned]
        if n < 3:
            c.fixes.append(f"You have {plural(n, 'pinned repo')}; pin at least 3 of your best projects.")
        undescribed = [p["name"] for p in pinned if not p.get("description")]
        if undescribed:
            c.fixes.append("Add a one-line description to pinned repos: " + ", ".join(undescribed) + ".")
        score = 15 * min(1, n / 3) - (2 if undescribed else 0)
        checks.append(c.finish(score, f"{plural(n, 'pinned repository', 'pinned repositories')}."))

    # G3 activity
    c = Check("G3", "Regular commit activity", "Activity", 25, effort="long",
              why="Recruiters look for steady activity. A burst before placements and nothing else looks like cramming.")
    weeks, total, source = activity_weeks(data)
    c.details = {"active_weeks_of_12": weeks, "contributions": total, "source": source}
    if weeks < 6:
        c.fixes.append(f"You were active in {weeks} of the last 12 weeks. Aim for at least one meaningful commit "
                       "every week — small improvements to your projects count.")
    score = 25 * min(1, weeks / 6)
    checks.append(c.finish(score, f"Active in {weeks} of the last 12 weeks ({total} contributions, from {source})."))

    # G4 profile basics
    c = Check("G4", "Profile completeness", "Profile", 10, why="Name, photo, bio and a link make your profile look owned.")
    score = 0
    parts = {"name": bool(user.get("name")), "bio": bool(user.get("bio")), "avatar": "avatars" in (user.get("avatar_url") or "")
             and not user.get("gravatar_id") == "default", "location": bool(user.get("location")),
             "link": bool(user.get("blog")) or bool(user.get("twitter_username"))}
    score += 3 if parts["name"] else 0
    score += 3 if parts["bio"] else 0
    score += 2 if parts["location"] else 0
    score += 2 if parts["link"] else 0
    for k, v in parts.items():
        if not v and k != "avatar":
            c.fixes.append({"name": "Set your full name on GitHub.", "bio": "Add a one-line bio: role + stack (e.g. 'Backend dev · Java · Spring Boot').",
                            "location": "Add your city.", "link": "Add your portfolio or LinkedIn URL to the profile."}[k])
    c.details = parts
    checks.append(c.finish(score, "Profile basics complete." if score >= 9 else f"{sum(not v for k, v in parts.items() if k != 'avatar')} profile fields missing."))

    # G5 repo hygiene
    c = Check("G5", "Repositories are described", "Repositories", 15, why="Descriptions and topics make repos "
              "understandable at a glance and searchable.")
    if not own:
        c.fixes.append("Publish your projects as public repositories.")
        checks.append(c.finish(0, "No original public repositories."))
    else:
        described = [r for r in own if r.get("description")]
        topics = [r for r in own if r.get("topics")]
        ratio = len(described) / len(own)
        score = 10 * ratio + 5 * min(1, len(topics) / max(1, min(len(own), 3)))
        missing = [r["name"] for r in own if not r.get("description")][:6]
        if missing:
            c.fixes.append("Add a one-line description to: " + ", ".join(missing) + ".")
        if len(topics) < min(3, len(own)):
            c.fixes.append("Add topics (e.g. react, nodejs, machine-learning) to your main repos.")
        checks.append(c.finish(score, f"{len(described)} of {plural(len(own), 'repo')} have a description; {len(topics)} have topics."))

    # G6 original work
    c = Check("G6", "Original projects (not just forks)", "Repositories", 15, effort="long",
              why="Forks and tutorial clones don't show your ability; original repos with real commits do.")
    substantial = [r for r in own if (r.get("size") or 0) >= 50]
    score = 15 * min(1, len(substantial) / 3)
    if len(substantial) < 3:
        c.fixes.append(f"You have {plural(len(substantial), 'substantial original repo')}; build up to 3 real projects.")
    if forks and len(forks) > len(own):
        c.fixes.append(f"{len(forks)} of your repos are forks; archive or hide forks you didn't contribute to.")
        score -= 3
    c.details = {"original": len(own), "forks": len(forks), "substantial": len(substantial),
                 "languages": dict(Counter(r.get("language") for r in own if r.get("language")).most_common(6))}
    checks.append(c.finish(score, f"{plural(len(own), 'original repo')}, {plural(len(forks), 'fork')}."))

    score = total_score(checks)
    return {
        "benchmark_version": BENCHMARK_VERSION,
        "score": score,
        "checks": [c.to_dict() for c in checks],
        "summary": f"GitHub profile score {score:.0f}/100.",
        "extracted": {
            "login": login, "name": user.get("name"), "bio": user.get("bio"), "public_repos": user.get("public_repos"),
            "followers": user.get("followers"), "avatar_url": user.get("avatar_url"), "html_url": user.get("html_url"),
            "top_repos": [{"name": r["name"], "url": r["html_url"], "description": r.get("description"),
                           "language": r.get("language"), "stars": r.get("stargazers_count", 0), "pushed_at": r.get("pushed_at"),
                           "homepage": r.get("homepage")}
                          for r in sorted(own, key=lambda r: r.get("pushed_at") or "", reverse=True)[:8]],
            "pinned": [p["name"] for p in (data.get("pinned") or [])],
        },
    }
