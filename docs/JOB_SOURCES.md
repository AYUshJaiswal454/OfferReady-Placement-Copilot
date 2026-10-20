# Job sources and compliance

OfferReady collects jobs only from sources that publish them for reuse: official APIs, applicant-tracking-system
job-board APIs that companies provide for their career pages, and syndication feeds. It never scrapes job sites
whose terms prohibit it. For those, students get one-click searches that open in their own browser.

## Sources collected automatically

| Source | Type | Why it is allowed | Notes |
|---|---|---|---|
| Greenhouse job boards | Public Job Board API (`boards-api.greenhouse.io`) | Published by Greenhouse for embedding listings on any site | Add recruiters' board tokens in `app/data/job_sources.json` (Postman, Groww, Databricks… preset) |
| Lever job boards | Public Postings API (`api.lever.co/v0/postings`) | Published for career sites and aggregators | CRED, Meesho, Atlan… preset |
| Ashby job boards | Public Job Postings API | Published for career pages | |
| SmartRecruiters | Public Posting API | Published for career pages | Off by default; add company ids |
| Remotive | Public API | Allowed with attribution, a few calls a day | Source name and link shown on each card |
| Arbeitnow | Free job board API | Public API | |
| Remote OK | Public API | Allowed with a link back to Remote OK and the original URL | Both shown on every card |
| The Muse | Public jobs API | Public API | Internship and entry-level filters |
| Adzuna (India) | Official search API | Free key required | Set `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` |
| Jooble | Official REST API | Free key required | Set `JOOBLE_API_KEY` |
| RSS / Atom feeds | Syndication feeds | Feeds exist to be syndicated; **robots.txt is checked first** | e.g. We Work Remotely |
| **MSOT job board** | Posted by the placement cell | Our own data | Pinned on top for eligible students |

Students can also add any job they find elsewhere by pasting its link and details ("Add a job you found"). It then
appears in their tracker.

## Not collected (terms prohibit automated access)

LinkedIn, Naukri, Indeed, Internshala, Wellfound and Glassdoor. For each, OfferReady builds a search link from the
student's query (keywords, city, experience level, last week) that opens the student's own logged-in session.
The same applies to profiles: OfferReady never opens linkedin.com and asks for the official "Save to PDF" export.

## How collection behaves

* **Polite by design:** one shared HTTP client identifies itself (`HTTP_USER_AGENT`), per-host rate limits,
  ETag/Last-Modified caching, retries with back-off, and robots.txt checks for anything that isn't an official API.
* **Health is visible:** Admin → Job sources shows each source's last run, jobs found, and a readable error
  (e.g. "Skipped: add ADZUNA_APP_ID and ADZUNA_APP_KEY to .env"). The placement cell can run a source on demand.
* **Refresh:** every `JOB_REFRESH_HOURS` (default 6). Postings expire after 30 days unless seen again.
* **Normalise and dedupe:** titles, companies, cities (Bangalore = Bengaluru), remote flags, internship versus
  full-time, experience and skills are normalised. The same job seen on two sources is stored once with an "also on"
  link to the other.
* **Search and rank:** a boolean query (AND, OR, NOT, "phrases", brackets) built from the student's skills, target
  role, level and cities, which they can edit. Ranking is 45% skills, 20% role, 15% level, 10% location and
  10% freshness, ×0.75 for unrelated role families. Every card shows why it matched, which skills are missing,
  the original source, and opens the original posting in one click.
* **Offline demo:** `OFFLINE_MODE=true` disables every external source. The bundled sample jobs (source
  "Sample jobs (demo data)", URLs on example.com) are clearly labelled.
