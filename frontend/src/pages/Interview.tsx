import { useCallback, useEffect, useRef, useState } from "react";
import { LuMic, LuMicOff, LuSend, LuSquare, LuVolume2 } from "react-icons/lu";
import { api, fmtDate, Json } from "../api";
import { Link, navigate } from "../router";
import { useAuth, useTaskDone, useToast } from "../state";
import { Empty, ErrorNote, Loading, ScoreBlock, Segmented, useLoad } from "../ui";

// ------------------------------------------------------------------ speech helpers
const SR: any = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;

function speakBrowser(text: string): Promise<void> {
  return new Promise((resolve) => {
    if (!("speechSynthesis" in window)) return resolve();
    const u = new SpeechSynthesisUtterance(text);
    const voices = speechSynthesis.getVoices();
    u.voice = voices.find((v) => v.lang === "en-IN") || voices.find((v) => v.lang.startsWith("en")) || null;
    u.rate = 1.02;
    u.onend = () => resolve();
    u.onerror = () => resolve();
    speechSynthesis.cancel();
    speechSynthesis.speak(u);
  });
}

async function speak(text: string, mode: string): Promise<void> {
  if (mode === "openai") {
    try {
      const res = await fetch("/api/speech/tts", { method: "POST", credentials: "same-origin",
        headers: { "X-Requested-With": "offerready", "content-type": "application/json" }, body: JSON.stringify({ text }) });
      if (res.ok) {
        const url = URL.createObjectURL(await res.blob());
        await new Promise<void>((resolve) => { const a = new Audio(url); a.onended = () => resolve(); a.onerror = () => resolve(); a.play().catch(() => resolve()); });
        return;
      }
    } catch { /* fall back to the browser voice */ }
  }
  return speakBrowser(text);
}

function fmtClock(s: number) {
  const m = Math.floor(Math.max(0, s) / 60);
  return `${m}:${String(Math.floor(Math.max(0, s) % 60)).padStart(2, "0")}`;
}

