# Running fully locally with Ollama

OfferReady works with no AI at all (rule-based reviews, scoring and interviews), with OpenAI, or with a model
running on your own machine through Ollama. In Ollama mode no request leaves the machine and AI costs nothing.

## Set up (10 minutes)

1. Install Ollama from ollama.com (Windows, macOS, Linux) and start it (`ollama serve`, or the desktop app).
2. Pull a model. Recommended:

   | Machine | Model | Download |
   |---|---|---|
   | 16 GB RAM laptop, no GPU | `qwen2.5:7b-instruct` (default) | 4.7 GB |
   | 8 GB RAM | `qwen2.5:3b-instruct` or `llama3.2:3b` | 2 GB |
   | GPU with 12 GB+ (college server) | `qwen2.5:14b-instruct` | 9 GB |

   ```bash
   ollama pull qwen2.5:7b-instruct
   ```
3. Point OfferReady at it, either for everyone in `.env`:
   ```bash
   LLM_PROVIDER=ollama
   OLLAMA_BASE_URL=http://localhost:11434/v1
   OLLAMA_MODEL=qwen2.5:7b-instruct
   ```
   or per student in **Settings → AI provider → Local model (Ollama)**, then **Test connection**.

With Docker: `LLM_PROVIDER=ollama docker compose --profile local-ai up --build` starts Ollama, pulls the model and
connects the app to it.

## Proof it runs locally

```bash
python scripts/prove_ollama.py            # options: --model llama3.2:3b  --base http://gpu-server:11434
```

The script blocks and records **every** outbound connection that is not to localhost, then runs, through your local
model:

1. a resume review with AI rewrites of the weak bullets,
2. LinkedIn headline and About polishing,
3. a complete 15-minute mock interview, with the model judging answers and choosing follow-ups, scored three times,
4. a chat answer.

It writes `docs/OLLAMA_PROOF.md` and `docs/data/ollama_proof.json`: the model, your hardware, the latency of every
call, sample outputs, AI cost (₹0) and the list of blocked external requests, which must be empty for **PASS**.

The same code path is exercised in the automated tests (`tests/test_interview.py::ApiAndOllamaModes`): five full
interviews go through the Ollama provider against a local server speaking Ollama's OpenAI-compatible API.

## How Ollama mode differs

* At most 4 requests at a time go to the local model (a GPU serves few requests at once). Others wait briefly.
* Timeouts are longer, and if the model is down or too slow, every feature falls back to the offline rules, so
  interviews never stall.
* Scores are the same in every mode, because they come from written rules. Interview scoring uses the median of
  three runs.
* Voice: browser speech recognition is free, but Chrome and Edge send the audio to their vendor's speech service.
  For voice interviews where nothing leaves your network, run a faster-whisper server and set
  `STT_PROVIDER=whisper` (speech synthesis in the browser is local). Text mode is always fully local.
