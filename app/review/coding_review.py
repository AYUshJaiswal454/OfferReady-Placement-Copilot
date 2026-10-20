"""Coding practice (LeetCode / Codeforces) and co-curricular achievements components.

LeetCode: its public GraphQL endpoint (the same data shown on the public profile page),
queried once per refresh with a strict per-host rate limit; can be disabled with
LEETCODE_ENABLED=false, in which case students enter their stats manually.
Codeforces: official public API (https://codeforces.com/apiHelp).
"""
from __future__ import annotations

import json
import re
import time

from ..config import get_settings
from ..net.http import client, get_json_cached, limiter
from .common import Check, Evidence, plural, total_score

BENCHMARK_VERSION = "coding-2026.10"
LEETCODE_QUERY = """
query userProfile($username: String!) {
  matchedUser(username: $username) {
    username
    submitStatsGlobal { acSubmissionNum { difficulty count } }
    profile { ranking }
    userCalendar { streak totalActiveDays submissionCalendar }
  }
  userContestRanking(username: $username) { attendedContestsCount rating topPercentage }
}"""


class CodingProfileError(Exception):
    pass


def parse_handle(value: str, platform: str) -> str:
    v = value.strip().rstrip("/")
    if platform == "leetcode":
        v = re.sub(r"^(https?://)?(www\.)?leetcode\.com/(u/)?", "", v, flags=re.I)
    elif platform == "codeforces":
        v = re.sub(r"^(https?://)?(www\.)?codeforces\.com/profile/", "", v, flags=re.I)
    v = v.split("/")[0].lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9_.\-]{2,40}", v):
        raise CodingProfileError("PERMANENT: That doesn't look like a valid username.")
    return v


async def fetch_leetcode(username: str) -> dict:
    if not get_settings().leetcode_enabled:
        raise CodingProfileError("PERMANENT: LeetCode fetching is disabled here; enter your stats manually.")
    await limiter.wait("leetcode.com", 0.5)
    resp = await client().post("https://leetcode.com/graphql", json={"query": LEETCODE_QUERY, "variables": {"username": username}},
                               headers={"referer": f"https://leetcode.com/u/{username}/", "content-type": "application/json"})
    if resp.status_code != 200:
        raise CodingProfileError(f"LeetCode returned HTTP {resp.status_code}")
    data = (resp.json() or {}).get("data") or {}
    user = data.get("matchedUser")
    if not user:
        raise CodingProfileError(f"PERMANENT: LeetCode user '{username}' not found (is the profile public?).")
    counts = {row["difficulty"].lower(): row["count"] for row in user["submitStatsGlobal"]["acSubmissionNum"]}
    contest = data.get("userContestRanking") or {}
    calendar = {}
    try:
        calendar = json.loads((user.get("userCalendar") or {}).get("submissionCalendar") or "{}")
    except ValueError:
        pass
    cutoff = time.time() - 90 * 86400
    active_90 = sum(1 for ts, n in calendar.items() if int(ts) >= cutoff and n > 0)
    return {
        "platform": "leetcode", "username": username, "url": f"https://leetcode.com/u/{username}/",
        "solved": counts.get("all", 0), "easy": counts.get("easy", 0), "medium": counts.get("medium", 0),
        "hard": counts.get("hard", 0), "ranking": (user.get("profile") or {}).get("ranking"),
        "contests": contest.get("attendedContestsCount") or 0, "rating": round(contest.get("rating") or 0),
        "top_percent": contest.get("topPercentage"), "active_days_90": active_90,
        "streak": (user.get("userCalendar") or {}).get("streak"),
    }


