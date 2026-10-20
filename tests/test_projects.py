"""GitHub repository analysis, secret scanning and live-link checks on known fixtures."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests import evaluate


class RepoAnalysis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = evaluate.repo_checks()

    def test_ten_repos_all_expectations_met(self):
        self.assertEqual(self.result["repos"], 10)
        failures = [(r["repo"], [e for e in r["expectations"] if not e["ok"]]) for r in self.result["rows"] if not r["all_ok"]]
        self.assertEqual(failures, [])

    def test_secret_values_are_never_shown(self):
        for r in self.result["rows"]:
            self.assertEqual(r["unredacted_values"], 0, r["repo"])
            for rule, severity, redacted in r["secrets"]:
                self.assertTrue("…" in redacted or "****" in redacted, (r["repo"], rule, redacted))


class SecretScanner(unittest.TestCase):
    def test_placeholders_are_not_secrets(self):
        from app.review.secrets_scan import scan_repo

        root = Path(tempfile.mkdtemp())
        (root / ".env.example").write_text("OPENAI_API_KEY=your-api-key-here\nJWT_SECRET=changethis\n", encoding="utf-8")
        (root / "config.js").write_text("const key = process.env.API_KEY;\n", encoding="utf-8")
        res = scan_repo(root)
        self.assertEqual(res["high"], 0, res["findings"])


class ProjectReview(unittest.TestCase):
    def test_missing_repo_gives_actionable_message(self):
        from app.review.project_review import review_project

        r = review_project({"name": "Ghost", "repo_url": "https://github.com/nobody/ghost"}, None, None,
                           "Repository not found or private. Make sure the repo exists and is public.")
        readme = next(c for c in r["checks"] if c["id"] == "PR1")
        self.assertEqual(readme["status"], "fail")
        self.assertTrue(any("public" in f.lower() for f in readme["fixes"]))


class LiveLinks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = evaluate.live_link_checks()

    def test_all_link_cases(self):
        failures = [(r["case"], r["results"], r["error"]) for r in self.result["rows"] if not r["all_ok"]]
        self.assertEqual(failures, [])

    def test_errors_are_human_readable(self):
        for r in self.result["rows"]:
            if r["error"]:
                self.assertNotIn("net::", r["error"])
                self.assertNotIn("Page.goto", r["error"])


if __name__ == "__main__":
    unittest.main()
