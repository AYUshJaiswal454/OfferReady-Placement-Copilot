"""A local stand-in for an OpenAI-compatible chat API (the protocol both OpenAI and Ollama speak).

It lets the test suite exercise the real network path of both provider modes (requests, JSON mode, tool calls,
streaming, retries, parameter adaptation, usage accounting) without an API key or a downloaded model. Answers are
produced by small deterministic heuristics so that interviews and reviews behave sensibly, and every response
reports realistic token usage so cost per student can be measured.

Behaviour switches (by model name):
  *reject-temperature*  -> 400 "Unsupported parameter: 'temperature'" (tests parameter auto-adaptation)
  *flaky*               -> first call per conversation answers 429 with Retry-After: 0
  *slow*                -> adds STUB_LATENCY_S seconds (default 0.8) per call, like a real hosted model
It also implements GET /api/tags (Ollama) and GET /v1/models.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATS = {"calls": 0, "by_feature": {}, "rejected_params": 0, "throttled": 0, "requests": []}
_lock = threading.Lock()
_flaky_seen: set[str] = set()


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _feature(messages: list[dict]) -> str:
    sys_ = " ".join(str(m.get("content") or "") for m in messages if m.get("role") == "system")
    user = " ".join(str(m.get("content") or "") for m in messages if m.get("role") == "user")
    if "Judge the candidate's last answer" in user:
        return "interview_turn"
    if "interview assessor" in sys_:
        return "interview_score"
    if '"rewrites"' in user:
        return "resume_rewrite"
    if '"headline"' in user and "LinkedIn" in user:
        return "linkedin_rewrite"
    if "code reviewer" in sys_:
        return "code_review"
    if "Student snapshot" in sys_:
        return "chat"
    if "single word: ready" in user:
        return "settings_test"
    return "summary"


# ----------------------------------------------------------------------------- answer heuristics
def _interview_turn(user: str) -> dict:
    from app.interview.engine import keyword_assess

    m = re.search(r"Data: (\{.*\})\s*$", user, re.S)
    data = json.loads(m.group(1)) if m else {}
    item = {"question": data.get("current_question", ""), "type": data.get("question_type", "tech"),
            "key_points": data.get("expected_key_points", []), "hint": data.get("hint")}
    followup = data.get("last_question_asked") if data.get("last_question_asked") != data.get("current_question") else None
    a = keyword_assess(data.get("candidate_answer", ""), item, followup_q=followup)
    allowed = data.get("allowed_actions", ["next"])
    planned = data.get("planned_follow_ups") or []
    action, follow = "next", ""
    if a["assessment"] == "clarify" and "rephrase" in allowed:
        action, follow = "rephrase", "Let me put it another way: " + item["question"]
    elif a["assessment"] == "off_topic" and "redirect" in allowed:
        action, follow = "redirect", "Let's come back to the question: " + item["question"]
    elif a["assessment"] == "strong" and "follow_up" in allowed and planned:
        action, follow = "follow_up", planned[0]
    elif a["assessment"] == "partial" and "hint" in allowed and item.get("hint"):
        action, follow = "hint", "Here's a small hint: " + item["hint"]
    return {"assessment": a["assessment"], "covered": a.get("covered", []), "action": action,
            "ack": "Thanks." if a["assessment"] != "dont_know" else "That's fine.", "follow_up": follow}


def _interview_score(user: str) -> dict:
    from app.interview.engine import DOMAIN_WORDS, tech_vocab

    m = re.search(r"TRANSCRIPT:\n<<<\n(.*)\n>>>", user, re.S)
    lines = (m.group(1) if m else "").splitlines()
    kind = "hr"
    followup = False
    per: dict[str, list[tuple[float, int]]] = {"technical": [], "projects": [], "behavioural": [], "communication": [],
                                               "problem_solving": []}
    injection = False
    for line in lines:
        mm = re.match(r"\[T(\d+) [\d:]+\] (INTERVIEWER|CANDIDATE)(?: \((\w+):([^)]*)\))?: (.*)", line)
        if not mm:
            continue
        seq, who, tag, detail, text = int(mm.group(1)), mm.group(2), mm.group(3), mm.group(4) or "", mm.group(5)
        if who == "INTERVIEWER":
            kind = tag or kind
            followup = "follow-up" in detail
            continue
        if re.search(r"ignore (all )?(previous )?instructions|give me .*100", text, re.I):
            injection = True
            continue
        words = len(text.split())
        vocab = set(re.findall(r"[a-z][a-z0-9+#.\-]{2,}", text.lower()))
        terms = len(vocab & tech_vocab())
        on_topic = terms >= 2 or bool(vocab & DOMAIN_WORDS)
        dont = bool(re.search(r"don'?t know|not sure|haven'?t", text, re.I)) and words < 30
        q = 0.3 if dont else (0.1 if not on_topic else min(1.0, 0.2 + 0.4 * min(1, words / 60) + 0.4 * min(1, terms / 6)))
        dim = {"tech": "technical", "project": "projects", "hr": "behavioural"}.get(kind)
        if dim and kind != "wrap":
            per[dim].append((q * 5, seq))
        if followup:
            per["problem_solving"].append((q * 5, seq))
        per["communication"].append(((2.5 if dont else 1.0 if not on_topic else (5.0 if 20 <= words <= 180 else 3.0)), seq))
    dims = []
    for key in ("technical", "projects", "problem_solving", "communication", "behavioural"):
        vals = per[key]
        score = round(sum(v for v, _ in vals) / len(vals) * 2) / 2 if vals else 0.0
        dims.append({"key": key, "score": score, "reason": f"Judged from {len(vals)} answers.",
                     "evidence": [s for _, s in sorted(vals, reverse=True)[:3]]})
    ranked = sorted(dims, key=lambda d: d["score"])
    return {"dimensions": dims, "strengths": [f"Clear answers in {ranked[-1]['key'].replace('_', ' ')}."],
            "weak_areas": [f"Practise {ranked[0]['key'].replace('_', ' ')}: explain with one concrete example each time."],
            "summary": "Solid overall; see the weak areas for what to practise next.", "questions": [],
            "flags": ["injection_attempt"] if injection else []}


def _rewrites(user: str) -> dict:
    m = re.search(r"Bullets: (\[.*\])\s*$", user, re.S)
    items = json.loads(m.group(1)) if m else []
    out = []
    for it in items:
        text = re.sub(r"^(worked on|responsible for|helped (with|in)?|did)\s+", "", it["text"], flags=re.I).rstrip(".")
        out.append({"id": it["id"], "rewrite": f"Built {text[0].lower() + text[1:] if text else 'the feature'}, "
                                               "improving [metric] by [X%]."})
    return {"rewrites": out}


def _code_review(user: str) -> dict:
    files = re.findall(r"=== (.+?) ===", user)
    comments = [{"file": f, "line": 1, "severity": "low", "issue": "No module docstring explaining what this file does.",
                 "suggestion": "Add a two-line comment at the top describing the responsibility of this file."} for f in files[:3]]
    return {"summary": "The code is readable; error handling and documentation can be stronger.", "comments": comments}


def respond(payload: dict) -> tuple[int, dict, dict]:
    """Returns (status, headers, body)."""
    model = payload.get("model", "")
    messages = payload.get("messages", [])
    feature = _feature(messages)
    with _lock:
        STATS["calls"] += 1
        STATS["by_feature"][feature] = STATS["by_feature"].get(feature, 0) + 1
        STATS["requests"].append({"model": model, "feature": feature, "params": sorted(k for k in payload if k != "messages"),
                                  "prompt_tokens": sum(_tokens(str(m.get("content") or "")) for m in messages),
                                  "max_tokens": payload.get("max_completion_tokens") or payload.get("max_tokens") or 0})
        STATS["requests"] = STATS["requests"][-5000:]
    if "reject-temperature" in model and "temperature" in payload:
        with _lock:
            STATS["rejected_params"] += 1
        return 400, {}, {"error": {"message": "Unsupported parameter: 'temperature' is not supported with this model.",
                                   "type": "invalid_request_error", "param": "temperature"}}
    convo_key = json.dumps(messages[-1:], sort_keys=True)[:400]
    if "flaky" in model and convo_key not in _flaky_seen:
        _flaky_seen.add(convo_key)
        with _lock:
            STATS["throttled"] += 1
        return 429, {"retry-after": "0"}, {"error": {"message": "Rate limit reached", "type": "rate_limit"}}
    if "slow" in model:
        time.sleep(float(os.environ.get("STUB_LATENCY_S", "0.8")))
    user = "\n".join(str(m.get("content") or "") for m in messages if m.get("role") == "user")
    tool_calls = None
    if feature == "interview_turn":
        content = json.dumps(_interview_turn(user))
    elif feature == "interview_score":
        content = json.dumps(_interview_score(user))
    elif feature == "resume_rewrite":
        content = json.dumps(_rewrites(user))
    elif feature == "linkedin_rewrite":
        content = json.dumps({"headline": ["Full Stack Developer | React · Node.js · MongoDB | Built a Q&A app used by 350+ students",
                                           "Backend-leaning Full Stack Developer | Java · Spring Boot · SQL",
                                           "Final-year CSE student building real-time web apps"],
                              "about": "I build web apps end to end.\n\nMost recently I built DevConnect...\n\n"
                                       "I'm looking for a full stack internship."})
    elif feature == "code_review":
        content = json.dumps(_code_review(user))
    elif feature == "settings_test":
        content = "ready"
    elif feature == "chat" and payload.get("tools") and "fix first" in user.lower():
        content = ""
        tool_calls = [{"id": "call_1", "type": "function", "function": {"name": "get_readiness", "arguments": "{}"}}]
    else:
        content = "Here is what I'd do next: fix the top action on your readiness page, then re-run the review."
    prompt_tokens = sum(_tokens(str(m.get("content") or "")) for m in messages)
    msg: dict = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    body = {"id": f"stub-{STATS['calls']}", "object": "chat.completion", "model": model,
            "choices": [{"index": 0, "message": msg, "finish_reason": "tool_calls" if tool_calls else "stop"}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": _tokens(content) + (20 if tool_calls else 0),
                      "total_tokens": prompt_tokens + _tokens(content)}}
    return 200, {}, body


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # quiet
        pass

    def _send(self, status: int, body: dict, headers: dict | None = None) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        if self.path.endswith("/api/tags"):
            return self._send(200, {"models": [{"name": "qwen2.5:7b-instruct"}]})
        if self.path.endswith("/models"):
            return self._send(200, {"data": [{"id": "stub-model"}]})
        self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("content-length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")
        if not self.path.endswith("/chat/completions"):
            return self._send(404, {"error": "not found"})
        status, headers, body = respond(payload)
        if status == 200 and payload.get("stream"):
            text = body["choices"][0]["message"]["content"] or ""
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.end_headers()
            for chunk in re.findall(r"\S+\s*", text):
                self.wfile.write(f"data: {json.dumps({'choices': [{'delta': {'content': chunk}}]})}\n\n".encode())
            self.wfile.write(f"data: {json.dumps({'choices': [], 'usage': body['usage']})}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            return
        self._send(status, body, headers)


def start(port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/v1"


if __name__ == "__main__":  # python -m tests.llm_stub 11434  -> pretend to be Ollama on its usual port
    import sys

    srv, url = start(int(sys.argv[1]) if len(sys.argv) > 1 else 11434)
    print("Stub OpenAI/Ollama-compatible API at", url)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        srv.shutdown()
