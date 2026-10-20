# Cost per student

**About ₹1.3 per student for a complete journey with the default hosted model (gpt-6-luna), at most ₹1.8, and
₹0 with Ollama.** Measured by `python scripts/measure_cost.py` (raw numbers: `docs/data/cost.json`).

## What one "complete journey" includes

Resume review with AI rewrites of weak bullets, LinkedIn review with polished headline and About, GitHub profile,
three projects (each cloned, analysed and code-reviewed by the AI), coding profile, achievements, **one full
15-minute mock interview** (26 AI turn decisions plus 3 scoring runs), and **10 chat questions** (each a tool-calling
step plus a streamed answer).

Input tokens are counted from the real prompts the app sends. Output tokens are given two ways: **typical** (the
sizes these prompts produce, including low/medium reasoning) and a **ceiling** where every call uses its whole
`max_tokens` budget, which on reasoning models also caps hidden reasoning tokens. The fixture repositories are
small, so code-review input was raised to the app's excerpt cap (24,000 characters, about 6,000 tokens per project)
to reflect real student repos.

| Feature | AI calls | Input tokens | Output tokens (typical) | Output tokens (ceiling) |
|---|---|---|---|---|
| Mock interview turns | 26 | 18,264 | 4,160 | 7,800 |
| Project code reviews (3 projects) | 3 | 18,750 | 2,700 | 3,600 |
| Chat (10 questions) | 20 | 12,474 | 7,000 | 12,000 |
| Interview scoring (median of 3) | 3 | 8,139 | 4,500 | 5,400 |
| LinkedIn headline and About | 1 | 530 | 600 | 900 |
| Resume bullet rewrites | 1 | 327 | 650 | 900 |
| **Total** | **54** | **58,484** | **19,610** | **30,600** |

Rule-based work (all scoring, parsing, OCR, repo analysis, secret scanning, live-link checks, job matching,
tracking) uses no AI and costs nothing beyond the server.

## By model

Prices from `app/data/pricing.json` (OpenAI pricing page, checked 18 Oct 2026; ₹84 = $1).

| Model | Typical per student | Ceiling per student | 1,000 students (typical) |
|---|---|---|---|
| **gpt-6-luna** (default) | **$0.0157, ₹1.31** | $0.0211, ₹1.78 | ₹1,310 |
| gpt-4o-mini | $0.0205, ₹1.73 | $0.0271, ₹2.28 | ₹1,730 |
| gpt-5-mini | $0.0538, ₹4.52 | $0.0758, ₹6.37 | ₹4,520 |
| gpt-4.1-mini | $0.0548, ₹4.60 | $0.0724, ₹6.08 | ₹4,600 |
| gpt-6.1-sol | $0.3131, ₹26.30 | $0.4230, ₹35.53 | ₹26,300 |
| **Ollama (local)** | **₹0** | ₹0 | ₹0 (plus your own hardware and electricity) |

Each extra mock interview adds about ₹0.5 on gpt-6-luna (turns + scoring). A student who practises five interviews
in a season therefore costs about ₹3–4 in total.

## Voice interviews

Browser speech recognition and speech synthesis (Chrome/Edge) are free and the default. If the college prefers
OpenAI voice for accuracy, a 15-minute interview (about 7.5 minutes of student speech transcribed with
gpt-4o-mini-transcribe and 4.5 minutes of interviewer speech with gpt-4o-mini-tts) adds about **$0.09 (₹7.6)**.
A self-hosted faster-whisper server (`STT_PROVIDER=whisper`) is free.

## Keeping costs under control

* Temperature-0 calls are cached by content hash, so re-running an unchanged review costs nothing.
* Usage and cost are recorded per student and feature (`usage_ledger`). The placement cell's dashboard shows total
  and per-student cost, broken down by feature.
* Students can bring their own OpenAI key in Settings. It is stored encrypted and never shown again.
* Unsupported parameters are learned once per model, so no call is paid for twice. Rate limits are retried with
  back-off, and a circuit breaker switches to the offline rules if the provider is down.
* Server: the 2-vCPU VM used for the load test handles about 250 simultaneously active students
  ([SCALABILITY.md](SCALABILITY.md)). A VM of that size costs roughly ₹1,500–3,000 per month at Indian cloud prices.
