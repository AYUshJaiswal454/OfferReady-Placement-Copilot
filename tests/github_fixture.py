"""Offline stand-in for the GitHub REST/GraphQL responses of a fictional student account.

Used by the demo seed and the tests so the GitHub profile review can be exercised without network access.
Dates are generated relative to "now" so the activity check behaves the same on any day.
"""
from __future__ import annotations

from datetime import timedelta

from app.db import utcnow


def _iso(days_ago: float) -> str:
    return (utcnow() - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def demo_github_profile(login: str = "demo-msot", active_weeks: int = 5, readme_words: int = 60) -> dict:
    repos = [
        ("good_fullstack", "Real-time Q&A platform for student developers (React, Node.js, Socket.io)", "JavaScript", 4, 820, ["react", "nodejs", "socket-io"], "https://devconnect.example.com", 3),
        ("default_cra_readme", None, "JavaScript", 0, 410, [], None, 40),
        ("python_ml", "Crop disease detection from leaf images with a CNN", "Python", 2, 2300, ["pytorch", "computer-vision"], None, 12),
        ("dsa-practice", "Solutions to 200+ LeetCode problems in Java", "Java", 1, 160, [], None, 6),
        ("portfolio", None, "HTML", 0, 30, [], None, 120),
        ("awesome-python", "A curated list of Python frameworks (fork)", "Python", 0, 900, [], None, 400),
    ]
    out = []
    for i, (name, desc, lang, stars, size, topics, homepage, pushed) in enumerate(repos):
        out.append({"name": name, "full_name": f"{login}/{name}", "html_url": f"https://github.com/{login}/{name}", "description": desc,
                    "language": lang, "stargazers_count": stars, "size": size, "topics": topics, "homepage": homepage,
                    "fork": name == "awesome-python", "archived": False, "pushed_at": _iso(pushed), "id": 1000 + i})
    events = []
    for w in range(active_weeks):
        events.append({"type": "PushEvent", "created_at": _iso(w * 7 * 2 + 1), "payload": {"size": 3}})
    readme = " ".join(["Final-year CSE student at MSOT building full-stack apps with React and Node.js."] +
                      ["I enjoy shipping small tools for my college community."] * max(0, (readme_words - 12) // 9))
    return {
        "user": {"login": login, "name": "Kabir Mehta", "bio": None, "location": "Bengaluru", "blog": "", "twitter_username": None,
                 "avatar_url": "", "html_url": f"https://github.com/{login}", "public_repos": len(repos), "followers": 11},
        "repos": out,
        "profile_readme": readme,
        "events": events,
        "pinned": None,      # pinned repos need a GitHub token; the review marks the check n/a and suggests pins
        "calendar": None,
    }
