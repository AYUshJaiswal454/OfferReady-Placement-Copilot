"""Mock interview: simulated candidates in offline (rules), OpenAI-API and Ollama modes."""
from __future__ import annotations

import asyncio
import unittest

from tests import evaluate
from tests.support import fresh_environment


class RulesModeInterviews(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = evaluate.interview_personas("rules")
        cls.by = {r["persona"]: r for r in cls.result["rows"]}

    def test_all_complete_with_transcript_and_score(self):
        for r in self.result["rows"]:
            self.assertEqual(r["status"], "completed", r["persona"])
            self.assertTrue(r["has_transcript"])
            self.assertIsNotNone(r["score"])
            self.assertEqual(set(r["dimensions"]), {"technical", "projects", "problem_solving", "communication", "behavioural"})

    def test_scores_separate_strong_from_weak(self):
        self.assertTrue(self.result["ordering_ok"], {k: v["score"] for k, v in self.by.items()})
        self.assertGreaterEqual(self.by["strong"]["score"], 70)
        self.assertLessEqual(self.by["weak"]["score"], 40)

    def test_strong_candidate_uses_most_of_the_time(self):
        self.assertGreaterEqual(self.by["strong"]["minutes_used"], 10)
        self.assertLessEqual(self.by["strong"]["minutes_used"], 15.5)

    def test_off_topic_answers_are_redirected_and_cost_points(self):
        self.assertGreaterEqual(self.by["rambler"]["redirects"], 2)
        self.assertLess(self.by["rambler"]["score"], self.by["strong"]["score"] - 20)

    def test_prompt_injection_is_flagged_and_not_rewarded(self):
        inj = self.by["injector"]
        self.assertIn("injection_attempt", inj["flags"])
        self.assertLess(inj["score"], self.by["strong"]["score"])

    def test_weak_areas_are_specific(self):
        for r in self.result["rows"]:
            self.assertTrue(r["weak_areas"], r["persona"])
            self.assertTrue(all(":" in w and len(w) > 40 for w in r["weak_areas"]), r["weak_areas"])


class ApiAndOllamaModes(unittest.TestCase):
    """The same five interviews through the OpenAI and the Ollama code paths (local stub API, same wire protocol)."""

    def check_mode(self, mode):
        r = evaluate.interview_personas(mode)
        for row in r["rows"]:
            self.assertEqual(row["provider"], mode)
            self.assertEqual(row["status"], "completed", row)
            self.assertEqual(row["scorer"], mode)
            self.assertEqual(row["scorer_runs"], 3)      # median of three scoring runs
        self.assertGreater(r["llm_calls"], 5 * 10)
        self.assertTrue(r["ordering_ok"], [(x["persona"], x["score"]) for x in r["rows"]])
        inj = next(x for x in r["rows"] if x["persona"] == "injector")
        self.assertIn("injection_attempt", inj["flags"])

    def test_openai_mode(self):
        self.check_mode("openai")

    def test_ollama_mode(self):
        self.check_mode("ollama")


class InterviewEngine(unittest.TestCase):
    def setUp(self):
        fresh_environment()

    def test_time_limit_is_enforced(self):
        """A candidate who talks forever still gets a closed interview within the time limit."""
        from app.db import get_db
        from app.interview import service as iv
        from tests.interview_personas import _shift_clock

        user, _ = evaluate._interview_user("Long Talker")
        st = iv.start(user, "text", 15, "mock", "deterministic")
        db = get_db()
        done = False
        for _ in range(60):
            _shift_clock(st["interview_id"], 75)
            row = db.fetchone("SELECT * FROM interviews WHERE id = ?", (st["interview_id"],))
            if row["status"] != "live":
                done = True
                break
            res = asyncio.run(iv.take_turn(row, user, "Let me explain in detail. " * 40))
            if res.get("done"):
                done = True
                break
        self.assertTrue(done)
        last = db.fetchone("SELECT MAX(t_ms) m FROM interview_turns WHERE interview_id = ?", (st["interview_id"],))["m"]
        self.assertLessEqual(last / 60000, 16.5)

    def test_questions_come_from_resume_projects_and_role(self):
        from app.interview.engine import build_plan

        plan = build_plan({"target_role": "Backend Developer"}, {"skills": ["Java", "Spring Boot", "SQL"]},
                          [{"name": "PayFlow", "tech": ["Spring Boot", "PostgreSQL"]}], 15, seed=3)
        phases = {p["key"]: p for p in plan["phases"]}
        self.assertIn("PayFlow", phases["projects"]["items"][0]["question"])
        self.assertTrue(all(i["type"] == "tech" for i in phases["technical"]["items"]))
        self.assertTrue(phases["hr"]["items"])
        self.assertEqual(plan["phases"][0]["items"][0]["id"], "HR001")

    def test_twenty_minute_plan_is_longer(self):
        from app.interview.engine import build_plan

        p15 = build_plan({"target_role": "SDE"}, None, [], 15, seed=1)
        p20 = build_plan({"target_role": "SDE"}, None, [], 20, seed=1)
        n = lambda p: sum(len(ph["items"]) for ph in p["phases"])  # noqa: E731
        self.assertGreater(n(p20), n(p15))

    def test_scoring_is_consistent(self):
        r = evaluate.interview_scoring_consistency(runs=5)
        self.assertLessEqual(r["spread"], 3.0)

    def test_dont_know_moves_on_politely(self):
        from app.interview.engine import keyword_assess

        self.assertEqual(keyword_assess("Sorry, I don't know this one.", {"type": "tech", "key_points": ["queue"]})["assessment"],
                         "dont_know")


if __name__ == "__main__":
    unittest.main()
