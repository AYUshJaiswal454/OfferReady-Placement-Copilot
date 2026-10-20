# Written benchmarks

Every score in OfferReady comes from the checks below, implemented as deterministic rules (`app/review/*`,
`app/readiness/score.py`, `app/interview/scorer.py`). A check **passes** at 90% or more of its points, is a
**warning** from 50%, and **fails** below 50%. Every warning or failure comes with evidence (where exactly) and at
least one specific fix. Benchmark versions are stored with each review (`resume-2026.10`, `readiness-2026.10`,
`scorer-2026.10.1`), so old reviews stay explainable when the rules change.

## Resume (100 points)

The challenge's 8 benchmark items, split into 16 checks.

| # | Check | Points | Full marks when | Typical fix produced |
|---|---|---|---|---|
| 1 | **R1** Exactly one page | 12 | the PDF has one page. A second page scores 0 | the least painful cuts, in order, until the overflow fits: remove declaration/hobbies, shorten the summary, tighten 3-line bullets to 2, compress Class X/XII into one line, drop the weakest project |
| 2 | **R2.1** Consistent fonts | 3 | at most 2 font families (each ≥3% of text), at most 4 sizes, body text 9.5–12.5 pt | "use one family (Carlito) for the whole resume; change the text set in Arial" |
| 2 | **R2.2** Aligned bullets and margins | 3 | bullets and entries start at consistent x-positions within each section | the misaligned lines are boxed on the page |
| 2 | **R2.3** Consistent dates | 3 | one date format (e.g. "Mon YYYY"), one range separator, dates in the same position | each odd date with its corrected form ("05/2023" → "May 2023") |
| 2 | **R2.4** Spacing and margins | 3 | margins ≥0.35 in (top ≥0.2 in) and ≤1.2 in; even space above section headings | "use the same ~12 pt gap above every heading via Spacing Before" |
| 3 | **R3.1** No spelling mistakes | 8 | no mistakes (8; one 6, two 4, three or four 2, five or more 0). 166k-word dictionary plus tech terms and proper nouns; British spellings accepted | each misspelling located with a confident suggestion |
| 3 | **R3.2** Grammar, style, tech-term casing | 6 | no casing errors (Javascript→JavaScript, github→GitHub), first-person pronouns, mixed tenses or mixed UK/US spelling | each instance with the correction |
| 4 | **R4** Every project is complete | 16 | each of the top 5 projects has a description, tech stack, measurable impact, live link and GitHub repo link (partial credit for a demo video or profile-only link); 2+ projects expected (×0.75 otherwise) | per project: what is missing, e.g. "deploy it on Vercel and put the URL next to the title"; "'GitHub' is written but not linked" |
| 5 | **R5** GitHub and LeetCode links | 10 | clickable GitHub profile (5) and LeetCode profile (5); repo-only or other coding profile earns half; plain-text links lose 1 | the exact link to add |
| 6 | **R6** Co-curricular achievements | 8 | 2+ achievements/activities, or one strong one (hackathon, contest, club role…); certifications alone earn 4 | "add your rank to 'Smart India Hackathon'" |
| 7 | **R7.1** Bullets start with action verbs | 7 | ≥80% of bullets start with a strong past-tense verb (scaled from 30%); misspelt verbs don't count | each weak bullet with a suggested verb and a template rewrite (unknown numbers as [placeholders]) |
| 7 | **R7.2** Bullets show measurable results | 7 | ≥50% of bullets contain a number (users, %, ms, rank, ₹…) | the bullets without numbers |
| 8 | **R8.1** Readable text layer | 4 | selectable text that decodes cleanly, no icon-font junk | "export from Word/Docs as PDF, not a scan" |
| 8 | **R8.2** No text inside images | 3 | no image contains text (found by OCR) | "type out the skills hidden in the image: Python, React…" |
| 8 | **R8.3** Standard section headings | 4 | Education, Skills and Projects/Experience present with standard names | "rename 'THINGS I HAVE BUILT' to 'Projects'" |
| 8 | **R8.4** ATS-safe layout | 3 | single column, no tables, no icon fonts | which layout feature to remove |

Also reported (not scored): section order, photo, personal details (DOB/marital status), declaration, cliché
objective, file name, and the skills the target role expects that are missing.

## LinkedIn (100 points)

| Check | Points | Full marks when |
|---|---|---|
| **L1** Professional photo | 10 | a photo is present (student confirms, or a face is detected in an uploaded screenshot); n/a when unknown from the PDF |
| **L2** Specific headline | 20 | not "Student at…"; names the target role, 2+ core skills and a proof point (project, internship, rank) |
| **L3** About section | 20 | 300–2,600 characters, 3+ relevant skills, a concrete proof (project/number) and what they are looking for |
| **L4** Matches the resume | 20 | experience titles, organisations and dates agree with the resume; projects appear on both |
| **L5** Skills for the target role | 15 | 5+ skills listed (7) and coverage of the target role's core skills (8 × share covered) |
| **L6** Custom profile URL | 10 | linkedin.com/in/name, not name-8f3a91c2 |
| **L7** Education and basics | 5 | education with years, location, and certifications or honours |

