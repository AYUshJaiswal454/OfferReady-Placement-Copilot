import { useState } from "react";
import { LuCalendarDays, LuExternalLink, LuPlus, LuTrash2 } from "react-icons/lu";
import { api, fmtDate, Json, timeAgo } from "../api";
import { Link } from "../router";
import { useToast } from "../state";
import { ErrorNote, Loading, Modal, useLoad } from "../ui";

function Drawer({ app, statuses, onClose, onChange }: { app: Json; statuses: Json[]; onClose: () => void; onChange: () => void }) {
  const [notes, setNotes] = useState(app.notes || "");
  const [when, setWhen] = useState(app.interview_at ? app.interview_at.slice(0, 16) : "");
  const toast = useToast();
  const managed = !!app.msot_job_id;
  return (
    <Modal title={`${app.company} — ${app.title}`} onClose={onClose} footer={<>
      {!managed && <button className="btn ghost" onClick={async () => { if (confirm("Remove this application from your tracker?")) { await api.del(`/applications/${app.id}`); onClose(); onChange(); } }}><LuTrash2 /> Remove</button>}
      <button className="btn" onClick={async () => {
        try {
          await api.patch(`/applications/${app.id}`, { notes, interview_at: when ? new Date(when).toISOString() : undefined });
          toast.push({ text: "Saved." }); onClose(); onChange();
        } catch (e) { toast.push({ kind: "error", text: (e as Error).message }); }
      }}>Save</button></>}>
      <div className="stack" style={{ "--gap": "1rem" } as React.CSSProperties}>
        {managed && <div className="notice info small">This is an MSOT application — the placement cell updates its status.</div>}
        {app.url && !app.url.includes("manual.offerready.local") && <a href={app.url} target="_blank" rel="noreferrer">Job posting <LuExternalLink /></a>}
        <dl className="kv small">
          <dt>Source</dt><dd>{app.source}</dd>
          {app.match_score != null && <><dt>Match</dt><dd>{Math.round(app.match_score)}%</dd></>}
          {app.applied_at && <><dt>Applied</dt><dd>{fmtDate(app.applied_at)}</dd></>}
          {app.next_follow_up_at && <><dt>Follow up</dt><dd>{fmtDate(app.next_follow_up_at)}</dd></>}
        </dl>
        <div>
          <span className="label">History</span>
          <ol className="list small" style={{ marginTop: ".3rem" }}>
            {(app.status_history || []).map((h: Json, i: number) => (
              <li key={i} style={{ padding: ".4rem 0" }}><b>{statuses.find((s) => s.key === h.status)?.label || h.status}</b> — {fmtDate(h.at, true)}{h.by && h.by !== "student" ? " (placement cell)" : ""}{h.note ? `: ${h.note}` : ""}</li>
            ))}
          </ol>
        </div>
        <div className="field"><label htmlFor="iv-at">Interview date and time</label>
          <input id="iv-at" type="datetime-local" className="input" value={when} onChange={(e) => setWhen(e.target.value)} /></div>
        <div className="field"><label htmlFor="notes">Notes</label>
          <textarea id="notes" className="textarea" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Recruiter name, referral, test date…" /></div>
      </div>
    </Modal>
  );
}

