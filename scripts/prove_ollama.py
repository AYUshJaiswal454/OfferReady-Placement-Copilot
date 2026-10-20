"""Prove OfferReady runs fully locally with Ollama: no API key, and every request stays on this machine.

    ollama pull qwen2.5:7b-instruct          # once (about 4.7 GB); any instruct model works, see docs/OLLAMA.md
    python scripts/prove_ollama.py            # about 3-10 minutes depending on your CPU/GPU

What it does, with every outbound connection to anything other than localhost blocked and recorded:
  1. reviews a resume and has the local model rewrite its weak bullets,
  2. polishes a LinkedIn headline and About section,
  3. runs a complete 15-minute mock interview (simulated candidate) with the local model choosing follow-ups,
     then scores it three times,
  4. answers a chat question.
It writes docs/OLLAMA_PROOF.md and docs/data/ollama_proof.json with the model, the hardware, the latency of every
model call, sample outputs, and the count of blocked external requests (which must be 0 for the proof to pass).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
LOCAL = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def hardware() -> dict:
    info = {"os": f"{platform.system()} {platform.release()}", "machine": platform.machine(), "cpu_count": os.cpu_count()}
    try:
        import ctypes  # noqa: F401
        if Path("/proc/meminfo").exists():
            kb = int(next(l for l in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines() if l.startswith("MemTotal")).split()[1])
            info["ram_gb"] = round(kb / 1024 / 1024, 1)
    except Exception:
        pass
    if shutil.which("nvidia-smi"):
        try:
            info["gpu"] = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                                         capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:
            pass
    return info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
                    help="Ollama server (without /v1)")
    ap.add_argument("--model", default=os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct"))
    ap.add_argument("--out", default=str(ROOT / "docs" / "OLLAMA_PROOF.md"))
    a = ap.parse_args()
    base = a.base.rstrip("/").removesuffix("/v1")

    try:
        import httpx  # type: ignore
    except ImportError:  # pragma: no cover
        import httpx2 as httpx  # type: ignore
    try:
        tags = httpx.get(base + "/api/tags", timeout=5).json()
    except Exception as exc:
        sys.exit(f"Ollama is not reachable at {base} ({exc}). Start it with `ollama serve`.")
    names = [m.get("name") for m in tags.get("models", [])]
    if not any(n == a.model or n.split(":")[0] == a.model.split(":")[0] for n in names):
        sys.exit(f"Model {a.model} is not pulled. Run: ollama pull {a.model}   (installed: {', '.join(names) or 'none'})")

    from tests.support import RESUMES, drain, ensure_resume_corpus, fresh_environment

    ensure_resume_corpus()
    fresh_environment(llm_provider="ollama", ollama_base_url=base + "/v1", ollama_model=a.model, ollama_model_smart=a.model,
                      offline_mode=True, playwright_enabled=False, llm_timeout_s=240)

    # Block and record every request that would leave this machine.
    from app.net import http as nethttp

    blocked: list[str] = []
    real = httpx.AsyncHTTPTransport()

    class LocalOnly(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            host = urlparse(str(request.url)).hostname or ""
            if host not in LOCAL:
                blocked.append(str(request.url)[:120])
                raise httpx.ConnectError(f"blocked external request to {host}")
            return await real.handle_async_request(request)

    nethttp.set_transport(LocalOnly())

    from app.db import get_db, now_iso
    from app.intake.resume_parser import parse_resume_pdf
    from app.interview import service as iv
    from app.llm.features import polish_linkedin, rewrite_bullets
    from app.review.resume_checks import review_resume
    from app.security import hash_password
    from tests.interview_personas import simulate

    db = get_db()
    uid = db.insert("users", {"email": "ollama-proof@local", "password_hash": hash_password("x" * 12), "name": "Kabir Mehta",
                              "role": "student", "created_at": now_iso(), "consent_at": now_iso(), "settings": {},
                              "target_role": "Full Stack Developer", "job_type": "internship", "target_locations": ["Bengaluru"]})
    user = db.fetchone("SELECT * FROM users WHERE id = ?", (uid,))
    samples: dict = {}
    t_start = time.perf_counter()

    print("1/4 resume review + local rewrites…", flush=True)
    parsed = parse_resume_pdf((RESUMES / "resume_07.pdf").read_bytes())
    review = review_resume(parsed, "resume.pdf", "Full Stack Developer")
    rewrites = asyncio.run(rewrite_bullets([{"text": b["text"], "suggestion": b.get("suggestion")} for b in review["weak_bullets"][:4]],
                                           "Full Stack Developer", user))
    samples["resume_rewrite"] = rewrites[:2]

    print("2/4 LinkedIn polish…", flush=True)
    li = asyncio.run(polish_linkedin({"headline": ["Full Stack Developer | React · Node.js"], "about": "I build web apps."},
                                     {"name": "Kabir Mehta", "headline": "Student", "about": "I am a hardworking student."},
                                     {"target_role": "Full Stack Developer", "resume": parsed.to_summary()}, user))
    samples["linkedin_headline"] = (li or {}).get("headline", [])[:2]

    print("3/4 15-minute mock interview with local follow-ups, then 3 scoring runs…", flush=True)
    db.insert("profile_sources", {"user_id": uid, "kind": "resume", "label": "resume.pdf", "input": {}, "status": "ready",
                                  "extracted": parse_resume_pdf((RESUMES / "resume_05.pdf").read_bytes()).to_summary(),
                                  "created_at": now_iso(), "updated_at": now_iso()})
    st = iv.start(user, "text", 15, "ollama", a.model)
    asyncio.run(simulate(st["interview_id"], user, "good", seed=11))
    drain()
    row = db.fetchone("SELECT * FROM interviews WHERE id = ?", (st["interview_id"],))
    turns = db.fetchall("SELECT speaker, text, meta FROM interview_turns WHERE interview_id = ? ORDER BY seq", (row["id"],))
    follow = [t["text"] for t in turns if t["speaker"] == "interviewer" and (t["meta"] or {}).get("followup")]
    samples["interview"] = {"score": row["score"], "status": row["status"], "follow_up_examples": follow[:3],
                            "weak_areas": (row["result"] or {}).get("weak_areas", [])[:2],
                            "scorer": (row["result"] or {}).get("scorer")}

    print("4/4 chat…", flush=True)
    from app.llm.providers import chat

    ans = asyncio.run(chat([{"role": "user", "content": "In two sentences: how should a fresher prepare for a system design round?"}],
                           feature="chat_proof", user=user, max_tokens=200, cache=False))
    samples["chat"] = ans.text[:400]

    ledger = db.fetchall("SELECT feature, provider, model, latency_ms, cost_usd, input_tokens, output_tokens FROM usage_ledger")
    lat = sorted(r["latency_ms"] for r in ledger if r["provider"] == "ollama")
    providers = sorted({r["provider"] for r in ledger})
    proof = {
        "generated": datetime.now().isoformat(timespec="seconds"), "ollama": base, "model": a.model, "hardware": hardware(),
        "llm_calls": len(ledger), "providers_used": providers, "total_cost_usd": round(sum(r["cost_usd"] for r in ledger), 6),
        "latency_ms": {"p50": lat[len(lat) // 2] if lat else None, "p95": lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else None,
                       "mean": round(statistics.mean(lat)) if lat else None},
        "external_requests_blocked": blocked, "wall_seconds": round(time.perf_counter() - t_start, 1), "samples": samples,
        "passed": bool(lat) and providers == ["ollama"] and not blocked and row["status"] == "completed",
    }
    (ROOT / "docs" / "data").mkdir(parents=True, exist_ok=True)
    (ROOT / "docs" / "data" / "ollama_proof.json").write_text(json.dumps(proof, indent=2, default=str), encoding="utf-8")
    hw = proof["hardware"]
    md = [
        "# Proof: OfferReady running fully locally with Ollama", "",
        f"Generated {proof['generated']} by `python scripts/prove_ollama.py`.", "",
        "| | |", "|---|---|",
        f"| Result | **{'PASS' if proof['passed'] else 'FAIL'}** |",
        f"| Model | `{a.model}` via Ollama at {base} |",
        f"| Machine | {hw.get('os')}, {hw.get('cpu_count')} CPU threads, {hw.get('ram_gb', '?')} GB RAM{', GPU ' + hw['gpu'] if hw.get('gpu') else ', no GPU'} |",
        f"| Model calls | {proof['llm_calls']}, all served by: {', '.join(providers)} |",
        f"| Latency per call | p50 {proof['latency_ms']['p50']} ms, p95 {proof['latency_ms']['p95']} ms |",
        f"| External requests attempted | {len(blocked)} (every non-localhost request was blocked and would be listed here) |",
        f"| AI cost | ${proof['total_cost_usd']} |",
        f"| Total time | {proof['wall_seconds']} s |",
        "", "## Sample outputs from the local model", "",
        "**Resume bullet rewrites**", "",
        *[f"* {r.get('text', '')} → {r.get('rewrite', '')}" for r in samples.get("resume_rewrite", [])], "",
        "**LinkedIn headline options**", "", *[f"* {h}" for h in samples.get("linkedin_headline", [])], "",
        f"**Mock interview**: {samples['interview']['status']}, score {samples['interview']['score']}. Follow-up questions the "
        "local model chose:", "", *[f"* {q}" for q in samples["interview"]["follow_up_examples"]], "",
        "**Chat**", "", f"> {samples['chat']}", "",
    ]
    Path(a.out).write_text("\n".join(md), encoding="utf-8")
    print(("PASS" if proof["passed"] else "FAIL"), "-", a.out)


if __name__ == "__main__":
    main()
