import { KeyboardEvent, useEffect, useRef, useState } from "react";
import { LuArrowUp, LuCheck, LuCircle, LuPaperclip, LuTrash2 } from "react-icons/lu";
import { api, Json, streamChat } from "../api";
import { ChatCard, ReadinessCard, UploadDrop } from "../components/Cards";
import { Link } from "../router";
import { useAuth, useTasks, useTaskDone, useToast } from "../state";
import { Prose, useLoad } from "../ui";

type Msg = { id?: number; role: "user" | "assistant"; content: string; cards?: Json[]; pending?: boolean };

const SUGGESTIONS = ["What should I fix first?", "Find jobs for me", "I want a backend developer internship in Bangalore",
  "Start a mock interview", "How do I make my projects stand out?"];
const CHECK_LINKS: Record<string, string> = {
  resume: "/profile#resume", linkedin: "/profile#linkedin", github: "/profile#github", coding: "/profile#coding",
  projects: "/profile#projects", achievements: "/profile#achievements", interview: "/interview",
};

function Margin({ tick }: { tick: number }) {
  const { data: rd, reload } = useLoad(() => api.get("/readiness"), []);
  const { data: prof, reload: reloadProf } = useLoad(() => api.get("/profile"), []);
  const { track } = useTasks();
  const toast = useToast();
  useEffect(() => { if (tick) { reload(); reloadProf(); } }, [tick, reload, reloadProf]);
  useTaskDone(() => { reload(); reloadProf(); }, [reload, reloadProf]);
  return (
    <aside className="stack" style={{ "--gap": "1.25rem" } as React.CSSProperties}>
      {rd && <ReadinessCard data={rd} />}
      {prof && (
        <div className="sheet pad">
          <div className="spread"><b>Your profile</b><span className="small muted">{Math.round(prof.completeness * 100)}% complete</span></div>
          <ul className="list" style={{ marginTop: ".5rem" }}>
            {prof.checklist.map((c: Json) => (
              <li key={c.key} style={{ padding: ".45rem 0" }}>
                <Link to={CHECK_LINKS[c.key]} className="row" style={{ textDecoration: "none", gap: ".5rem" }} aria-current={undefined}>
                  {c.done ? <LuCheck style={{ color: "var(--tick)" }} /> : <LuCircle style={{ color: "var(--rule-strong)" }} />}
                  <span className={c.done ? "" : "muted"}>{c.label}</span>
                </Link>
              </li>
            ))}
          </ul>
          {prof.suggestions?.map((s: Json) => (
            <div key={s.kind} className="notice info small" style={{ marginTop: ".6rem" }}>
              {s.text}.{" "}
              <button className="btn small secondary" style={{ marginTop: ".4rem" }} onClick={async () => {
                const res = s.kind === "github" ? await api.post("/profile/github", { username: s.value })
                  : await api.post("/profile/coding", { platform: "leetcode", username: s.value });
                track(res.task_id);
                toast.push({ text: `Added ${s.kind === "github" ? "GitHub" : "LeetCode"} — reviewing now.` });
                reloadProf();
              }}>Add it</button>
            </div>
          ))}
        </div>
      )}
    </aside>
  );
}

