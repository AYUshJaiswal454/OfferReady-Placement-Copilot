"""End-to-end flows through the real HTTP API: a student's whole journey, the tracker, and the MSOT job board."""
from __future__ import annotations

import json
import unittest

from tests.support import H, AppTestCase, OfflineWeb, drain

LINKEDIN_TEXT = """Asha Verma
Student at MSOT Institute of Technology
Bengaluru, Karnataka, India
linkedin.com/in/asha-verma-12ab34cd
About
I am a hardworking student passionate about technology.
Experience
Software Engineering Intern
Fintrix Labs
May 2025 - July 2025
Education
MSOT Institute of Technology
Bachelor of Technology - BTech, Computer Science (2022 - 2026)
Skills
Java
Python
"""


class StudentJourney(AppTestCase):
    def test_full_journey(self):
        c = self.student("Asha Verma", consent=False)
        # 1. Nothing is processed before consent.
        r = c.post("/api/profile/resume", files={"file": ("cv.pdf", b"%PDF-1.4 x", "application/pdf")}, headers=H)
        self.assertEqual(r.json()["code"], "consent_required")
        self.assertEqual(c.post("/api/me/consent", json={"accept": True}, headers=H).status_code, 200)
        c.patch("/api/me", json={"target_role": "Full Stack Developer", "job_type": "internship",
                                 "target_locations": ["Bangalore", "Remote"]}, headers=H)
        self.assertEqual(c.post("/api/profile/resume", files={"file": ("x.pdf", b"hello", "application/pdf")}, headers=H)
                         .json()["code"], "bad_type")

        with OfflineWeb() as web:
            # 2. Profile intake: resume, LinkedIn (pasted), GitHub, coding stats, a project, an achievement.
            self.upload_resume(c, "resume_05.pdf")
            self.assertEqual(c.post("/api/profile/linkedin", data={"text": LINKEDIN_TEXT}, headers=H).status_code, 200)
            self.assertEqual(c.post("/api/profile/github", json={"username": "github.com/asha-verma"}, headers=H).status_code, 200)
            self.assertEqual(c.post("/api/profile/coding", json={"platform": "leetcode", "manual": {
                "solved": 180, "easy": 90, "medium": 80, "hard": 10, "contests": 3, "rating": 1520}}, headers=H).status_code, 200)
            r = c.post("/api/profile/projects", json={"name": "DevConnect", "repo_url": "https://github.com/asha/good_fullstack",
                                                      "live_url": web.base + "/good", "description": "Real-time Q&A for students",
                                                      "tech": ["React", "Node.js"]}, headers=H)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(c.post("/api/profile/achievements", json={"text": "Finalist, Smart India Hackathon 2025"}, headers=H)
                             .status_code, 200)
            drain()

        profile = c.get("/api/profile").json()
        statuses = {k: [s["status"] for s in v] for k, v in profile["sources"].items()}
        for kind in ("resume", "linkedin", "github", "leetcode", "project", "achievement"):
            self.assertIn(kind, statuses)
            self.assertTrue(all(s == "ready" for s in statuses[kind]), (kind, statuses))

        # 3. One review page with every section, benchmark checks and specific fixes.
        report = c.get("/api/report").json()
        for section in ("resume", "linkedin", "github", "coding"):
            self.assertTrue(report["reviews"].get(section), section)
        resume = report["reviews"]["resume"][0]
        self.assertEqual(len(resume["checks"]), 16)
        page_file = resume["data"]["page_files"][0]
        img = c.get(f"/api/files/{page_file}")
        self.assertEqual(img.status_code, 200)
        self.assertTrue(img.headers["content-type"].startswith("image/"))
        li = report["reviews"]["linkedin"][0]
        self.assertGreaterEqual(len(li["rewrites"]["headline"]), 2)        # ready-to-paste headlines
        project = report["reviews"]["project"][0]
        ids = {ch["id"] for ch in project["checks"]}
        self.assertTrue({"PR1", "PR2", "PR3", "PR4", "PR5", "PR6", "PR7"} <= ids)

        # 4. Readiness out of 100 with the five best actions; history grows when something changes.
        rd = c.get("/api/readiness").json()
        self.assertTrue(0 <= rd["score"] <= 100)
        self.assertIn(rd["level"], ("Not ready", "Almost ready", "Placement ready"))
        self.assertLessEqual(len(rd["top_actions"]), 5)
        self.assertTrue(all(a["gain"] > 0 for a in rd["top_actions"]))

        # 5. A short mock interview through the API.
        r = c.post("/api/interviews", json={"mode": "text", "duration": 15}, headers=H).json()
        iid = r["interview_id"]
        from app.db import get_db

        plan = get_db().fetchone("SELECT plan FROM interviews WHERE id = ?", (iid,))["plan"]
        asked_projects = {i.get("project") for p in plan["phases"] for i in p["items"] if i["type"] == "project"}
        self.assertTrue(asked_projects & {"DevConnect", "ShopLite", "CropDoc"}, asked_projects)   # from the resume/projects
        for answer in ["I'm a final-year CSE student who builds full stack apps; my main project is DevConnect.",
                       "DevConnect is a Q&A app: React frontend, Express API, MongoDB, Socket.io chat. I built auth and chat.",
                       "I don't know."]:
            t = c.post(f"/api/interviews/{iid}/turn", json={"text": answer}, headers=H).json()
            self.assertIn("turns", t)
        c.post(f"/api/interviews/{iid}/end", headers=H)
        drain()
        iv = c.get(f"/api/interviews/{iid}").json()
        self.assertEqual(iv["interview"]["status"], "completed")
        self.assertIsNotNone(iv["interview"]["score"])
        self.assertGreaterEqual(len(iv["turns"]), 6)
        rd2 = c.get("/api/readiness").json()
        self.assertIsNotNone(rd2["components"]["interview"]["score"])

        # 6. Jobs: boolean query, ranked results with reasons, deep links for sites we don't scrape.
        from app.tasks import enqueue

        enqueue("crawl_jobs", {"source": "demo"})
        drain()
        jobs = c.get("/api/jobs").json()
        self.assertGreater(jobs["total"], 0)
        self.assertTrue(all(x["reasons"] for x in jobs["results"]))
        self.assertTrue(any(d["site"] == "LinkedIn Jobs" for d in jobs["deep_links"]))
        self.assertIn("error", c.get("/api/jobs", params={"q": '(React OR'}).json())

        # 7. Tracker: every status, history, calendar export, follow-up reminder.
        job = jobs["results"][0]["job"]
        app = c.post("/api/applications", json={"job_id": job["id"], "status": "saved"}, headers=H).json()["application"]
        for status in ("applied", "shortlisted", "interview", "offer"):
            body = {"status": status}
            if status == "interview":
                body["interview_at"] = "2030-01-15T10:00:00+00:00"
            r = c.patch(f"/api/applications/{app['id']}", json=body, headers=H)
            self.assertEqual(r.json()["application"]["status"], status)
        board = c.get("/api/applications").json()
        self.assertEqual(board["counts"]["offer"], 1)
        self.assertIn("BEGIN:VEVENT", c.get("/api/applications.ics").text)

        other = c.post("/api/applications", json={"title": "SDE Intern", "company": "Acme", "status": "applied"}, headers=H).json()
        get_db().execute("UPDATE applications SET next_follow_up_at = ? WHERE id = ?", ("2020-01-01T00:00:00+00:00",
                                                                                         other["application"]["id"]))
        enqueue("send_reminders", {})
        drain()
        notes = c.get("/api/notifications").json()["notifications"]
        self.assertTrue(any("Follow up with Acme" in n["title"] for n in notes))

        # 8. Chat answers from the student's own data.
        with c.stream("POST", "/api/chat", json={"message": "What should I fix first?"}, headers=H) as resp:
            body = "".join(resp.iter_text())
        events = [json.loads(line[5:]) for line in body.split("\n") if line.startswith("data:")]
        self.assertTrue(any(e["type"] == "delta" for e in events))
        self.assertEqual(events[-1]["type"], "done")

        # 9. Students can delete any piece of their data; its reviews go with it.
        sid = profile["sources"]["linkedin"][0]["id"]
        self.assertEqual(c.delete(f"/api/profile/sources/{sid}", headers=H).status_code, 200)
        self.assertFalse(c.get("/api/report").json()["reviews"].get("linkedin"))