// ------------------------------------------------------------------ setup + history
function Setup() {
  const { data, error, loading, reload } = useLoad(() => api.get("/interviews"), []);
  const [duration, setDuration] = useState(15);
  const [mode, setMode] = useState<"text" | "voice">("text");
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const { user } = useAuth();
  useTaskDone(() => reload(), [reload]);
  async function start() {
    setBusy(true);
    try {
      if (mode === "voice") await navigator.mediaDevices.getUserMedia({ audio: true }).then((s) => s.getTracks().forEach((t) => t.stop()));
      const res = await api.post("/interviews", { duration, mode });
      sessionStorage.setItem(`iv-first-${res.interview_id}`, "1");
      navigate(`/interview/${res.interview_id}`);
    } catch (e) {
      toast.push({ kind: "error", text: (e as Error).name === "NotAllowedError" ? "Microphone access was blocked. Allow it in your browser, or use text mode." : (e as Error).message });
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Mock interview</h1>
          <p>A timed interview built from your own projects and your target role{user?.target_role ? ` (${user.target_role})` : ""}: introduction, project deep-dive, technical questions, one behavioural question. Scored on a fixed rubric with transcript evidence.</p>
        </div>
      </header>
      <div className="two-col">
        <div className="sheet pad stack" style={{ "--gap": "1.25rem" } as React.CSSProperties}>
          <div className="field"><span className="label">Length</span>
            <Segmented label="Length" value={duration} onChange={setDuration} options={[{ value: 15, label: "15 minutes" }, { value: 20, label: "20 minutes" }]} /></div>
          <div className="field"><span className="label">How you answer</span>
            <Segmented label="Mode" value={mode} onChange={setMode} options={[{ value: "text", label: "Type answers" }, { value: "voice", label: "Speak answers" }]} />
            <span className="hint">{mode === "voice" ? (SR ? "The interviewer speaks; you answer out loud and can correct the transcript before sending. Your audio is recorded so you can replay it." : "Your browser has no built-in speech recognition; answers are transcribed on the server if it is configured, otherwise use text mode.") : "Best on a slow connection or in a noisy place."}</span></div>
          <ul className="small muted" style={{ margin: 0, paddingLeft: "1.1rem" }}>
            <li>Take a few seconds to think before answering — like a real interview.</li>
            <li>Saying "I don't know" is fine; you'll simply move on.</li>
            <li>Feedback and a replayable transcript are ready a few seconds after you finish.</li>
          </ul>
          <button className="btn marker" onClick={start} disabled={busy} style={{ alignSelf: "flex-start" }}>{busy ? "Preparing questions…" : "Start interview"}</button>
        </div>
        <aside>
          <h3 style={{ marginBottom: ".5rem" }}>Past interviews</h3>
          {loading && !data ? <Loading /> : error ? <ErrorNote error={error} retry={reload} /> : data.interviews.length === 0 ? (
            <p className="muted small">None yet. Your first one sets your interview score (20% of readiness).</p>
          ) : (
            <ul className="list">
              {data.interviews.map((iv: Json) => (
                <li key={iv.id} className="spread">
                  <span><Link to={`/interview/${iv.id}`}>{fmtDate(iv.started_at, true)}</Link><div className="small muted">{iv.duration_min} min, {iv.mode}, {iv.status}</div></span>
                  <span className="score-mini num" style={{ fontSize: "1.3rem" }}>{iv.score != null ? Math.round(iv.score) : "—"}</span>
                </li>
              ))}
            </ul>
          )}
        </aside>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ live room
function Room({ id, initial, onFinished }: { id: number; initial: Json; onFinished: () => void }) {
  const [turns, setTurns] = useState<Json[]>(initial.turns);
  const [state, setState] = useState<Json>(initial.state);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [remaining, setRemaining] = useState<number>(initial.state.remaining_s);
  const [speech, setSpeech] = useState<Json>({ stt: "browser", tts: "browser" });
  const voice = initial.interview.mode === "voice";
  const recRef = useRef<any>(null);
  const sessionRec = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const answerRec = useRef<MediaRecorder | null>(null);
  const answerChunks = useRef<Blob[]>([]);
  const toast = useToast();
  const endRef = useRef<HTMLDivElement>(null);
  const phases = initial.plan.phases;
  const lastQ = [...turns].reverse().find((t) => t.speaker === "interviewer");

  useEffect(() => { api.get("/speech/config").then(setSpeech).catch(() => null); }, []);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [turns]);
  useEffect(() => {
    const iv = setInterval(() => setRemaining((r) => r - 1), 1000);
    return () => clearInterval(iv);
  }, []);

  // Whole-session recording (voice mode) for replay.
  useEffect(() => {
    if (!voice) return;
    let stream: MediaStream | null = null;
    navigator.mediaDevices?.getUserMedia({ audio: true }).then((s) => {
      stream = s;
      const rec = new MediaRecorder(s);
      rec.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
      rec.start(5000);
      sessionRec.current = rec;
    }).catch(() => toast.push({ kind: "error", text: "Microphone unavailable — switch to typing your answers." }));
    return () => { sessionRec.current?.state === "recording" && sessionRec.current.stop(); stream?.getTracks().forEach((t) => t.stop()); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voice]);

  const uploadRecording = useCallback(async () => {
    const rec = sessionRec.current;
    if (!rec) return;
    await new Promise<void>((resolve) => { rec.onstop = () => resolve(); rec.state === "recording" ? rec.stop() : resolve(); });
    if (chunks.current.length) {
      const blob = new Blob(chunks.current, { type: rec.mimeType || "audio/webm" });
      await api.upload(`/interviews/${id}/audio`, blob, {}, "interview.webm").catch(() => null);
    }
  }, [id]);

  // Speak each new interviewer line in voice mode.
  const spokenRef = useRef<number>(0);
  useEffect(() => {
    if (!voice || !lastQ || lastQ.seq <= spokenRef.current) return;
    spokenRef.current = lastQ.seq;
    speak(lastQ.text, speech.tts);
  }, [lastQ, voice, speech.tts]);

  async function send(textOverride?: string) {
    const text = (textOverride ?? answer).trim();
    if (!text || busy) return;
    setBusy(true);
    stopListening();
    try {
      const res = await api.post(`/interviews/${id}/turn`, { text });
      setTurns((t) => [...t, ...res.turns]);
      setAnswer("");
      if (res.state) { setState(res.state); setRemaining(res.state.remaining_s); }
      if (res.done) {
        await uploadRecording();
        if (voice) await speak(res.turns[res.turns.length - 1].text, speech.tts);
        onFinished();
      }
    } catch (e) {
      toast.push({ kind: "error", text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  function startListening() {
    if (SR && speech.stt === "browser") {
      const rec = new SR();
      rec.lang = "en-IN";
      rec.continuous = true;
      rec.interimResults = true;
      let finalText = answer ? answer + " " : "";
      rec.onresult = (e: any) => {
        let interim = "";
        for (let i = e.resultIndex; i < e.results.length; i++) {
          if (e.results[i].isFinal) finalText += e.results[i][0].transcript + " ";
          else interim += e.results[i][0].transcript;
        }
        setAnswer((finalText + interim).trimStart());
      };
      rec.onend = () => setListening(false);
      rec.onerror = () => setListening(false);
      rec.start();
      recRef.current = rec;
      setListening(true);
      return;
    }
    // Server transcription: record this answer, send it when the student stops.
    navigator.mediaDevices.getUserMedia({ audio: true }).then((s) => {
      const rec = new MediaRecorder(s);
      answerChunks.current = [];
      rec.ondataavailable = (e) => e.data.size && answerChunks.current.push(e.data);
      const started = Date.now();
      rec.onstop = async () => {
        s.getTracks().forEach((t) => t.stop());
        const blob = new Blob(answerChunks.current, { type: rec.mimeType || "audio/webm" });
        try {
          const res = await api.upload("/speech/transcribe", blob, { seconds: String((Date.now() - started) / 1000) }, "answer.webm");
          setAnswer((a) => (a ? a + " " : "") + res.text);
        } catch (e) {
          toast.push({ kind: "error", text: (e as Error).message });
        }
      };
      rec.start();
      answerRec.current = rec;
      setListening(true);
    }).catch(() => toast.push({ kind: "error", text: "Microphone access was blocked." }));
  }

  function stopListening() {
    recRef.current?.stop();
    recRef.current = null;
    if (answerRec.current?.state === "recording") answerRec.current.stop();
    answerRec.current = null;
    setListening(false);
  }

  useEffect(() => {
    if (remaining <= 0 && !busy) {
      api.post(`/interviews/${id}/end`).then(async () => { await uploadRecording(); onFinished(); }).catch(() => null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [remaining <= 0]);

  return (
    <div className="page">
      <div className="spread" style={{ marginBottom: "1rem" }}>
        <div>
          <h1 style={{ fontSize: "var(--step-2)" }}>Mock interview — {initial.interview.target_role}</h1>
          <p className="muted small">{initial.interview.duration_min} minutes, {voice ? "spoken" : "typed"} answers</p>
        </div>
        <div className="row">
          <span className={`timer ${remaining < 60 ? "low" : ""}`} aria-label={`Time left ${fmtClock(remaining)}`}>{fmtClock(remaining)}</span>
          <button className="btn secondary small" onClick={async () => { if (confirm("End the interview now? It will be scored on the answers so far.")) { await api.post(`/interviews/${id}/end`); await uploadRecording(); onFinished(); } }}><LuSquare /> End</button>
        </div>
      </div>
      <ol className="steps" aria-label="Interview phases">
        {phases.map((p: Json, i: number) => <li key={p.key} className={i < state.phase_index ? "done" : i === state.phase_index ? "now" : ""}>{p.label}</li>)}
      </ol>

      <div className="two-col" style={{ marginTop: "1.5rem" }}>
        <div className="stack" style={{ "--gap": "1.5rem" } as React.CSSProperties}>
          {lastQ && (
            <div>
              <div className="row muted small" style={{ marginBottom: ".4rem" }}>Interviewer {voice && <button className="btn ghost small" onClick={() => speak(lastQ.text, speech.tts)} aria-label="Repeat the question aloud"><LuVolume2 /> Repeat</button>}</div>
              <p className="question">{lastQ.text}</p>
            </div>
          )}
          <div className="stack" style={{ "--gap": ".6rem" } as React.CSSProperties}>
            {voice && (
              <div className="row" style={{ gap: "1rem" }}>
                <button className={`mic ${listening ? "on" : ""}`} onClick={listening ? stopListening : startListening} disabled={busy}
                  aria-label={listening ? "Stop recording" : "Start answering"}>{listening ? <LuMicOff /> : <LuMic />}</button>
                <span className="muted">{listening ? "Listening… press again when you've finished." : "Press the microphone and answer out loud."}</span>
              </div>
            )}
            <label className="sr-only" htmlFor="answer">Your answer</label>
            <textarea id="answer" className="textarea" rows={voice ? 4 : 6} value={answer} onChange={(e) => setAnswer(e.target.value)}
              placeholder={voice ? "Your spoken answer appears here — fix any words before sending." : "Type your answer. Ctrl+Enter sends it."}
              onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(); } }} />
            <div className="row">
              <button className="btn" onClick={() => send()} disabled={busy || !answer.trim()}><LuSend /> {busy ? "Sending…" : "Send answer"}</button>
              <button className="btn ghost" onClick={() => send("I don't know this one, let's move on.")} disabled={busy}>Skip question</button>
            </div>
          </div>
        </div>
        <aside>
          <h3 style={{ marginBottom: ".6rem" }}>Transcript</h3>
          <ol className="transcript small" style={{ maxHeight: "60vh", overflow: "auto" }}>
            {turns.map((t) => (
              <li key={t.seq} style={{ gridTemplateColumns: "1fr" }}>
                <div className="spk"><b>{t.speaker === "interviewer" ? "Interviewer" : "You"}</b></div>
                <div className={t.speaker === "interviewer" ? "iv" : ""}>{t.text}</div>
              </li>
            ))}
            <div ref={endRef} />
          </ol>
        </aside>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ results
function Results({ data }: { data: Json }) {
  const iv = data.interview;
  const res = data.result || {};
  const evidenceTurns = new Set<number>((res.dimensions || []).flatMap((d: Json) => d.evidence || []));
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Interview feedback</h1>
          <p>{fmtDate(iv.started_at, true)}, {iv.duration_min} minutes, {iv.target_role}. Scored on a fixed rubric{res.scorer?.runs ? ` (median of ${res.scorer.runs} runs)` : ""}.</p>
        </div>
        <div className="row no-print"><Link to="/interview" className="btn secondary">Back</Link><Link to="/interview" className="btn">Practise again</Link></div>
      </header>
      {iv.status === "abandoned" ? <Empty title="Not enough answers to score">{res.reason}</Empty> : (
        <div className="stack" style={{ "--gap": "2rem" } as React.CSSProperties}>
          <ScoreBlock score={iv.score} sub="Interview score — 20% of your readiness" />
          {res.summary && <p className="serif" style={{ fontSize: "var(--step-1)" }}>{res.summary}</p>}
          {res.flags?.length > 0 && <div className="notice">{res.flags.includes("injection_attempt") && "An answer tried to instruct the AI; it was ignored. "}{res.flags.includes("very_short_answers") && "Your answers were very short, so the score has low confidence — aim for 30–90 seconds per answer."}</div>}
          <section>
            <h2 style={{ marginBottom: ".6rem" }}>Rubric</h2>
            <table className="scheme">
              <thead><tr><th>Dimension</th><th className="num">Weight</th><th>Why</th><th className="num">Score</th></tr></thead>
              <tbody>
                {(res.dimensions || []).map((d: Json) => (
                  <tr key={d.key}>
                    <td><b>{d.label}</b></td><td className="num">{d.weight}%</td>
                    <td className="small">{d.reason} {d.evidence?.length > 0 && <span className="muted">Evidence: {d.evidence.map((e: number) => <a key={e} href={`#t${e}`} style={{ marginRight: ".3rem" }}>turn {e}</a>)}</span>}</td>
                    <td className="num"><b>{d.score}</b> / 5</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
          <div className="grid-2">
            <section className="sheet pad"><h3 style={{ marginBottom: ".5rem" }}>What went well</h3><ul className="list">{(res.strengths || []).map((s: string, i: number) => <li key={i}>{s}</li>)}</ul></section>
            <section className="sheet pad"><h3 style={{ marginBottom: ".5rem" }}>Practise next</h3><ul className="list">{(res.weak_areas || []).map((s: string, i: number) => <li key={i}>{s}</li>)}</ul></section>
          </div>
          {res.questions?.length > 0 && (
            <section>
              <h2 style={{ marginBottom: ".6rem" }}>What a strong answer covers</h2>
              <ul className="list">
                {res.questions.map((q: Json, i: number) => (
                  <li key={i}><b>{q.question || `Question at turn ${q.turn}`}</b>
                    <div className="row" style={{ marginTop: ".4rem" }}>{(q.ideal_points || []).map((p: string) => <span className="tag" key={p}>{p}</span>)}</div></li>
                ))}
              </ul>
            </section>
          )}
          <section>
            <div className="spread" style={{ marginBottom: ".6rem" }}><h2>Transcript</h2>{iv.audio_file_id && <audio controls src={`/api/interviews/${iv.id}/audio`} />}</div>
            <ol className="transcript">
              {data.turns.map((t: Json) => (
                <li key={t.seq} id={`t${t.seq}`} className={evidenceTurns.has(t.seq) ? "evidence-turn" : ""}>
                  <div className="spk"><b>{t.speaker === "interviewer" ? "Interviewer" : "You"}</b>turn {t.seq}, {fmtClock(t.t_ms / 1000)}</div>
                  <div className={`txt ${t.speaker === "interviewer" ? "iv" : ""}`}>{t.text}</div>
                </li>
              ))}
            </ol>
          </section>
        </div>
      )}
    </div>
  );
}

function Session({ id }: { id: number }) {
  const { data, error, loading, reload } = useLoad(() => api.get(`/interviews/${id}`), [id]);
  useTaskDone((t) => { if (t.kind === "score_interview") reload(); }, [reload]);
  useEffect(() => {
    if (data?.interview?.status === "scoring") {
      const iv = setInterval(reload, 2500);
      return () => clearInterval(iv);
    }
  }, [data?.interview?.status, reload]);
  if (loading && !data) return <div className="page"><Loading /></div>;
  if (error) return <div className="page"><ErrorNote error={error} retry={reload} /></div>;
  if (data.interview.status === "live") return <Room id={id} initial={data} onFinished={reload} />;
  if (data.interview.status === "scoring") return <div className="page"><Loading label="Scoring your interview against the rubric…" /></div>;
  return <Results data={data} />;
}

export default function Interview({ id }: { id?: number }) {
  return id ? <Session id={id} /> : <Setup />;
}
