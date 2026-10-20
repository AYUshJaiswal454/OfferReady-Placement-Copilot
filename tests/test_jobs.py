"""Job search: boolean queries, permitted sources only, dedupe, ranking relevance and explanations."""
from __future__ import annotations

import asyncio
import unittest

from tests import evaluate
from tests.support import fresh_environment


class BooleanQueries(unittest.TestCase):
    def match(self, q, text):
        from app.jobs.boolean import evaluate as ev, parse

        return ev(parse(q), text.lower())

    def test_precedence_not_and_or(self):
        q = 'React OR Angular AND NOT senior'
        self.assertTrue(self.match(q, "React developer, senior role"))      # React OR (Angular AND NOT senior)
        self.assertFalse(self.match(q, "Angular senior engineer"))
        self.assertTrue(self.match(q, "Angular intern"))

    def test_phrases_brackets_and_implicit_and(self):
        q = '("machine learning" OR "deep learning") python intern'
        self.assertTrue(self.match(q, "Machine Learning intern, Python required"))
        self.assertFalse(self.match(q, "Python intern for learning machines"))

    def test_bad_query_is_reported_not_crashing(self):
        from app.jobs.boolean import QueryError, parse

        with self.assertRaises(QueryError):
            parse('(React OR "Node.js" AND')

    def test_query_built_from_profile(self):
        from app.jobs.boolean import build_query

        q = build_query(["React", "Node.js", "MongoDB", "Git"], "Full Stack Developer", "internship", ["Bangalore", "Remote"])
        self.assertIn("React", q["query"])
        self.assertIn("intern", q["query"].lower())
        self.assertIn("Bengaluru", q["query"])           # city aliases are expanded
        self.assertNotIn("Git ", q["query"])             # generic tools don't drive the search


class Relevance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = evaluate.job_matching()

    def test_top_results_are_relevant(self):
        self.assertGreaterEqual(self.result["mean_precision_at_5"], 0.8)
        self.assertGreaterEqual(self.result["mean_good_match_precision"], 0.9)

    def test_every_result_explains_why(self):
        for row in self.result["rows"]:
            self.assertTrue(row["all_have_reasons"], row["role"])
            self.assertGreaterEqual(row["deep_links"], 5)


class SourcesAndDedupe(unittest.TestCase):
    def test_cross_source_duplicates_merge(self):
        r = evaluate.dedupe_check()
        self.assertEqual(r["stored"], 2)
        merged = next(x for x in r["rows"] if "Backend" in x["title"])
        self.assertTrue(merged["also_on"])

    def test_no_scraping_connectors_for_restricted_sites(self):
        from app.jobs.connectors import REGISTRY

        for name in REGISTRY:
            for banned in ("linkedin", "naukri", "indeed", "internshala", "wellfound", "glassdoor"):
                self.assertNotIn(banned, name)

    def test_restricted_sites_get_deep_links_only(self):
        from app.jobs.connectors import deep_links

        links = {d["site"]: d["url"] for d in deep_links({"keywords": "react developer"}, ["Bengaluru"], "internship")}
        self.assertTrue(links["LinkedIn Jobs"].startswith("https://www.linkedin.com/jobs/search/"))
        self.assertIn("Naukri", links)

    def test_robots_txt_is_respected(self):
        import http.server
        import threading

        from app.jobs import connectors
        from app.net import http as nethttp

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):  # noqa: N802
                body = b"User-agent: *\nDisallow: /private/\n" if self.path == "/robots.txt" else b"<rss></rss>"
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        fresh_environment()
        nethttp._client = None
        connectors._robots.clear()
        try:
            self.assertTrue(asyncio.run(connectors.robots_allowed(base + "/feed.xml")))
            connectors._robots.clear()
            nethttp._client = None
            self.assertFalse(asyncio.run(connectors.robots_allowed(base + "/private/feed.xml")))
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main()