export default function Copilot() {
  const { user } = useAuth();
  const [messages, setMessages] = useState<Msg[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(0);
  const [attachOpen, setAttachOpen] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    api.get("/chat/history").then((r) => { setMessages(r.messages); setLoaded(true); }).catch(() => setLoaded(true));
  }, []);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [messages]);

  async function send(msg: string) {
    const t = msg.trim();
    if (!t || busy) return;
    setText("");
    setBusy(true);
    setMessages((m) => [...m, { role: "user", content: t }, { role: "assistant", content: "", pending: true, cards: [] }]);
    try {
      await streamChat(t, (e) => {
        setMessages((m) => {
          const copy = [...m];
          const last = { ...copy[copy.length - 1] };
          if (e.type === "delta") last.content += e.text;
          if (e.type === "cards") last.cards = [...(last.cards || []), ...e.cards];
          if (e.type === "done") { last.pending = false; last.id = e.message_id || undefined; }
          if (e.type === "error") { last.pending = false; last.content = e.message; }
          copy[copy.length - 1] = last;
          return copy;
        });
      });
    } catch (e) {
      setMessages((m) => {
        const copy = [...m];
        copy[copy.length - 1] = { role: "assistant", content: (e as Error).message, pending: false };
        return copy;
      });
    } finally {
      setBusy(false);
      setTick((x) => x + 1);
      taRef.current?.focus();
    }
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(text);
    }
  }

  const first = user?.name?.split(" ")[0] || "there";
  const { data: prof } = useLoad(() => api.get("/profile"), [tick]);
  const hasResume = !!prof?.checklist?.find((c: Json) => c.key === "resume" && c.done);
  return (
    <div className="page">
      <div className="two-col">
        <section className="chat" aria-label="Copilot chat">
          <div className="messages" aria-live="polite">
            {loaded && messages.length === 0 && (
              <div className="welcome stack" style={{ "--gap": "1.25rem" } as React.CSSProperties}>
                {hasResume ? (<>
                  <h1>Welcome back, {first}.</h1>
                  <p>Your profile has been reviewed. Ask what to fix first, paste a GitHub or LeetCode link to add it,
                    or tell me the role and city you're aiming for and I'll find matching jobs.</p>
                </>) : (<>
                  <h1>Hi {first}. Let's find out how placement-ready you are.</h1>
                  <p>Start with your resume. I'll mark every issue on the page and tell you exactly how to fix it.
                    Then add your GitHub, LeetCode and LinkedIn, or just tell me in your own words.</p>
                  <UploadDrop kind="resume" onDone={() => setTick((x) => x + 1)} />
                </>)}
              </div>
            )}
            {messages.map((m, i) => (
              <div key={m.id ?? `p${i}`} className={`msg ${m.role}`}>
                {m.role === "assistant" && <div className="who-line">OfferReady {m.pending && <span className="spinner" style={{ width: 12, height: 12 }} />}</div>}
                {m.role === "assistant" ? <Prose text={m.content || (m.pending ? "…" : "")} /> : <span style={{ whiteSpace: "pre-wrap" }}>{m.content}</span>}
                {(m.cards || []).map((c, ci) => <div key={ci} className="card-in-chat"><ChatCard card={c} /></div>)}
              </div>
            ))}
            <div ref={endRef} />
          </div>
          <div className="composer">
            {messages.length < 3 && (
              <div className="suggestions">
                {SUGGESTIONS.map((s) => <button key={s} onClick={() => send(s)} disabled={busy}>{s}</button>)}
              </div>
            )}
            {attachOpen && (
              <div className="grid-2" style={{ marginBottom: ".6rem" }}>
                <UploadDrop kind="resume" onDone={() => { setAttachOpen(false); setTick((x) => x + 1); }} />
                <UploadDrop kind="linkedin" onDone={() => { setAttachOpen(false); setTick((x) => x + 1); }} />
              </div>
            )}
            <div className="composer-box">
              <button className="icon-btn" aria-label="Attach resume or LinkedIn PDF" aria-expanded={attachOpen} onClick={() => setAttachOpen(!attachOpen)}><LuPaperclip /></button>
              <textarea ref={taRef} rows={1} value={text} placeholder="Paste a GitHub/LeetCode link, ask a question, or tell me your target role…"
                onChange={(e) => { setText(e.target.value); e.target.style.height = "auto"; e.target.style.height = Math.min(180, e.target.scrollHeight) + "px"; }}
                onKeyDown={onKey} aria-label="Message" />
              <button className="btn" onClick={() => send(text)} disabled={busy || !text.trim()} aria-label="Send"><LuArrowUp /></button>
            </div>
            {messages.length > 0 && (
              <div className="row small muted" style={{ marginTop: ".4rem", justifyContent: "flex-end" }}>
                <button className="btn ghost small" onClick={async () => { await api.del("/chat/history"); setMessages([]); }}><LuTrash2 /> Clear chat</button>
              </div>
            )}
          </div>
        </section>
        <Margin tick={tick} />
      </div>
    </div>
  );
}
