"""Readiness formula and the AI provider adapter (OpenAI / Ollama / offline)."""
from __future__ import annotations

import asyncio
import unittest

from tests.support import fresh_environment


class ReadinessFormula(unittest.TestCase):
    def test_weights_and_levels(self):
        from app.readiness.score import WEIGHTS, level_for

        self.assertEqual(sum(WEIGHTS.values()), 100)
        self.assertEqual(WEIGHTS, {"resume": 25, "projects": 25, "interview": 20, "github": 10, "coding": 10, "linkedin": 5,
                                   "achievements": 5})
        self.assertEqual(level_for(49.9), "Not ready")
        self.assertEqual(level_for(50), "Almost ready")
        self.assertEqual(level_for(74.9), "Almost ready")
        self.assertEqual(level_for(75), "Placement ready")

    def _user_with_reviews(self, reviews):
        from app.db import get_db, now_iso

        db = get_db()
        uid = db.insert("users", {"email": f"r{len(reviews)}@x.edu", "password_hash": "x", "name": "R", "role": "student",
                                  "created_at": now_iso(), "settings": {}})
        for kind, score, checks, sid in reviews:
            if sid:
                db.insert("profile_sources", {"id": sid, "user_id": uid, "kind": kind if kind != "project" else "project",
                                              "label": "p", "input": {}, "status": "ready", "created_at": now_iso(), "updated_at": now_iso()})
            db.insert("reviews", {"user_id": uid, "kind": kind, "source_id": sid, "score": score, "checks": checks, "data": {},
                                  "benchmark_version": "t", "created_at": now_iso()})
        return uid

    def test_score_is_exact_weighted_sum_and_actions_exact(self):
        from app.readiness.score import compute

        fresh_environment()
        checks = [{"id": "R1", "title": "One page", "max": 50, "score": 50, "status": "pass", "fixes": []},
                  {"id": "R2", "title": "Links", "max": 50, "score": 10, "status": "fail", "fixes": ["Add your GitHub link."]}]
        uid = self._user_with_reviews([("resume", 60.0, checks, None)])
        r = compute(uid)
        self.assertAlmostEqual(r["score"], 25 * 0.60, places=1)
        self.assertEqual(r["level"], "Not ready")
        link = next(a for a in r["all_actions"] if a["check_id"] == "R2")
        self.assertAlmostEqual(link["gain"], 25 * 40 / 100, places=2)        # weight x missing / sum of max
        self.assertLessEqual(len(r["top_actions"]), 5)
        missing = {a["component"] for a in r["all_actions"] if a["check_id"] == "MISSING"}
        self.assertEqual(missing, {"projects", "interview", "github", "coding", "linkedin", "achievements"})

    def test_one_fix_for_many_checks_is_one_action(self):
        from app.readiness.score import compute

        fresh_environment()
        fix = "Repository not found or private. Make sure the repo exists and is public."
        checks = [{"id": f"PR{i}", "title": f"Check {i}", "max": 10, "score": 0, "status": "fail", "fixes": [fix]} for i in range(1, 6)]
        uid = self._user_with_reviews([("project", 0.0, checks, 501), ("project", 80.0, [], 502)])
        r = compute(uid)
        same = [a for a in r["all_actions"] if a["detail"] == fix]
        self.assertEqual(len(same), 1)
        self.assertEqual(len(same[0]["also_fixes"]), 4)

    def test_history_is_recorded_over_time(self):
        from app.db import get_db
        from app.readiness.score import snapshot

        fresh_environment()
        uid = self._user_with_reviews([("resume", 50.0, [], None)])
        snapshot(uid)
        snapshot(uid)                    # unchanged -> no duplicate point
        get_db().insert("reviews", {"user_id": uid, "kind": "coding", "source_id": None, "score": 90, "checks": [], "data": {},
                                    "benchmark_version": "t", "created_at": "2026-10-01T00:00:00+00:00"})
        snapshot(uid)
        n = get_db().scalar("SELECT COUNT(*) FROM readiness_snapshots WHERE user_id = ?", (uid,))
        self.assertEqual(n, 2)