async def fetch_codeforces(handle: str) -> dict:
    st, info = await get_json_cached(f"https://codeforces.com/api/user.info?handles={handle}", max_age_s=3600, rate=0.5)
    if st != 200 or not isinstance(info, dict) or info.get("status") != "OK":
        raise CodingProfileError(f"PERMANENT: Codeforces handle '{handle}' not found.")
    user = info["result"][0]
    _, rating = await get_json_cached(f"https://codeforces.com/api/user.rating?handle={handle}", max_age_s=3600, rate=0.5)
    _, status = await get_json_cached(f"https://codeforces.com/api/user.status?handle={handle}&from=1&count=2000",
                                      max_age_s=3600, rate=0.5)
    solved = set()
    active = set()
    cutoff = time.time() - 90 * 86400
    for sub in (status or {}).get("result", []) if isinstance(status, dict) else []:
        if sub.get("verdict") == "OK":
            prob = sub.get("problem", {})
            solved.add(f"{prob.get('contestId')}{prob.get('index')}")
            if sub.get("creationTimeSeconds", 0) >= cutoff:
                active.add(time.strftime("%Y-%m-%d", time.gmtime(sub["creationTimeSeconds"])))
    contests = len((rating or {}).get("result", [])) if isinstance(rating, dict) else 0
    return {
        "platform": "codeforces", "username": handle, "url": f"https://codeforces.com/profile/{handle}",
        "solved": len(solved), "rating": user.get("rating") or 0, "max_rating": user.get("maxRating") or 0,
        "rank": user.get("rank"), "contests": contests, "active_days_90": len(active),
    }


def _piecewise(x: float, points: list[tuple[float, float]]) -> float:
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


def review_coding(profiles: list[dict]) -> dict:
    """profiles: fetched or manually entered stats for LeetCode/Codeforces/others."""
    checks: list[Check] = []
    lc = next((p for p in profiles if p.get("platform") == "leetcode"), None)
    cf = next((p for p in profiles if p.get("platform") == "codeforces"), None)
    total_solved = sum(p.get("solved") or 0 for p in profiles)

    c = Check("C1", "Problems solved", "Practice", 40, effort="long",
              why="Most campus coding rounds are DSA problems; volume of practice is the best predictor of clearing them.")
    c.details = {"total": total_solved, "by_platform": {p["platform"]: p.get("solved") for p in profiles}}
    score = _piecewise(total_solved, [(0, 0), (50, 12), (150, 26), (300, 36), (500, 40)])
    if total_solved < 150:
        c.fixes.append(f"You've solved {total_solved}. Target 150+ (then 300): ~2 problems a day for 10 weeks gets you there. "
                       "Follow a topic list (arrays → hashing → two pointers → trees → graphs → DP).")
    elif total_solved < 300:
        c.fixes.append(f"{total_solved} solved is good; push to 300 with more medium problems.")
    checks.append(c.finish(score, f"{total_solved} problems solved."))

    c = Check("C2", "Difficulty mix", "Practice", 20, effort="long",
              why="Interview problems are mostly medium; only-easy practice doesn't transfer.")
    if lc and lc.get("solved"):
        harder = (lc.get("medium") or 0) + (lc.get("hard") or 0)
        ratio = harder / max(1, lc["solved"])
        c.details = {"easy": lc.get("easy"), "medium": lc.get("medium"), "hard": lc.get("hard"), "medium_hard_ratio": round(ratio, 2)}
        if ratio < 0.5:
            c.fixes.append(f"Only {round(100 * ratio)}% of your LeetCode solves are medium/hard; aim for at least 50%.")
        checks.append(c.finish(20 * min(1, ratio / 0.5), f"{lc.get('easy', 0)} easy, {lc.get('medium', 0)} medium, {lc.get('hard', 0)} hard."))
    elif cf and cf.get("rating"):
        checks.append(c.finish(20 * min(1, (cf.get("max_rating") or cf["rating"]) / 1400), f"Codeforces max rating {cf.get('max_rating')}."))
    else:
        checks.append(c.na("No difficulty breakdown available."))

    c = Check("C3", "Contest participation", "Practice", 20, effort="long",
              why="Timed contests build the speed you need in online assessments.")
    contests = sum(p.get("contests") or 0 for p in profiles)
    best = max([p.get("rating") or 0 for p in profiles] + [0])
    c.details = {"contests": contests, "best_rating": best}
    score = 20 if contests >= 5 or (lc and (lc.get("rating") or 0) >= 1600) or (cf and (cf.get("max_rating") or 0) >= 1400) \
        else (10 + 2 * contests if contests else 0)
    if contests < 5:
        c.fixes.append("Take part in weekly LeetCode or Codeforces contests (aim for 5+), then upsolve the problems you missed.")
    checks.append(c.finish(score, f"{plural(contests, 'contest')} attended" + (f", rating {best}." if best else ".")))

    c = Check("C4", "Consistent recent practice", "Practice", 20, effort="long",
              why="Steady practice beats last-minute cramming before placement season.")
    known = [p for p in profiles if p.get("active_days_90") is not None]
    if not known:
        checks.append(c.na("No activity data (manual entry)."))
    else:
        active = max(p["active_days_90"] for p in known)
        c.details = {"active_days_last_90": active}
        if active < 30:
            c.fixes.append(f"Active on {active} of the last 90 days. Practice at least 3 days a week.")
        checks.append(c.finish(20 * min(1, active / 30), f"Active on {active} of the last 90 days."))

    if not profiles:
        for ch in checks:
            ch.score, ch.status = 0, "fail"
    score = total_score(checks)
    return {"benchmark_version": BENCHMARK_VERSION, "score": score, "checks": [c.to_dict() for c in checks],
            "summary": f"Coding practice score {score:.0f}/100.", "extracted": {"profiles": profiles}}