export default function Tracker() {
  const { data, error, loading, reload } = useLoad(() => api.get("/applications"), []);
  const [over, setOver] = useState<string | null>(null);
  const [open, setOpen] = useState<Json | null>(null);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ title: "", company: "", url: "", status: "applied" });
  const toast = useToast();

  async function move(app: Json, status: string) {
    if (app.status === status) return;
    try {
      await api.patch(`/applications/${app.id}`, { status });
      reload();
    } catch (e) { toast.push({ kind: "error", text: (e as Error).message }); }
  }

  if (loading && !data) return <div className="page"><Loading /></div>;
  if (error) return <div className="page"><ErrorNote error={error} retry={reload} /></div>;
  const total = Object.values(data.counts as Record<string, number>).reduce((a, b) => a + b, 0);
  return (
    <div className="page" style={{ maxWidth: "none" }}>
      <header className="page-head">
        <div>
          <h1>Applications</h1>
          <p>{total ? `${data.funnel.applied_or_later} applied, ${data.funnel.responses} with a response so far.` : "Every job you save or apply to, in one place."} Drag a card to change its status.</p>
        </div>
        <div className="row">
          <a className="btn secondary" href="/api/applications.ics"><LuCalendarDays /> Interviews to calendar</a>
          <button className="btn" onClick={() => setAdding(true)}><LuPlus /> Add application</button>
        </div>
      </header>

      {data.due_follow_ups.length > 0 && (
        <div className="notice" style={{ marginBottom: "1.25rem" }}>
          <b>Follow-ups due:</b> {data.due_follow_ups.map((a: Json) => `${a.company} (${a.title})`).join(", ")}. A short polite email or LinkedIn message to the recruiter often moves things along.
        </div>
      )}
      {total === 0 && (
        <div className="empty" style={{ marginBottom: "1.25rem" }}><h3>No applications yet</h3><p style={{ margin: "0 auto" }}>Save jobs from the Jobs page or add one you found elsewhere.</p>
          <Link to="/jobs" className="btn">Find jobs</Link></div>
      )}

      <div className="board">
        {data.statuses.map((s: Json) => (
          <section key={s.key} className={`col ${over === s.key ? "over" : ""}`} aria-label={s.label}
            onDragOver={(e) => { e.preventDefault(); setOver(s.key); }} onDragLeave={() => setOver(null)}
            onDrop={(e) => {
              e.preventDefault(); setOver(null);
              const id = Number(e.dataTransfer.getData("text/plain"));
              const app = Object.values(data.columns as Record<string, Json[]>).flat().find((a) => a.id === id);
              if (app) {
                if (app.msot_job_id && !["saved", "applied"].includes(s.key)) toast.push({ kind: "error", text: "The placement cell updates MSOT applications." });
                else move(app, s.key);
              }
            }}>
            <h3><span>{s.label}</span><span className="muted">{data.counts[s.key]}</span></h3>
            {data.columns[s.key].map((a: Json) => {
              const due = a.next_follow_up_at && new Date(a.next_follow_up_at) <= new Date() && ["applied", "shortlisted"].includes(a.status);
              return (
                <article key={a.id} className="app-card" draggable onDragStart={(e) => e.dataTransfer.setData("text/plain", String(a.id))}>
                  <button className="btn ghost" style={{ padding: 0, minHeight: 0, display: "block", textAlign: "left", whiteSpace: "normal", fontWeight: 400 }} onClick={() => setOpen(a)}>
                    <div className="co">{a.company} {a.msot_job_id && <span className="tag msot" style={{ fontSize: ".7rem" }}>MSOT</span>}</div>
                    <div className="ti">{a.title}</div>
                  </button>
                  <div className="foot">
                    <span className="small muted">{due ? <span className="due">Follow up</span> : a.interview_at ? `Interview ${fmtDate(a.interview_at)}` : timeAgo(a.updated_at)}</span>
                    <label className="sr-only" htmlFor={`st-${a.id}`}>Status</label>
                    <select id={`st-${a.id}`} value={a.status} onChange={(e) => move(a, e.target.value)} disabled={!!a.msot_job_id && !["saved", "applied"].includes(a.status)}>
                      {data.statuses.map((x: Json) => <option key={x.key} value={x.key} disabled={!!a.msot_job_id && !["saved", "applied"].includes(x.key)}>{x.label}</option>)}
                    </select>
                  </div>
                </article>
              );
            })}
          </section>
        ))}
      </div>

      {open && <Drawer app={open} statuses={data.statuses} onClose={() => setOpen(null)} onChange={reload} />}
      {adding && (
        <Modal title="Add an application" onClose={() => setAdding(false)} footer={<>
          <button className="btn ghost" onClick={() => setAdding(false)}>Cancel</button>
          <button className="btn" disabled={!form.title || !form.company} onClick={async () => {
            try { await api.post("/applications", { ...form, url: form.url || null }); setAdding(false); setForm({ title: "", company: "", url: "", status: "applied" }); reload(); }
            catch (e) { toast.push({ kind: "error", text: (e as Error).message }); }
          }}>Add</button></>}>
          <div className="stack" style={{ "--gap": ".75rem" } as React.CSSProperties}>
            <div className="field"><label htmlFor="a-t">Role</label><input id="a-t" className="input" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></div>
            <div className="field"><label htmlFor="a-c">Company</label><input id="a-c" className="input" value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} /></div>
            <div className="field"><label htmlFor="a-u">Link (optional)</label><input id="a-u" className="input" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} /></div>
            <div className="field"><label htmlFor="a-s">Status</label>
              <select id="a-s" className="select" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                {data.statuses.map((x: Json) => <option key={x.key} value={x.key}>{x.label}</option>)}
              </select></div>
          </div>
        </Modal>
      )}
    </div>
  );
}