class ProviderAdapter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests import llm_stub

        cls.stub = llm_stub
        cls.server, cls.url = llm_stub.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def call(self, **kw):
        from app.llm.providers import chat

        return asyncio.run(chat([{"role": "user", "content": "Reply with the single word: ready"}], feature="settings_test",
                                cache=False, **kw))

    def test_unsupported_parameters_are_dropped_and_remembered(self):
        fresh_environment(llm_provider="openai", openai_api_key="sk-test", openai_base_url=self.url,
                          openai_model="gpt-6-luna-reject-temperature")
        before = self.stub.STATS["rejected_params"]
        self.assertEqual(self.call(temperature=0).text, "ready")
        self.assertEqual(self.call(temperature=0).text, "ready")
        self.assertEqual(self.stub.STATS["rejected_params"] - before, 1)     # learned after the first 400

    def test_rate_limits_are_retried(self):
        fresh_environment(llm_provider="openai", openai_api_key="sk-test", openai_base_url=self.url, openai_model="flaky-model")
        before = self.stub.STATS["throttled"]
        self.assertEqual(self.call().text, "ready")
        self.assertEqual(self.stub.STATS["throttled"] - before, 1)

    def test_ollama_mode_costs_nothing(self):
        from app.db import get_db

        fresh_environment(llm_provider="ollama", ollama_base_url=self.url, ollama_model="qwen2.5:7b-instruct")
        res = self.call()
        self.assertEqual(res.provider, "ollama")
        row = get_db().fetchone("SELECT provider, cost_usd, input_tokens FROM usage_ledger ORDER BY id DESC LIMIT 1")
        self.assertEqual(row["provider"], "ollama")
        self.assertEqual(row["cost_usd"], 0)
        self.assertGreater(row["input_tokens"], 0)

    def test_openai_cost_is_recorded(self):
        from app.db import get_db

        fresh_environment(llm_provider="openai", openai_api_key="sk-test", openai_base_url=self.url, openai_model="gpt-6-luna")
        self.call()
        row = get_db().fetchone("SELECT cost_usd FROM usage_ledger ORDER BY id DESC LIMIT 1")
        self.assertGreater(row["cost_usd"], 0)

    def test_provider_down_falls_back_to_rules(self):
        from app.llm.providers import chat

        fresh_environment(llm_provider="ollama", ollama_base_url="http://127.0.0.1:9/v1", ollama_model="x", llm_timeout_s=2)
        res = asyncio.run(chat([{"role": "user", "content": "hi"}], feature="t", mock=lambda: {"ok": True}, cache=False))
        self.assertEqual(res.provider, "mock")
        self.assertEqual(res.data, {"ok": True})

    def test_streaming_chat(self):
        from app.llm.providers import stream_chat

        fresh_environment(llm_provider="ollama", ollama_base_url=self.url, ollama_model="qwen2.5:7b-instruct")

        async def collect():
            return [c async for c in stream_chat([{"role": "system", "content": "Student snapshot (JSON): {}"},
                                                  {"role": "user", "content": "hello"}], feature="chat")]

        chunks = asyncio.run(collect())
        self.assertGreater(len(chunks), 3)

    def test_scores_never_depend_on_the_model(self):
        """Resume scores are identical with the AI on or off ('LLM writes, rules score')."""
        from app.intake.resume_parser import parse_resume_pdf
        from app.review.resume_checks import review_resume
        from tests.support import RESUMES, ensure_resume_corpus

        ensure_resume_corpus()
        data = (RESUMES / "resume_07.pdf").read_bytes()
        fresh_environment()
        a = review_resume(parse_resume_pdf(data), "r.pdf", "SDE")["score"]
        fresh_environment(llm_provider="openai", openai_api_key="sk-test", openai_base_url=self.url, openai_model="gpt-6-luna")
        b = review_resume(parse_resume_pdf(data), "r.pdf", "SDE")["score"]
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