ACH_CATEGORIES = {
    "hackathon": re.compile(r"hackathon|ideathon|codathon|buildathon|sih\b|smart india", re.I),
    "competitive_programming": re.compile(r"icpc|codechef|codeforces|leetcode|contest|olympiad|kick ?start|code ?jam|rated", re.I),
    "leadership": re.compile(r"\b(lead|led|head|president|secretary|captain|coordinator|founder|organi[sz]|core team|"
                             r"chair|convenor|representative|ambassador|mentor)", re.I),
    "certification": re.compile(r"certif|nptel|coursera|udemy|aws certified|google cloud certified|azure|course", re.I),
    "open_source": re.compile(r"open[- ]source|gsoc|hacktoberfest|contribut(ed|or) to|pull request|lfx|mlh fellowship", re.I),
    "research": re.compile(r"paper|publication|published|journal|conference|ieee|springer|research", re.I),
    "sports_cultural": re.compile(r"sports|cricket|football|chess|music|dance|drama|debate|quiz|ncc|nss|art", re.I),
}
RESULT_RE = re.compile(r"\b(won|winner|1st|2nd|3rd|first|second|third|top\s?\d+|rank(ed)?\s?#?\d+|finalist|runner[- ]up|"
                       r"gold|silver|bronze|prize|award|qualified|selected)\b", re.I)


def review_achievements(items: list[str]) -> dict:
    cats: dict[str, list[str]] = {}
    for it in items:
        for cat, pattern in ACH_CATEGORIES.items():
            if pattern.search(it):
                cats.setdefault(cat, []).append(it)
    with_result = [it for it in items if RESULT_RE.search(it)]
    c = Check("A1", "Co-curricular achievements", "Achievements", 100, effort="long",
              why="Hackathons, contests, leadership and certifications separate students with similar grades.")
    score = min(100, 22 * len(cats) + (12 if with_result else 0) + (6 if len(items) >= 4 else 0))
    c.details = {"categories": {k: len(v) for k, v in cats.items()}, "with_results": len(with_result), "items": len(items)}
    for it in items[:6]:
        c.evidence.append(Evidence(text=it[:140]))
    missing = [k for k in ("hackathon", "leadership", "competitive_programming", "certification", "open_source") if k not in cats]
    labels = {"hackathon": "a hackathon (even reaching the finals counts)", "leadership": "a club/fest/team role",
              "competitive_programming": "a coding contest result", "certification": "a relevant certification (NPTEL/AWS/Google)",
              "open_source": "an open-source contribution (Hacktoberfest, GSoC)"}
    if missing:
        c.fixes.append("Add evidence of: " + "; ".join(labels[m] for m in missing[:3]) + ".")
    if items and not with_result:
        c.fixes.append("State results: rank, prize, 'finalist out of N teams', rating.")
    if not items:
        c.fixes.append("Add your achievements in the chat or in an 'Achievements' section on your resume.")
    c.finish(score, f"{plural(len(items), 'achievement')} across {plural(len(cats), 'category', 'categories')}.")
    return {"benchmark_version": "achievements-2026.10", "score": float(round(score, 1)), "checks": [c.to_dict()],
            "summary": c.summary, "extracted": {"items": items, "categories": list(cats)}}
