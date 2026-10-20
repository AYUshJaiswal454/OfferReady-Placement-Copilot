// Cards shown inside chat replies and reused on pages.
import { useState } from "react";
import { LuExternalLink, LuMic, LuUpload } from "react-icons/lu";
import { api, Json } from "../api";
import { Link, navigate } from "../router";
import { useTasks, useTaskDone, useToast } from "../state";
import { levelClass } from "../ui";

export function UploadDrop({ kind = "resume", onDone }: { kind?: "resume" | "linkedin"; onDone?: () => void }) {
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const { track } = useTasks();
  const toast = useToast();
  const label = kind === "resume" ? "your resume (PDF or DOCX)" : "your LinkedIn PDF (Profile → More → Save to PDF)";
  async function send(file: File) {
    setBusy(true);
    try {
      const res = await api.upload(kind === "resume" ? "/profile/resume" : "/profile/linkedin", file);
      track(res.task_id);
      toast.push({ text: kind === "resume" ? "Resume uploaded — reviewing it now." : "LinkedIn uploaded — reviewing it now." });
      onDone?.();
    } catch (e) {
      toast.push({ kind: "error", text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }
  return (
    <label className={`drop ${over ? "over" : ""}`} onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f) send(f); }}>
      <input type="file" className="sr-only" accept={kind === "resume" ? ".pdf,.docx" : ".pdf"} onChange={(e) => e.target.files?.[0] && send(e.target.files[0])} />
      <div className="row" style={{ justifyContent: "center" }}>
        {busy ? <span className="spinner" /> : <LuUpload />}
        <span><b>{busy ? "Uploading…" : "Drop or choose"}</b> {label}</span>
      </div>
    </label>
  );
}

export function ReadinessCard({ data }: { data: Json }) {
  return (
    <div className="sheet pad">
      <div className="spread">
        <div className="row" style={{ alignItems: "baseline" }}>
          <span className="score-mini num">{Math.round(data.score)}</span><span className="muted">/ 100</span>
          <span className={`level ${levelClass(data.level)}`} style={{ fontSize: "1.05rem" }}>{data.level}</span>
        </div>
        <Link to="/readiness" className="small">Full breakdown</Link>
      </div>
      {data.top_actions?.length > 0 && (
        <ol className="actions" style={{ marginTop: ".75rem" }}>
          {data.top_actions.slice(0, 3).map((a: Json, i: number) => (
            <li key={i}>
              <div><b>{a.title}</b><div className="small muted clamp-2">{a.detail}</div></div>
              <span className="gain">+{a.gain.toFixed(1)}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export function JobMini({ r }: { r: Json }) {
  return (
    <li>
      <div className="job" style={{ gridTemplateColumns: "54px 1fr" }}>
        <div className="job-match">{r.match}<small>match</small></div>
        <div>
          <h3 style={{ fontSize: "1.05rem" }}>{r.job.title}</h3>
          <div className="meta">{r.job.company}{r.job.location ? `, ${r.job.location}` : ""}</div>
          <div className="skills">
            {r.matched_skills.slice(0, 4).map((s: string) => <span className="tag have" key={s}>{s}</span>)}
            {r.missing_skills.slice(0, 2).map((s: string) => <span className="tag miss" key={s}>{s}</span>)}
          </div>
        </div>
      </div>
    </li>
  );
}

function TaskCard({ data }: { data: Json }) {
  const [done, setDone] = useState<Json | null>(null);
  useTaskDone((t) => { if (t.id === data.task_id) setDone(t); }, [data.task_id]);
  return (
    <div className="row small muted">
      {done ? (done.status === "done" ? <>Finished. <Link to="/report">Open the review report</Link></> : <span className="error-text">Failed: {done.error}</span>)
        : <><span className="spinner" /> {data.label}…</>}
    </div>
  );
}

export function ChatCard({ card }: { card: Json }) {
  const d = card.data || {};
  switch (card.type) {
    case "readiness":
      return <ReadinessCard data={d} />;
    case "jobs":
      return (
        <div className="sheet pad">
          <div className="spread"><b>{d.total} matching openings</b><Link to="/jobs" className="small">See all jobs</Link></div>
          <ul className="list" style={{ marginTop: ".5rem" }}>{(d.results || []).map((r: Json) => <JobMini key={r.job.id} r={r} />)}</ul>
        </div>
      );
    case "task":
      return <TaskCard data={d} />;
    case "upload":
      return <UploadDrop kind={d.kind === "linkedin" ? "linkedin" : "resume"} />;
    case "interview":
      return <button className="btn" onClick={() => navigate("/interview")}><LuMic /> Set up a mock interview</button>;
    case "applications":
      return (
        <div className="row">
          {Object.entries(d.counts || {}).map(([k, v]) => <span key={k} className="tag">{k}: <b>{String(v)}</b></span>)}
          <Link to="/tracker" className="small">Open tracker</Link>
        </div>
      );
    case "review":
      return (
        <div className="sheet pad spread">
          <span><b className="num">{Math.round(d.score)}</b> / 100 — {d.kind} review</span>
          <Link to={`/report#${d.kind === "project" ? "projects" : d.kind}`} className="small">Open review <LuExternalLink /></Link>
        </div>
      );
    default:
      return null;
  }
}
