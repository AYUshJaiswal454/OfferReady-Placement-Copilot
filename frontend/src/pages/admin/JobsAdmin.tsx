import { useState } from "react";
import { LuPlus } from "react-icons/lu";
import { api, fmtDate, Json } from "../../api";
import { Link, navigate } from "../../router";
import { useToast } from "../../state";
import { Empty, ErrorNote, Loading, useLoad } from "../../ui";

const BLANK = { title: "", company: "", location: "", employment_type: "internship", stipend: "", description: "", apply_url: "",
  skills: "", min_score: "", batches: "2026", branches: "", deadline: "", status: "open" };

function JobForm({ job, onSaved, onCancel }: { job?: Json; onSaved: () => void; onCancel: () => void }) {
  const [f, setF] = useState<Json>(job ? {
    ...BLANK, ...job, skills: (job.skills || []).join(", "), min_score: job.eligibility?.min_score ?? "", batches: (job.eligibility?.batches || []).join(", "),
    branches: (job.eligibility?.branches || []).join(", "), stipend: job.stipend || "", apply_url: job.apply_url || "", deadline: job.deadline || "", location: job.location || "",
  } : BLANK);
  const [err, setErr] = useState("");
  const toast = useToast();
  const set = (k: string) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const list = (s: string) => s.split(",").map((x: string) => x.trim()).filter(Boolean);
  async function save() {
    const body = { title: f.title, company: f.company, location: f.location || null, employment_type: f.employment_type, stipend: f.stipend || null,
      description: f.description, apply_url: f.apply_url || null, skills: list(f.skills), min_score: f.min_score === "" ? null : Number(f.min_score),
      batches: list(f.batches).map(Number).filter(Boolean), branches: list(f.branches), deadline: f.deadline || null, status: f.status };
    try {
      if (job) await api.patch(`/admin/jobs/${job.id}`, body); else await api.post("/admin/jobs", body);
      toast.push({ text: job ? "Job updated." : "Job posted — eligible students were notified." });
      onSaved();
    } catch (e) { setErr((e as Error).message); }
  }
  return (
    <div className="sheet pad stack" style={{ "--gap": "1rem" } as React.CSSProperties}>
      <h2>{job ? "Edit job" : "Post a job to students"}</h2>
      <div className="grid-2">
        <div className="field"><label htmlFor="j-t">Role</label><input id="j-t" className="input" value={f.title} onChange={set("title")} /></div>
        <div className="field"><label htmlFor="j-c">Company</label><input id="j-c" className="input" value={f.company} onChange={set("company")} /></div>
        <div className="field"><label htmlFor="j-l">Location</label><input id="j-l" className="input" value={f.location} onChange={set("location")} placeholder="Bengaluru / Remote" /></div>
        <div className="field"><label htmlFor="j-e">Type</label><select id="j-e" className="select" value={f.employment_type} onChange={set("employment_type")}>
          <option value="internship">Internship</option><option value="fulltime">Full-time</option><option value="contract">Contract</option></select></div>
        <div className="field"><label htmlFor="j-s">Stipend / CTC</label><input id="j-s" className="input" value={f.stipend} onChange={set("stipend")} /></div>
        <div className="field"><label htmlFor="j-d">Apply by</label><input id="j-d" type="date" className="input" value={f.deadline} onChange={set("deadline")} /></div>
      </div>
      <div className="field"><label htmlFor="j-desc">Description</label><textarea id="j-desc" className="textarea" rows={6} value={f.description} onChange={set("description")} placeholder="Responsibilities, requirements, selection process…" /></div>
      <div className="field"><label htmlFor="j-u">External apply link (optional)</label><input id="j-u" className="input" value={f.apply_url} onChange={set("apply_url")} /></div>
      <h3>Eligibility</h3>
      <div className="grid-2">
        <div className="field"><label htmlFor="j-ms">Minimum readiness score</label><input id="j-ms" className="input" inputMode="numeric" value={f.min_score} onChange={set("min_score")} placeholder="e.g. 60" /></div>
        <div className="field"><label htmlFor="j-b">Batches</label><input id="j-b" className="input" value={f.batches} onChange={set("batches")} placeholder="2026, 2027" /></div>
        <div className="field"><label htmlFor="j-br">Branches (empty = all)</label><input id="j-br" className="input" value={f.branches} onChange={set("branches")} placeholder="CSE, IT" /></div>
        <div className="field"><label htmlFor="j-sk">Required skills</label><input id="j-sk" className="input" value={f.skills} onChange={set("skills")} placeholder="Java, SQL" /></div>
      </div>
      {job && <label className="check"><input type="checkbox" checked={f.status === "closed"} onChange={(e) => setF({ ...f, status: e.target.checked ? "closed" : "open" })} /> Closed (hidden from students)</label>}
      {err && <p className="error-text">{err}</p>}
      <div className="row"><button className="btn" onClick={save}>{job ? "Save" : "Post job"}</button><button className="btn ghost" onClick={onCancel}>Cancel</button></div>
    </div>
  );
}

