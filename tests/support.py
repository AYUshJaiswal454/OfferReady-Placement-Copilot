"""Shared helpers for the test suite (stdlib unittest; also runs under pytest).

Every test class gets its own temporary data directory and SQLite database, an app instance without the
background worker (tasks are drained inline), and the deterministic offline AI mode unless a test opts in
to a stub provider.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")

try:  # Starlette's TestClient needs httpx; some sandboxes ship a compatible fork under another name.
    import httpx  # noqa: F401
except ImportError:  # pragma: no cover
    import httpx2  # type: ignore

    sys.modules["httpx"] = httpx2

from starlette.testclient import TestClient  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
RESUMES = FIXTURES / "resumes"
H = {"X-Requested-With": "offerready"}


def fresh_environment(**overrides) -> Path:
    """Point the app at a brand-new data directory and database."""
    from app.config import reset_settings
    from app.db import reset_db

    data_dir = Path(tempfile.mkdtemp(prefix="offerready-test-"))
    os.environ["DATA_DIR"] = str(data_dir)
    os.environ["LLM_PROVIDER"] = overrides.pop("llm_provider", "mock")
    os.environ.pop("DATABASE_URL", None)
    reset_settings(data_dir=data_dir, llm_provider=os.environ["LLM_PROVIDER"], seed_demo=False, embedded_worker=False, **overrides)
    reset_db()
    return data_dir


def drain() -> int:
    import app.pipelines  # noqa: F401  (registers every task handler)
    from app.tasks import drain as _drain

    total = 0
    while True:
        n = asyncio.run(_drain(500))
        total += n
        if not n:
            return total


def ensure_resume_corpus() -> list[dict]:
    import json

    labels = RESUMES / "labels.json"
    if not labels.exists():
        from tests.resume_factory import build_corpus

        build_corpus(RESUMES)
    return json.loads(labels.read_text(encoding="utf-8"))


class AppTestCase(unittest.TestCase):
    """A running app (no worker thread) plus helpers to create signed-in students and admins."""

    settings_overrides: dict = {}

    @classmethod
    def setUpClass(cls) -> None:
        cls.data_dir = fresh_environment(**dict(cls.settings_overrides))
        from app.main import create_app, seed

        cls.app = create_app(start_worker=False)
        seed()
        cls._clients: list[TestClient] = []
        cls.web = OfflineWeb().__enter__()     # no test ever reaches GitHub or the internet

    @classmethod
    def tearDownClass(cls) -> None:
        cls.web.__exit__(None, None, None)
        for c in cls._clients:
            try:
                c.__exit__(None, None, None)
            except Exception:
                pass

    # ------------------------------------------------------------------ helpers
    def client(self) -> TestClient:
        c = TestClient(self.app)
        c.__enter__()
        self._clients.append(c)
        return c

    def student(self, name: str = "Asha Verma", email: str | None = None, consent: bool = True, **profile) -> TestClient:
        c = self.client()
        email = email or f"{name.split()[0].lower()}.{len(self._clients)}@student.msot.edu"
        r = c.post("/api/auth/signup", json={"name": name, "email": email, "password": "password123", "batch_year": 2026,
                                             "branch": "CSE"}, headers=H)
        self.assertEqual(r.status_code, 200, r.text)
        if consent:
            self.assertEqual(c.post("/api/me/consent", json={"accept": True}, headers=H).status_code, 200)
        if profile:
            self.assertEqual(c.patch("/api/me", json=profile, headers=H).status_code, 200)
        c.email = email  # type: ignore[attr-defined]
        return c

    def admin(self) -> TestClient:
        c = self.client()
        r = c.post("/api/auth/login", json={"email": "admin@msot.edu", "password": "admin12345"}, headers=H)
        self.assertEqual(r.status_code, 200, r.text)
        return c

    def upload_resume(self, c: TestClient, file: str = "resume_05.pdf") -> dict:
        ensure_resume_corpus()
        r = c.post("/api/profile/resume", files={"file": (file, (RESUMES / file).read_bytes(), "application/pdf")}, headers=H)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()


class OfflineWeb:
    """Route project reviews to local fixtures: GitHub clones -> fixture repos, live links -> the local test site.

    Use as a context manager in tests that upload resumes or add projects, so nothing depends on the internet.
    """

    def __enter__(self):
        import shutil
        import zlib

        from app.review import github_review, livelink, repo_analyzer
        from tests import site_server
        from tests.github_fixture import demo_github_profile
        from tests.repo_factory import build_all

        self.root = Path(tempfile.mkdtemp(prefix="fixture-repos-"))
        repos = build_all(self.root)
        names = sorted(repos)
        self.server, base = site_server.start()
        self._saved = (repo_analyzer.clone_repo, livelink.check_live_link, github_review.fetch_profile)
        real_live = livelink.check_live_link

        def clone(url, dest, depth=60, timeout=90):
            name = url.rstrip("/").removesuffix(".git").split("/")[-1]
            if name not in repos:
                name = names[zlib.crc32(url.encode()) % len(names)]
            shutil.copytree(repos[name]["path"], dest)
            return True, ""

        async def live(url, claims=None):
            if "127.0.0.1" not in url:
                url = base + "/good"
            return await real_live(url, claims)

        async def profile(username):
            return demo_github_profile(username)

        repo_analyzer.clone_repo, livelink.check_live_link, github_review.fetch_profile = clone, live, profile
        self.base = base
        return self

    def __exit__(self, *exc):
        from app.review import github_review, livelink, repo_analyzer

        repo_analyzer.clone_repo, livelink.check_live_link, github_review.fetch_profile = self._saved
        self.server.shutdown()
        return False
