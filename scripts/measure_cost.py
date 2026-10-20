"""Measure the AI cost of one complete student journey.

Runs a full journey with the AI switched on (OpenAI API format, pointed at the local stub so no key is needed):
resume + LinkedIn + GitHub + 3 projects + coding + achievements reviewed, one complete 15-minute mock interview
scored three times, and ten chat questions. Input tokens are measured from the real prompts the app sends.
Output tokens are reported two ways: a ceiling (every call uses its full max_tokens budget, which on reasoning
models also caps reasoning tokens) and a typical estimate. Prices come from app/data/pricing.json.

    python scripts/measure_cost.py            -> prints a table and writes docs/data/cost.json
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.support import H, OfflineWeb, drain, ensure_resume_corpus, fresh_environment, RESUMES  # noqa: E402

# Typical completion sizes (tokens, including reasoning at the configured effort) observed for these prompts.
TYPICAL_OUTPUT = {"resume_rewrite": 650, "linkedin_rewrite": 600, "code_review": 900, "interview_turn": 160,
                  "interview_score": 1500, "chat_tools": 120, "chat": 350, "summary": 150}
CHAT_QUESTIONS = [
    "How should I prepare for a system design round as a fresher?",
    "Is it better to learn Docker or Kubernetes first?",
    "Write me a short message to ask a senior for a referral.",
    "Which of my projects should I talk about first in interviews?",
    "How do I explain a gap semester?",
    "Can you suggest a 2-week DSA plan?",
    "What should I put in my GitHub profile README?",
    "How do I answer 'tell me about yourself'?",
    "What salary should I expect for a fresher full stack role in Bengaluru?",
    "Give me three questions to ask the interviewer at the end.",
]


def main() -> None:
    from starlette.testclient import TestClient

    from tests import llm_stub
    from tests.interview_personas import simulate
    from tests.linkedin_factory import linkedin_pdf

    server, url = llm_stub.start()
    fresh_environment(llm_provider="openai", openai_api_key="sk-stub", openai_base_url=url, openai_model="gpt-6-luna",
                      openai_model_smart="gpt-6-luna")
    from app.db import get_db
    from app.interview import service as iv
    from app.main import create_app, seed

    ensure_resume_corpus()
    app = create_app(start_worker=False)
    seed()
    start_index = len(llm_stub.STATS["requests"])
    with OfflineWeb() as web, TestClient(app) as c:
        c.post("/api/auth/signup", json={"name": "Kabir Mehta", "email": "cost@student.msot.edu", "password": "password123",
                                         "batch_year": 2026, "branch": "CSE"}, headers=H)
        c.post("/api/me/consent", json={"accept": True}, headers=H)
        c.patch("/api/me", json={"target_role": "Full Stack Developer", "job_type": "internship"}, headers=H)
        c.post("/api/profile/resume", files={"file": ("cv.pdf", (RESUMES / "resume_07.pdf").read_bytes(), "application/pdf")}, headers=H)
        li = linkedin_pdf("Kabir Mehta", "Student at MSOT", "Bengaluru", "kabir-mehta-1a2b3c",
                          "I am a hardworking student passionate about technology.", ["Java", "Python"],
                          [{"org": "Fintrix Labs", "title": "Intern", "dates": "May 2025 - July 2025", "location": "Pune",
                            "description": "Built APIs."}], [{"school": "MSOT", "degree": "BTech CSE (2022 - 2026)"}], [])
        c.post("/api/profile/linkedin", files={"file": ("li.pdf", li, "application/pdf")}, headers=H)
        c.post("/api/profile/github", json={"username": "kabir-demo"}, headers=H)
        c.post("/api/profile/coding", json={"platform": "leetcode", "manual": {"solved": 212, "easy": 98, "medium": 96, "hard": 18,
                                                                                "contests": 4, "rating": 1612}}, headers=H)
        for name, repo in [("DevConnect", "good_fullstack"), ("ShopLite", "default_cra_readme"), ("CropDoc", "python_ml")]:
            c.post("/api/profile/projects", json={"name": name, "repo_url": f"https://github.com/kabir/{repo}",
                                                  "live_url": web.base + "/good", "description": name, "tech": ["React"]}, headers=H)
        c.post("/api/profile/achievements", json={"text": "Finalist, Smart India Hackathon 2025 internal round"}, headers=H)
        drain()
        db = get_db()
        user = db.fetchone("SELECT * FROM users WHERE email = 'cost@student.msot.edu'")
        st = iv.start(user, "text", 15, "openai", "gpt-6-luna")
        asyncio.run(simulate(st["interview_id"], user, "good", seed=11))
        drain()
        for q in CHAT_QUESTIONS:
            with c.stream("POST", "/api/chat", json={"message": q}, headers=H) as resp:
                "".join(resp.iter_text())
    server.shutdown()

    from app.llm.providers import PRICING

    calls = llm_stub.STATS["requests"][start_index:]
    by = defaultdict(lambda: {"calls": 0, "input": 0, "ceiling_output": 0, "typical_output": 0})
    for r in calls:
        f = "summary" if r["feature"] == "summary" else r["feature"]
        b = by[f]
        b["calls"] += 1
        b["input"] += r["prompt_tokens"]
        b["ceiling_output"] += r["max_tokens"]
        b["typical_output"] += min(r["max_tokens"] or 10**6, TYPICAL_OUTPUT.get(f, 200))
    # The fixture repositories are tiny; real projects fill the code-review excerpt cap (24,000 characters, about
    # 6,000 tokens per project), so code-review input is raised to that cap for the estimate.
    cr = by["code_review"]
    measured_cr = cr["input"]
    cr["input"] = max(cr["input"], cr["calls"] * 6000 + 250 * cr["calls"])
    totals = {k: sum(v[k] for v in by.values()) for k in ("calls", "input", "ceiling_output", "typical_output")}
    models = {}
    for model, price in PRICING["models"].items():
        typical = (totals["input"] * price["input"] + totals["typical_output"] * price["output"]) / 1e6
        ceiling = (totals["input"] * price["input"] + totals["ceiling_output"] * price["output"]) / 1e6
        models[model] = {"typical_usd": round(typical, 4), "ceiling_usd": round(ceiling, 4),
                         "typical_inr": round(typical * PRICING["usd_to_inr"], 2), "ceiling_inr": round(ceiling * PRICING["usd_to_inr"], 2)}
    audio = PRICING["audio_per_minute"]
    voice = {"candidate_speech_min": 7.5, "interviewer_speech_min": 4.5,
             "openai_voice_usd": round(7.5 * audio["gpt-4o-mini-transcribe"] + 4.5 * audio["gpt-4o-mini-tts"], 4),
             "browser_voice_usd": 0.0}
    out = {"journey": "resume + LinkedIn + GitHub + 3 projects + coding + achievements + one 15-min interview (3 scoring runs) + 10 chat questions",
           "features": dict(by), "totals": totals, "code_review_input_measured_on_fixtures": measured_cr, "per_model": models, "voice_interview_extra": voice,
           "ollama_usd": 0.0, "usd_to_inr": PRICING["usd_to_inr"], "pricing_source": PRICING.get("_source")}
    dest = ROOT / "docs" / "data"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "cost.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"{'feature':18s} {'calls':>5s} {'input tok':>10s} {'typical out':>12s} {'ceiling out':>12s}")
    for f, v in sorted(by.items(), key=lambda kv: -kv[1]["input"]):
        print(f"{f:18s} {v['calls']:5d} {v['input']:10d} {v['typical_output']:12d} {v['ceiling_output']:12d}")
    print(f"{'TOTAL':18s} {totals['calls']:5d} {totals['input']:10d} {totals['typical_output']:12d} {totals['ceiling_output']:12d}")
    for m, v in models.items():
        print(f"  {m:14s} typical ${v['typical_usd']:.4f} (₹{v['typical_inr']:.2f})   ceiling ${v['ceiling_usd']:.4f} (₹{v['ceiling_inr']:.2f})")
    print("voice extra (OpenAI STT+TTS):", voice["openai_voice_usd"])


if __name__ == "__main__":
    main()