function Applicants({ id }: { id: number }) {
  const { data, error, loading, reload } = useLoad(() => api.get(`/admin/jobs/${id}/applicants`), [id]);
  const [editing, setEditing] = useState(false);
  const toast = useToast();
  if (loading && !data) return <div className="page"><Loading /></div>;
  if (error) return <div className="page"><ErrorNote error={error} retry={reload} /></div>;
  const job = data.job;
  return (
    <div className="page">
      <header className="page-head">
        <div><Link to="/admin/jobs" className="small">All jobs</Link><h1 style={{ marginTop: ".3rem" }}>{job.title} — {job.company}</h1>
          <p>{data.applicants.length} applicants. Status changes appear instantly in each student's tracker, with a notification.</p></div>
        <button className="btn secondary" onClick={() => setEditing(!editing)}>{editing ? "Close editor" : "Edit job"}</button>
      </header>
      {editing && <div style={{ marginBottom: "2rem" }}><JobForm job={job} onSaved={() => { setEditing(false); reload(); }} onCancel={() => setEditing(false)} /></div>}
      {data.applicants.length === 0 ? <Empty title="No applicants yet">Eligible students were notified when you posted this job.</Empty> : (
        <div className="table-wrap"><table className="data">
          <thead><tr><th>Student</th><th>Batch</th><th>Readiness</th><th>Applied</th><th>Report</th><th>Status</th></tr></thead>
          <tbody>{data.applicants.map((a: Json) => (
            <tr key={a.id}>
              <td><b>{a.name}</b><div className="small muted">{a.roll_no || a.email}</div></td>
              <td>{a.batch_year} {a.branch}</td>
              <td className="num">{a.readiness != null ? Math.round(a.readiness) : "—"} <span className="small muted">{a.level || ""}</span></td>
              <td className="small">{fmtDate(a.applied_at)}</td>
              <td>{a.shared_report ? <Link to={`/admin/students/${a.student_id}`}>View report</Link> : <span className="muted small">Not shared</span>}</td>
              <td>
                <select className="select" style={{ minHeight: 34, padding: ".2rem .4rem" }} value={a.status} aria-label={`Status for ${a.name}`} onChange={async (e) => {
                  const note = ["shortlisted", "interview", "rejected", "offer"].includes(e.target.value) ? prompt("Message to the student (optional)", "") : null;
                  try { await api.patch(`/admin/applications/${a.id}`, { status: e.target.value, note: note || null }); toast.push({ text: `${a.name} → ${e.target.value}. Student notified.` }); reload(); }
                  catch (err) { toast.push({ kind: "error", text: (err as Error).message }); }
                }}>
                  {["applied", "shortlisted", "interview", "offer", "rejected"].map((s) => <option key={s} value={s}>{s[0].toUpperCase() + s.slice(1)}</option>)}
                </select>
              </td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
    </div>
  );
}

export default function AdminJobs({ id }: { id?: number }) {
  const { data, error, loading, reload } = useLoad(() => api.get("/admin/jobs"), []);
  const [creating, setCreating] = useState(false);
  if (id) return <Applicants id={id} />;
  if (loading && !data) return <div className="page"><Loading /></div>;
  if (error) return <div className="page"><ErrorNote error={error} retry={reload} /></div>;
  return (
    <div className="page">
      <header className="page-head">
        <div><h1>MSOT job board</h1><p>Jobs posted here appear at the top of the Jobs page for eligible students, who can apply in one click.</p></div>
        {!creating && <button className="btn" onClick={() => setCreating(true)}><LuPlus /> Post a job</button>}
      </header>
      {creating && <div style={{ marginBottom: "2rem" }}><JobForm onSaved={() => { setCreating(false); reload(); }} onCancel={() => setCreating(false)} /></div>}
      {data.jobs.length === 0 ? <Empty title="No jobs posted yet" action={!creating && <button className="btn" onClick={() => setCreating(true)}>Post the first job</button>} /> : (
        <ul className="list">{data.jobs.map((j: Json) => (
          <li key={j.id} className="spread">
            <div>
              <a href={`/admin/jobs/${j.id}`} onClick={(e) => { e.preventDefault(); navigate(`/admin/jobs/${j.id}`); }}><b>{j.title}</b></a> — {j.company}
              <div className="small muted">{j.employment_type}{j.location ? `, ${j.location}` : ""}{j.deadline ? `, apply by ${j.deadline}` : ""}{j.eligibility?.min_score ? `, readiness ≥ ${j.eligibility.min_score}` : ""}</div>
            </div>
            <div className="row"><span className={`tag ${j.status === "open" ? "ok" : ""}`}>{j.status}</span><span className="num"><b>{j.applicants}</b> applicants</span></div>
          </li>
        ))}</ul>
      )}
    </div>
  );
}