Output: three ready-to-paste headlines (≤220 characters, "Role, 3 skills, one proof") and an About draft built
only from the student's facts.

## GitHub profile (100 points)

| Check | Points | Full marks when |
|---|---|---|
| **G1** Profile README | 20 | a username/username README with 80+ words of the student's own (not the template) and links to projects |
| **G2** Pinned repositories | 15 | 3+ pinned repos, each with a description (needs a token to read; otherwise n/a with suggested pins) |
| **G3** Regular activity | 25 | active in 6 or more of the last 12 weeks |
| **G4** Profile completeness | 10 | name, bio, location and a link |
| **G5** Repositories described | 15 | every original repo has a description; main repos have topics |
| **G6** Original projects | 15 | 3+ substantial original repos (not forks or near-empty) |

## Each project: repo + live link (100 points)

| Check | Points | Full marks when |
|---|---|---|
| **PR1** README | 20 | exists (5), not the CRA/Vite template and 80+ words (+3), setup commands (+7), screenshots or GIF (+5); live link at the top |
| **PR2** Live link opens without errors | 15 | loads with HTTP < 400 and no placeholder page (10), no console errors or failed assets (+5; +2 if at most two); slower than 6 s is flagged |
| **PR3** Works on mobile | 5 | viewport tag present and no horizontal overflow at 390 px |
| **PR4** Matches the claims | 5 | the page shows the project name and most claimed features/tech |
| **PR5** Readable code | 20 | no very long files/functions, debug prints, hard-coded localhost, deep nesting or commented-out blocks; AI review comments listed separately (not scored) |
| **PR6** No secrets | 15 | no keys, tokens, private keys or DB URIs in files or recent history (values always redacted; Firebase web keys are info only) |
| **PR7** Meaningful commits | 10 | 60%+ of commit messages say what changed; several commits over several days; no "Add files via upload" |
| **PR8** Clean structure | 5 | organised folders, .gitignore, no node_modules/build output/.env/.DS_Store committed |
| **PR9** Tests or CI | 5 | test files or a CI workflow (n/a for projects under 300 lines) |

## Coding practice (100) and co-curricular (100)

| Check | Points | Full marks when |
|---|---|---|
| **C1** Problems solved | 40 | 500+ (piecewise: 50 → 12, 150 → 26, 300 → 36) |
| **C2** Difficulty mix | 20 | medium + hard ≥ 50% (or Codeforces max rating ≥ 1400) |
| **C3** Contests | 20 | 5+ contests, or LeetCode rating ≥ 1600, or Codeforces ≥ 1400 |
| **C4** Recent consistency | 20 | active on 30+ of the last 90 days |
| **A1** Achievements | 100 | weighted by category: competitive wins and ranks, leadership roles, open source, certifications, sports/cultural, with extra credit for quantified results |

## Mock interview rubric (100 points)

Each dimension is scored 0–5 with the transcript turns that justify it. With an AI provider the score is the median
of three runs at temperature 0. Offline, the same rubric is computed from the per-answer assessments recorded live.

| Dimension | Weight | 5/5 means |
|---|---|---|
| Technical knowledge | 30% | explains core concepts correctly and precisely in their own words |
| Project depth | 25% | architecture, own contribution, choices and trade-offs, concretely |
| Problem solving | 20% | reasons step by step in follow-ups; handles edge cases and "what if" |
| Communication | 15% | clear, structured, concise; accent and grammar never lower this score |
| Behavioural / HR | 10% | situation–action–result with reflection |

Timing for 15 minutes: introduction 1.5 min, projects 5, technical 5.5, behavioural 2, wrap-up 1. Unused time
carries forward and extra questions are drawn so the interview fills its slot. For 20 minutes: 1.5 / 7 / 8 / 2.5 / 1.
Projects allow up to 2 follow-ups and technical questions 1 follow-up or hint. Off-topic answers get one redirect,
"I don't know" moves on politely, and attempts to instruct the AI are flagged and ignored.

## Readiness score (100 points)

| Component | Weight | Source |
|---|---|---|
| Resume | 25 | resume review |
| Projects | 25 | mean of the best three project reviews; at least two expected (missing ones count as 0) |
| Mock interview | 20 | latest completed interview |
| GitHub | 10 | GitHub profile review |
| Coding practice | 10 | LeetCode/Codeforces review |
| LinkedIn | 5 | LinkedIn review |
| Co-curricular | 5 | achievements review |

Levels: **0–49 Not ready**, **50–74 Almost ready**, **75–100 Placement ready**. Top 5 actions: for every failing
check, gain = weight × (max − score) ÷ (sum of max in that component) ÷ divisor. A fix that clears several checks
becomes one action with the summed gain. Ranking is gain ÷ effort (quick 1.0, medium 1.6, long 2.6), with at most
two actions per component. Missing components are actions too ("Upload your LinkedIn PDF").
