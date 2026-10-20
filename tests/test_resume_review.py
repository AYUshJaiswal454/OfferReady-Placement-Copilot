"""Resume review: accuracy against the labelled corpus, consistency, and the behaviour of individual checks."""
from __future__ import annotations

import unittest

from tests import evaluate
from tests.support import RESUMES, ensure_resume_corpus


class ResumeAccuracy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = evaluate.resume_accuracy()

    def test_twenty_resumes(self):
        self.assertEqual(self.result["resumes"], 20)

    def test_precision_and_recall(self):
        r = self.result
        missed = [(row["file"], row["missed"]) for row in r["rows"] if row["missed"]]
        extra = [(row["file"], row["extra"]) for row in r["rows"] if row["extra"]]
        self.assertGreaterEqual(r["recall"], 0.95, f"missed: {missed}")
        self.assertGreaterEqual(r["precision"], 0.95, f"false alarms: {extra}")

    def test_clean_resume_scores_high(self):
        clean = next(row for row in self.result["rows"] if not row["defects"])
        self.assertGreaterEqual(clean["score"], 95)

    def test_worse_resumes_score_lower(self):
        rows = {row["file"]: row for row in self.result["rows"]}
        # resume_19 has typos + weak bullets + two pages; it must score well below the clean resume_01.
        self.assertLess(rows["resume_19.pdf"]["score"], rows["resume_01.pdf"]["score"] - 15)


class ResumeConsistency(unittest.TestCase):
    def test_scores_stable_over_five_runs(self):
        r = evaluate.resume_consistency(runs=5, files=["resume_01.pdf", "resume_07.pdf", "resume_13.pdf", "resume_19.pdf"])
        self.assertLessEqual(r["max_spread"], 3.0)
        self.assertTrue(r["all_verdicts_identical"])


class ResumeChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.intake.resume_parser import parse_resume_pdf
        from app.review.resume_checks import review_resume

        ensure_resume_corpus()

        def review(name):
            return review_resume(parse_resume_pdf((RESUMES / name).read_bytes(), ocr=True), name, "Full Stack Developer")

        cls.review = staticmethod(review)

    def checks(self, name):
        return {c["id"]: c for c in self.review(name)["checks"]}

    def test_every_check_has_benchmark_fields(self):
        for c in self.review("resume_19.pdf")["checks"]:
            self.assertIn(c["status"], ("pass", "warn", "fail", "na"))
            self.assertTrue(c["title"] and c["why"], c["id"])
            if c["status"] in ("fail", "warn"):
                self.assertTrue(c["fixes"], f"{c['id']} fails without a specific fix")

    def test_two_pages_flagged_with_cut_suggestions(self):
        c = self.checks("resume_02.pdf")["R1"]
        self.assertEqual(c["status"], "fail")
        self.assertTrue(any(w in f.lower() for f in c["fixes"] for w in ("drop", "compress", "cut", "remove", "shorten")), c["fixes"])

    def test_typos_are_located_with_suggestions(self):
        c = self.checks("resume_06.pdf")["R3.1"]
        self.assertIn(c["status"], ("fail", "warn"))
        self.assertTrue(c["evidence"])
        ev = c["evidence"][0]
        self.assertIsNotNone(ev.get("page"))
        self.assertTrue(ev.get("bbox"), "typo evidence should carry a bounding box for the highlight")

    def test_missing_links_flagged(self):
        self.assertEqual(self.checks("resume_10.pdf")["R5"]["status"], "fail")

    def test_two_column_layout_flagged_for_ats(self):
        self.assertIn(self.checks("resume_13.pdf")["R8.4"]["status"], ("fail", "warn"))

    def test_skills_in_image_found_by_ocr(self):
        c = self.checks("resume_12.pdf")["R8.2"]
        self.assertIn(c["status"], ("fail", "warn"))

    def test_rewrites_never_invent_numbers(self):
        import re

        r = self.review("resume_07.pdf")
        self.assertTrue(r["weak_bullets"])
        for b in r["weak_bullets"]:
            suggestion = (b.get("suggestion") or "").split("e.g.")[0]     # an illustrative example may contain numbers
            original_numbers = set(re.findall(r"\d+", b["text"]))
            new_numbers = set(re.findall(r"\d+", suggestion))
            self.assertTrue(new_numbers <= original_numbers, (b["text"], b.get("suggestion")))


class SpellingSuggestions(unittest.TestCase):
    def test_confident_suggestions(self):
        from app.review.spelling import find_misspellings

        found = {m["word"]: m.get("suggestion") for m in find_misspellings("Implemented a scalabel API and recieved feedback.")}
        self.assertEqual(found.get("scalabel"), "scalable")
        self.assertEqual(found.get("recieved"), "received")

    def test_tech_words_and_british_spelling_accepted(self):
        from app.review.spelling import find_misspellings

        text = "Optimised PostgreSQL queries with Redis, Kubernetes and FastAPI; organised a hackathon."
        self.assertEqual(find_misspellings(text), [])


if __name__ == "__main__":
    unittest.main()
