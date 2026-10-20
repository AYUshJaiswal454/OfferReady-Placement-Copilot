# Privacy and data handling

OfferReady handles resumes, interview recordings and job applications, which is personal data about young people
looking for their first job. These are the rules the code enforces (verified by `tests/test_privacy.py`).

## Consent first

Nothing is uploaded, fetched or analysed until the student accepts a plain-language consent screen. It says what is
collected, why, where it is stored, who can see it, and how to delete it. The consent version and time are stored;
if the wording changes, students are asked again. Every processing endpoint refuses requests without consent.

## What is collected, and what is not

| Collected (only what the student gives) | Never collected |
|---|---|
| Resume (PDF/DOCX), LinkedIn PDF export or pasted text | Anything fetched from linkedin.com (we never open LinkedIn pages) |
| Public GitHub username, repo and live links | Private repositories or GitHub write access |
| LeetCode/Codeforces username, or numbers typed by the student | Passwords to any other site |
| Achievements typed in; mock interview transcripts and (voice mode) audio | Location, contacts, browsing data |
| Applications the student tracks | Data from other students |

## Who can see what

* **The student** sees and controls everything.
* **The placement cell** sees each student's readiness score in cohort statistics and the list of students. It sees a
  student's full report and files **only** when that student applied to an MSOT job and ticked "share my report".
  Each such view is written to the audit log.
* **AI provider:** when AI features are on, only the text needed for that feature is sent (e.g. bullets to rewrite,
  a transcript to score). With Ollama, nothing leaves the college server. With the default offline mode, nothing
  is sent anywhere. In voice interviews, the default browser speech recognition (Chrome/Edge) sends audio to the
  browser vendor's speech service; for fully local voice, use the self-hosted Whisper option or text mode. Students can switch to offline mode or use their own key in Settings.
* **Nobody else.** There are no analytics scripts, no third-party trackers, and no fonts or scripts loaded from CDNs.
  The Content Security Policy allows only same-origin resources.

## Protection

* Files (resumes, LinkedIn PDFs, audio, page renders, screenshots) are **encrypted at rest** with Fernet
  (AES-128-CBC + HMAC). The key is in `DATA_ENCRYPTION_KEY`, generated on first run and kept outside the database.
* Students' own API keys are encrypted the same way and never returned by the API.
* Passwords use **scrypt**. Sessions are signed JWTs in an httpOnly, SameSite=Lax cookie (marked Secure when `BASE_URL` is https).
  Every state-changing request needs a CSRF header.
* Every query that reads student data is scoped to the signed-in owner. The tests confirm that one student cannot
  read, change or delete another's reviews, files, applications or interviews.
* Ten wrong passwords lock that account for 15 minutes without blocking others on the same campus network.
* Secrets found in a student's repositories are reported with their values redacted (e.g. `AKIA…B8ZK`) and are
  never stored in full.
* The resume parser never executes content from uploads. DOCX conversion runs LibreOffice headless in a temporary
  directory. Repos are cloned shallow, size-limited and deleted after analysis (stale work directories are removed
  every 6 hours).

## Rights: see, edit, export, delete

* **See and edit:** My profile lists every piece of data with its review. Any item can be edited, re-checked or
  deleted, and deleting a source deletes its reviews and files.
* **Export:** Settings → "Download my data" gives a zip with every table that concerns the student (account,
  sources, reviews, readiness history, interviews and transcripts, applications, notifications, chat, AI usage)
  plus the original uploaded files, decrypted.
* **Delete account:** Settings → "Delete my account and data" (type DELETE to confirm) removes every row and file
  immediately. Only an audit entry remains, saying that an account was deleted, with no personal data.

## Retention

Working copies of cloned repositories: under 6 hours. Finished background task records: 14 days. HTTP cache for
public APIs: 3 days. Student data is kept until the student deletes it or the college removes inactive accounts
(for example after graduation).

## Compliance notes

* Job data comes only from official APIs and feeds whose terms allow it, and robots.txt is respected
  ([JOB_SOURCES.md](JOB_SOURCES.md)).
* The design follows the data-minimisation, purpose-limitation, consent and erasure principles of India's Digital
  Personal Data Protection Act, 2023. The college remains the data fiduciary and should publish a privacy notice
  for students based on this page.