class MsotJobBoard(AppTestCase):
    def test_post_apply_review_status_sync(self):
        admin = self.admin()
        good = self.student("Ravi Kumar", target_role="Backend Developer", job_type="internship", target_locations=["Bengaluru"])
        other = self.student("Meena Das", target_role="Data Analyst")
        for s in (good, other):
            self.upload_resume(s, "resume_05.pdf")
        drain()

        r = admin.post("/api/admin/jobs", json={"title": "Backend Intern", "company": "Fintrix Labs", "location": "Bengaluru",
                                                "employment_type": "internship", "description": "Java, SQL, REST APIs.",
                                                "skills": ["Java", "SQL"], "min_score": 1, "batches": [2026], "branches": [],
                                                "deadline": "2030-12-31", "status": "open"}, headers=H)
        self.assertEqual(r.status_code, 200, r.text)
        job_id = r.json()["job"]["id"]
        hard = admin.post("/api/admin/jobs", json={"title": "Elite Intern", "company": "Top Co", "description": "Very selective role; apply only if your readiness is excellent.",
                                                   "skills": [], "min_score": 99, "batches": [2026], "status": "open"}, headers=H)
        hard_id = hard.json()["job"]["id"]

        # Eligible students see the MSOT job pinned above everything else; ineligible ones see why.
        jobs = good.get("/api/jobs").json()
        self.assertIn(job_id, [x["job"]["id"] for x in jobs["msot"]["eligible"]])
        blocked = next(x for x in jobs["msot"]["ineligible"] if x["job"]["id"] == hard_id)
        self.assertTrue(blocked["ineligible_reasons"])
        self.assertEqual(good.post(f"/api/msot/jobs/{hard_id}/apply", json={"share_report": True}, headers=H).json()["code"],
                         "not_eligible")

        # Apply in one click, sharing the report.
        r = good.post(f"/api/msot/jobs/{job_id}/apply", json={"share_report": True}, headers=H)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["application"]["status"], "applied")

        # The placement cell sees the applicant and their shared report; a non-applicant's report stays private.
        applicants = admin.get(f"/api/admin/jobs/{job_id}/applicants").json()["applicants"]
        self.assertEqual(len(applicants), 1)
        a = applicants[0]
        self.assertTrue(a["shared_report"])
        self.assertEqual(admin.get(f"/api/admin/students/{a['student_id']}/report").status_code, 200)
        other_id = next(s["id"] for s in admin.get("/api/admin/students").json()["students"] if s["name"] == "Meena Das")
        self.assertEqual(admin.get(f"/api/admin/students/{other_id}/report").status_code, 403)

        # Status changes by the cell appear in the student's tracker with a notification.
        r = admin.patch(f"/api/admin/applications/{a['id']}", json={"status": "shortlisted", "note": "Test on Friday 10am"}, headers=H)
        self.assertEqual(r.status_code, 200, r.text)
        mine = good.get("/api/applications").json()
        self.assertEqual(mine["counts"]["shortlisted"], 1)
        notes = good.get("/api/notifications").json()["notifications"]
        self.assertTrue(any("Fintrix" in n["title"] and "hortlisted" in (n["title"] + n.get("body", "")) for n in notes), notes)

        # Students can't use admin endpoints.
        self.assertEqual(good.get("/api/admin/overview").status_code, 403)
        self.assertEqual(good.patch(f"/api/admin/applications/{a['id']}", json={"status": "offer"}, headers=H).status_code, 403)

        # Cohort analytics for the cell.
        ov = admin.get("/api/admin/overview").json()
        self.assertEqual(ov["students"], 2)
        self.assertIn("common_gaps", ov)

        # Closing the job hides it from students.
        admin.patch(f"/api/admin/jobs/{job_id}", json={"status": "closed"}, headers=H)
        jobs = other.get("/api/jobs").json()
        self.assertNotIn(job_id, [x["job"]["id"] for x in jobs["msot"]["eligible"] + jobs["msot"]["ineligible"]])


if __name__ == "__main__":
    unittest.main()


class ProjectDedupe(AppTestCase):
    def test_adding_a_resume_project_again_replaces_it(self):
        c = self.student("Om Prakash")
        self.upload_resume(c, "resume_05.pdf")          # its three projects are picked up from the resume links
        drain()
        before = c.get("/api/profile").json()["sources"].get("project", [])
        self.assertTrue(before)
        name = before[0]["input"]["name"]
        c.post("/api/profile/projects", json={"name": name, "repo_url": "https://github.com/om/good_fullstack",
                                              "live_url": self.web.base + "/good"}, headers=H)
        drain()
        after = c.get("/api/profile").json()["sources"]["project"]
        self.assertEqual(len(after), len(before))
        self.assertEqual(sum(1 for p in after if p["input"]["name"] == name), 1)
        self.assertIn("good_fullstack", next(p for p in after if p["input"]["name"] == name)["input"]["repo_url"])
