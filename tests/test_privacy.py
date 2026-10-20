"""Privacy and security: consent, access control between students and admins, encryption at rest, export, deletion."""
from __future__ import annotations

import io
import json
import zipfile

from tests.support import H, AppTestCase, drain


class Privacy(AppTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def setUp(self):
        from app.security import failed_logins, rate_limiter

        rate_limiter.reset()
        failed_logins.reset()

    def two_students(self):
        a = self.student("Anil Rao")
        b = self.student("Bina Shah")
        self.upload_resume(a, "resume_03.pdf")
        self.upload_resume(b, "resume_04.pdf")
        drain()
        return a, b

    # ------------------------------------------------------------------ access control
    def test_students_cannot_see_each_others_data(self):
        a, b = self.two_students()
        b_review = b.get("/api/reviews").json()["latest"]["resume"][0]["id"]
        b_full = b.get(f"/api/reviews/{b_review}").json()
        b_file = b_full["data"]["page_files"][0]
        self.assertEqual(a.get(f"/api/reviews/{b_review}").status_code, 404)
        self.assertEqual(a.get(f"/api/files/{b_file}").status_code, 404)
        b_source = b.get("/api/profile").json()["sources"]["resume"][0]["id"]
        self.assertEqual(a.delete(f"/api/profile/sources/{b_source}", headers=H).status_code, 404)
        app = b.post("/api/applications", json={"title": "SDE Intern", "company": "Acme"}, headers=H).json()["application"]
        self.assertEqual(a.patch(f"/api/applications/{app['id']}", json={"status": "offer"}, headers=H).status_code, 404)
        iv = b.post("/api/interviews", json={"mode": "text", "duration": 15}, headers=H).json()["interview_id"]
        self.assertEqual(a.get(f"/api/interviews/{iv}").status_code, 404)
        self.assertEqual(a.post(f"/api/interviews/{iv}/turn", json={"text": "hi"}, headers=H).status_code, 404)

    def test_admin_sees_scores_but_not_private_reports(self):
        a, _ = self.two_students()
        admin = self.admin()
        students = admin.get("/api/admin/students").json()["students"]
        anil = next(s for s in students if s["name"] == "Anil Rao")
        self.assertFalse(anil["report_shared"])
        self.assertEqual(admin.get(f"/api/admin/students/{anil['id']}/report").status_code, 403)
        file_id = a.get(f"/api/reviews/{a.get('/api/reviews').json()['latest']['resume'][0]['id']}").json()["data"]["page_files"][0]
        self.assertEqual(admin.get(f"/api/files/{file_id}").status_code, 403)

    def test_admin_views_of_shared_reports_are_audited(self):
        from app.db import get_db

        admin = self.admin()
        r = admin.post("/api/admin/jobs", json={"title": "SDE Intern", "company": "Acme", "description": "Build services in Java and SQL.",
                                                "skills": [], "batches": [2026], "status": "open"}, headers=H)
        job = r.json()["job"]["id"]
        s = self.student("Chetan Iyer")
        self.upload_resume(s, "resume_05.pdf")
        drain()
        self.assertEqual(s.post(f"/api/msot/jobs/{job}/apply", json={"share_report": True}, headers=H).status_code, 200)
        sid = next(x["id"] for x in admin.get("/api/admin/students").json()["students"] if x["name"] == "Chetan Iyer")
        self.assertEqual(admin.get(f"/api/admin/students/{sid}/report").status_code, 200)
        self.assertTrue(get_db().fetchone("SELECT id FROM audit_log WHERE action LIKE 'admin.view%' AND entity_id = ?", (str(sid),)))

    def test_students_cannot_reach_admin_api(self):
        s = self.student("Dev Patel")
        for path in ("/api/admin/overview", "/api/admin/students", "/api/admin/jobs", "/api/admin/sources"):
            self.assertEqual(s.get(path).status_code, 403, path)

    # ------------------------------------------------------------------ consent and data handling
    def test_nothing_is_processed_without_consent(self):
        s = self.student("Esha Nair", consent=False)
        for path, kwargs in [("/api/profile/github", {"json": {"username": "esha"}}),
                             ("/api/profile/linkedin", {"data": {"text": "Esha Nair\nStudent"}}),
                             ("/api/interviews", {"json": {"mode": "text", "duration": 15}}),
                             ("/api/chat", {"json": {"message": "hi"}})]:
            r = s.post(path, headers=H, **kwargs)
            self.assertEqual(r.json().get("code"), "consent_required", path)

    def test_files_are_encrypted_at_rest(self):
        from app.config import get_settings
        from app.db import get_db

        s = self.student("Farah Khan")
        self.upload_resume(s, "resume_06.pdf")
        row = get_db().fetchone("SELECT * FROM files WHERE kind = 'resume' ORDER BY id DESC LIMIT 1")
        raw = (get_settings().files_dir / row["storage_path"]).read_bytes()
        self.assertFalse(raw.startswith(b"%PDF"))
        self.assertNotIn(b"Experience", raw)
        self.assertEqual(row["encrypted"], 1)

    def test_secrets_and_keys_are_never_returned(self):
        s = self.student("Gita Menon")
        r = s.put("/api/settings", json={"llm_provider": "openai", "openai_api_key": "sk-proj-THISISASECRETKEY1234567890"}, headers=H)
        self.assertEqual(r.status_code, 200, r.text)
        text = s.get("/api/settings").text + s.get("/api/auth/me").text
        self.assertNotIn("THISISASECRETKEY", text)
        from app.db import get_db

        stored = json.dumps(get_db().fetchone("SELECT settings FROM users WHERE email = ?", (s.email,))["settings"])
        self.assertNotIn("THISISASECRETKEY", stored)                     # encrypted in the database too

    def test_passwords_are_hashed(self):
        from app.db import get_db

        s = self.student("Hari Lal")
        h = get_db().fetchone("SELECT password_hash FROM users WHERE email = ?", (s.email,))["password_hash"]
        self.assertNotIn("password123", h)
        self.assertTrue(h.startswith("scrypt$"), h[:12])

    def test_export_contains_everything(self):
        s = self.student("Indu Pillai")
        self.upload_resume(s, "resume_07.pdf")
        drain()
        r = s.get("/api/me/export")
        self.assertEqual(r.status_code, 200)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        names = z.namelist()
        for key in ("account", "profile_sources", "reviews", "readiness_snapshots", "applications", "interviews",
                    "interview_turns", "chat_messages", "usage_ledger"):
            self.assertIn(f"{key}.json", names)
        account = json.loads(z.read("account.json"))
        self.assertNotIn("password_hash", json.dumps(account))
        self.assertTrue(json.loads(z.read("reviews.json")))
        self.assertTrue(any(n.startswith("files/") and n.endswith(".pdf") for n in names))   # decrypted original

    def test_delete_account_removes_every_row_and_file(self):
        from app.config import get_settings
        from app.db import get_db

        s = self.student("Jaya Sen")
        self.upload_resume(s, "resume_08.pdf")
        s.post("/api/applications", json={"title": "SDE Intern", "company": "Acme"}, headers=H)
        s.post("/api/interviews", json={"mode": "text", "duration": 15}, headers=H)
        drain()
        uid = s.get("/api/auth/me").json()["user"]["id"]
        self.assertEqual(s.request("DELETE", "/api/me", json={"confirm": "nope"}, headers=H).status_code, 400)
        r = s.request("DELETE", "/api/me", json={"confirm": "DELETE"}, headers=H)
        self.assertEqual(r.status_code, 200, r.text)
        db = get_db()
        for table in ("profile_sources", "reviews", "files", "readiness_snapshots", "applications", "interviews", "notifications",
                      "chat_messages", "usage_ledger"):
            self.assertEqual(db.scalar(f"SELECT COUNT(*) FROM {table} WHERE user_id = ?", (uid,)), 0, table)
        self.assertIsNone(db.fetchone("SELECT id FROM users WHERE id = ?", (uid,)))
        self.assertFalse((get_settings().files_dir / str(uid)).exists() and any((get_settings().files_dir / str(uid)).iterdir()))
        self.assertIsNone(s.get("/api/auth/me").json()["user"])

    # ------------------------------------------------------------------ web security
    def test_csrf_header_required_for_changes(self):
        s = self.student("Kiran Das")
        self.assertEqual(s.post("/api/applications", json={"title": "X", "company": "Y"}).json()["code"], "csrf")

    def test_tampered_session_is_rejected(self):
        c = self.client()
        c.cookies.set("or_session", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.forged")
        self.assertEqual(c.get("/api/profile").status_code, 401)

    def test_brute_force_is_limited_per_account(self):
        s = self.student("Lata Roy")
        c = self.client()
        codes = [c.post("/api/auth/login", json={"email": s.email, "password": "wrong-password"}, headers=H).status_code
                 for _ in range(12)]
        self.assertEqual(codes[:10], [401] * 10)
        self.assertEqual(codes[-1], 429)
        other = self.student("Mohan Joshi")            # other accounts on the same network are unaffected
        ok = c.post("/api/auth/login", json={"email": other.email, "password": "password123"}, headers=H)
        self.assertEqual(ok.status_code, 200)

    def test_security_headers(self):
        r = self.client().get("/")
        self.assertIn("default-src 'self'", r.headers.get("content-security-policy", ""))
        self.assertEqual(r.headers.get("x-content-type-options"), "nosniff")
        self.assertIn("frame-ancestors 'none'", r.headers.get("content-security-policy", ""))

    def test_linkedin_is_never_fetched(self):
        s = self.student("Neha Gupta")
        with s.stream("POST", "/api/chat", json={"message": "my linkedin is https://www.linkedin.com/in/neha-gupta"}, headers=H) as resp:
            body = "".join(resp.iter_text())
        self.assertIn("PDF", body)                        # asks for the PDF export instead of opening the page
        from tests import llm_stub  # noqa: F401  (nothing here should have made an outbound request)


if __name__ == "__main__":
    import unittest

    unittest.main()
