import { ReactNode, useEffect, useState } from "react";
import { LuExternalLink, LuPencil, LuPlus, LuRefreshCw, LuTrash2 } from "react-icons/lu";
import { api, fmtDate, Json, timeAgo } from "../api";
import { UploadDrop } from "../components/Cards";
import { useAuth, useTasks, useTaskDone, useToast } from "../state";
import { ErrorNote, Loading, Modal, Segmented, useLoad } from "../ui";

function Status({ s }: { s: Json }) {
  if (s.status === "ready") return <span className="tag ok">Reviewed {timeAgo(s.updated_at)}</span>;
  if (s.status === "error") return <span className="tag bad" title={s.error}>Needs attention</span>;
  return <span className="tag warn"><span className="spinner" style={{ width: 11, height: 11 }} /> Reviewing</span>;
}

function Block({ id, title, intro, children }: { id: string; title: string; intro: string; children: ReactNode }) {
  return (
    <section className="section" id={id}>
      <h2>{title}</h2>
      <p className="muted" style={{ margin: ".3rem 0 .9rem" }}>{intro}</p>
      {children}
    </section>
  );
}

function SourceLine({ s, onDelete, onRerun, children }: { s: Json; onDelete: () => void; onRerun?: () => void; children?: ReactNode }) {
  return (
    <li>
      <div className="spread">
        <div className="grow">
          <div className="row"><b>{s.label}</b><Status s={s} /></div>
          {s.status === "error" && <div className="error-text" style={{ marginTop: ".25rem" }}>{s.error}</div>}
          {children}
        </div>
        <div className="row">
          {onRerun && <button className="btn ghost small" onClick={onRerun}><LuRefreshCw /> Re-check</button>}
          <button className="btn ghost small" onClick={onDelete}><LuTrash2 /> Delete</button>
        </div>
      </div>
    </li>
  );
}

function ProjectForm({ initial, onClose, onSaved }: { initial?: Json; onClose: () => void; onSaved: (taskId: number) => void }) {
  const [f, setF] = useState({ name: initial?.input?.name || "", repo_url: initial?.input?.repo_url || "", live_url: initial?.input?.live_url || "",
    description: initial?.input?.description || "", tech: (initial?.input?.tech || []).join(", ") });
  const [err, setErr] = useState("");
  return (
    <Modal title={initial ? "Edit project" : "Add a project"} onClose={onClose} footer={<>
      <button className="btn ghost" onClick={onClose}>Cancel</button>
      <button className="btn" onClick={async () => {
        const body = { ...f, tech: f.tech.split(",").map((t: string) => t.trim()).filter(Boolean), repo_url: f.repo_url || null, live_url: f.live_url || null };
        try {
          const res = initial ? await api.patch(`/profile/projects/${initial.id}`, body) : await api.post("/profile/projects", body);
          onSaved(res.task_id);
        } catch (e) { setErr((e as Error).message); }
      }}>{initial ? "Save and re-check" : "Add and review"}</button></>}>
      <div className="stack" style={{ "--gap": ".8rem" } as React.CSSProperties}>
        <div className="field"><label htmlFor="pn">Project name</label><input id="pn" className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></div>
        <div className="field"><label htmlFor="pr">GitHub repository</label><input id="pr" className="input" placeholder="https://github.com/you/project" value={f.repo_url} onChange={(e) => setF({ ...f, repo_url: e.target.value })} /></div>
        <div className="field"><label htmlFor="pl">Live link</label><input id="pl" className="input" placeholder="https://project.vercel.app" value={f.live_url} onChange={(e) => setF({ ...f, live_url: e.target.value })} /></div>
        <div className="field"><label htmlFor="pt">Tech stack</label><input id="pt" className="input" placeholder="React, Node.js, MongoDB" value={f.tech} onChange={(e) => setF({ ...f, tech: e.target.value })} /></div>
        <div className="field"><label htmlFor="pd">Short description</label><textarea id="pd" className="textarea" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />
          <span className="hint">Used to check that the live site matches what you claim.</span></div>
        {err && <p className="error-text">{err}</p>}
      </div>
    </Modal>
  );
}

export default function Profile() {
  const { user, setUser } = useAuth();
  const { data, error, loading, reload } = useLoad(() => api.get("/profile"), []);
  const { track } = useTasks();
  const toast = useToast();
  useTaskDone(() => reload(), [reload]);
  const [basics, setBasics] = useState({ target_role: user?.target_role || "", job_type: user?.job_type || "internship",
    target_locations: (user?.target_locations || []).join(", "), branch: user?.branch || "", batch_year: String(user?.batch_year || ""), roll_no: user?.roll_no || "" });
  const [gh, setGh] = useState("");
  const [lc, setLc] = useState({ platform: "leetcode", username: "", manual: false, solved: "", easy: "", medium: "", hard: "", contests: "", rating: "" });
  const [li, setLi] = useState({ text: "", mode: "pdf" as "pdf" | "text" });
  const [ach, setAch] = useState("");
  const [proj, setProj] = useState<Json | "new" | null>(null);
  useEffect(() => {
    if (data && location.hash) setTimeout(() => document.getElementById(location.hash.slice(1))?.scrollIntoView({ behavior: "smooth" }), 100);
  }, [data]);

  async function run(fn: () => Promise<Json>, msg: string) {
    try {
      const res = await fn();
      if (res?.task_id) track(res.task_id);
      toast.push({ text: msg });
      reload();
      return res;
    } catch (e) {
      toast.push({ kind: "error", text: (e as Error).message });
    }
  }
  const del = (id: number) => { if (confirm("Delete this and its review? This can't be undone.")) run(() => api.del(`/profile/sources/${id}`), "Deleted."); };
  const rerun = (id: number) => run(() => api.post(`/profile/sources/${id}/rerun`), "Re-checking…");

  if (loading && !data) return <div className="page"><Loading /></div>;
  if (error) return <div className="page"><ErrorNote error={error} retry={reload} /></div>;
  const S = data.sources;
  return (
    <div className="page" style={{ maxWidth: 900 }}>
      <header className="page-head">
        <div><h1>My profile</h1><p>Everything you've given OfferReady. You can change or delete any of it — reviews update automatically.</p></div>
      </header>

      <Block id="basics" title="Target" intro="Used for interview questions, skill gaps and job matching.">
        <div className="sheet pad grid-2">
          <div className="field"><label htmlFor="tr">Target role</label><input id="tr" className="input" placeholder="Backend Developer" value={basics.target_role} onChange={(e) => setBasics({ ...basics, target_role: e.target.value })} /></div>
          <div className="field"><span className="label">Looking for</span>
            <Segmented label="Job type" value={basics.job_type} onChange={(v) => setBasics({ ...basics, job_type: v })}
              options={[{ value: "internship", label: "Internship" }, { value: "fulltime", label: "Full-time" }, { value: "both", label: "Both" }]} /></div>
          <div className="field"><label htmlFor="tl">Locations</label><input id="tl" className="input" placeholder="Bengaluru, Pune, Remote" value={basics.target_locations} onChange={(e) => setBasics({ ...basics, target_locations: e.target.value })} /></div>
          <div className="field"><label htmlFor="bb">Branch and batch</label>
            <div className="row" style={{ flexWrap: "nowrap" }}><input id="bb" className="input" value={basics.branch} onChange={(e) => setBasics({ ...basics, branch: e.target.value })} aria-label="Branch" />
              <input className="input" style={{ maxWidth: 110 }} value={basics.batch_year} onChange={(e) => setBasics({ ...basics, batch_year: e.target.value })} aria-label="Batch year" /></div></div>
          <div><button className="btn" onClick={async () => {
            const res = await run(() => api.patch("/me", { target_role: basics.target_role || null, job_type: basics.job_type, branch: basics.branch || null,
              batch_year: Number(basics.batch_year) || null, target_locations: basics.target_locations.split(",").map((s) => s.trim()).filter(Boolean) }), "Saved.");
            if (res?.user) setUser(res.user);
          }}>Save</button></div>
        </div>
      </Block>

      <Block id="resume" title="Resume" intro="PDF works best (DOCX is converted). Uploading a new one replaces the old one and its review.">
        <ul className="list">{(S.resume || []).map((s: Json) => (
          <SourceLine key={s.id} s={s} onDelete={() => del(s.id)} onRerun={() => rerun(s.id)}>
            {s.extracted?.skills && <div className="small muted" style={{ marginTop: ".3rem" }}>Found {s.extracted.pages} {s.extracted.pages === 1 ? "page" : "pages"}, {s.extracted.projects?.length || 0} projects, {s.extracted.skills.length} skills.</div>}
          </SourceLine>))}</ul>
        <div style={{ marginTop: ".75rem" }}><UploadDrop kind="resume" onDone={reload} /></div>
      </Block>

      <Block id="linkedin" title="LinkedIn" intro="We never open LinkedIn ourselves. Upload your profile PDF (Profile → More → Save to PDF) or paste the text of your profile.">
        <ul className="list">{(S.linkedin || []).map((s: Json) => (
          <SourceLine key={s.id} s={s} onDelete={() => del(s.id)} onRerun={() => rerun(s.id)}>
            <div className="row small" style={{ marginTop: ".4rem" }}>
              <span className="muted">Profile photo:</span>
              <button className="btn small secondary" onClick={() => run(() => api.post("/profile/linkedin/photo", { has_photo: true }), "Noted — re-checking.")}>I have one</button>
              <button className="btn small ghost" onClick={() => run(() => api.post("/profile/linkedin/photo", { has_photo: false }), "Noted — re-checking.")}>I don't</button>
              <label className="btn small ghost">Check a screenshot<input type="file" accept="image/*" className="sr-only"
                onChange={async (e) => { const f = e.target.files?.[0]; if (f) { const r = await api.upload("/profile/linkedin/photo", f).catch((x) => toast.push({ kind: "error", text: x.message })); if (r) { toast.push({ text: r.detected ? "Photo found in your screenshot." : "No face found — add a clear photo." }); track(r.task_id); } } }} /></label>
            </div>
          </SourceLine>))}</ul>
        <div className="sheet pad stack" style={{ marginTop: ".75rem", "--gap": ".75rem" } as React.CSSProperties}>
          <Segmented label="LinkedIn input" value={li.mode} onChange={(v) => setLi({ ...li, mode: v })} options={[{ value: "pdf", label: "Upload PDF" }, { value: "text", label: "Paste text" }]} />
          {li.mode === "pdf" ? <UploadDrop kind="linkedin" onDone={reload} /> : (
            <>
              <textarea className="textarea" rows={6} value={li.text} onChange={(e) => setLi({ ...li, text: e.target.value })} placeholder="Open your profile, select everything from your name to the Skills section, copy and paste it here." aria-label="LinkedIn profile text" />
              <div><button className="btn" disabled={li.text.length < 40} onClick={() => run(() => api.post("/profile/linkedin", { text: li.text }), "LinkedIn added — reviewing now.").then(() => setLi({ ...li, text: "" }))}>Review my LinkedIn</button></div>
            </>
          )}
        </div>
      </Block>

      <Block id="github" title="GitHub" intro="Your public profile: README, pinned repos, activity and repositories. We only read public data.">
        <ul className="list">{(S.github || []).map((s: Json) => (
          <SourceLine key={s.id} s={s} onDelete={() => del(s.id)} onRerun={() => rerun(s.id)}>
            {s.extracted?.html_url && <a className="small" href={s.extracted.html_url} target="_blank" rel="noreferrer">{s.extracted.html_url} <LuExternalLink /></a>}
          </SourceLine>))}</ul>
        <form className="row" style={{ marginTop: ".75rem" }} onSubmit={(e) => { e.preventDefault(); run(() => api.post("/profile/github", { username: gh }), "GitHub added — reviewing now.").then(() => setGh("")); }}>
          <input className="input" style={{ maxWidth: 340 }} placeholder="username or github.com/username" value={gh} onChange={(e) => setGh(e.target.value)} aria-label="GitHub username" />
          <button className="btn" disabled={!gh.trim()}>{S.github?.length ? "Replace" : "Add GitHub"}</button>
        </form>
      </Block>

      <Block id="coding" title="Coding practice" intro="LeetCode (public profile data) or Codeforces (official API). Prefer typing your numbers? Enter them manually.">
        <ul className="list">{[...(S.leetcode || []), ...(S.codeforces || [])].map((s: Json) => (
          <SourceLine key={s.id} s={s} onDelete={() => del(s.id)} onRerun={() => rerun(s.id)}>
            {s.extracted?.solved != null && <div className="small muted" style={{ marginTop: ".3rem" }}>{s.extracted.solved} solved{s.extracted.medium != null ? ` (${s.extracted.easy} easy, ${s.extracted.medium} medium, ${s.extracted.hard} hard)` : ""}{s.extracted.contests ? `, ${s.extracted.contests} contests` : ""}{s.extracted.rating ? `, rating ${s.extracted.rating}` : ""}</div>}
          </SourceLine>))}</ul>
        <div className="sheet pad stack" style={{ marginTop: ".75rem", "--gap": ".75rem" } as React.CSSProperties}>
          <div className="row">
            <Segmented label="Platform" value={lc.platform} onChange={(v) => setLc({ ...lc, platform: v })} options={[{ value: "leetcode", label: "LeetCode" }, { value: "codeforces", label: "Codeforces" }]} />
            <label className="check"><input type="checkbox" checked={lc.manual} onChange={(e) => setLc({ ...lc, manual: e.target.checked })} /> Enter numbers manually</label>
          </div>
          {lc.manual ? (
            <div className="grid-2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(110px, 1fr))" }}>
              {(["solved", "easy", "medium", "hard", "contests", "rating"] as const).map((k) => (
                <div className="field" key={k}><label htmlFor={`m-${k}`}>{k[0].toUpperCase() + k.slice(1)}</label>
                  <input id={`m-${k}`} className="input" inputMode="numeric" value={lc[k]} onChange={(e) => setLc({ ...lc, [k]: e.target.value.replace(/\D/g, "") })} /></div>
              ))}
            </div>
          ) : (
            <input className="input" style={{ maxWidth: 340 }} placeholder={lc.platform === "leetcode" ? "leetcode.com/u/username" : "codeforces handle"} value={lc.username} onChange={(e) => setLc({ ...lc, username: e.target.value })} aria-label="Username" />
          )}
          <div><button className="btn" onClick={() => run(() => api.post("/profile/coding", lc.manual
            ? { platform: lc.platform, username: lc.username || null, manual: { solved: lc.solved, easy: lc.easy, medium: lc.medium, hard: lc.hard, contests: lc.contests, rating: lc.rating } }
            : { platform: lc.platform, username: lc.username }), "Coding profile added — checking now.")}>Save</button></div>
        </div>
      </Block>

      <Block id="projects" title="Projects" intro="Each project's repository is cloned and checked (README, code, commits, secrets, tests) and its live link is opened on desktop and mobile.">
        <ul className="list">{(S.project || []).map((s: Json) => (
          <SourceLine key={s.id} s={s} onDelete={() => del(s.id)} onRerun={() => rerun(s.id)}>
            <div className="row small" style={{ marginTop: ".3rem" }}>
              {s.input.repo_url && <a href={s.input.repo_url} target="_blank" rel="noreferrer">Repo <LuExternalLink /></a>}
              {s.input.live_url && <a href={s.input.live_url} target="_blank" rel="noreferrer">Live <LuExternalLink /></a>}
              {s.input.from_resume && <span className="tag">From your resume</span>}
              {s.extracted?.score != null && <span className="num"><b>{Math.round(s.extracted.score)}</b> / 100</span>}
              <button className="btn ghost small" onClick={() => setProj(s)}><LuPencil /> Edit</button>
            </div>
          </SourceLine>))}</ul>
        <button className="btn" style={{ marginTop: ".75rem" }} onClick={() => setProj("new")}><LuPlus /> Add a project</button>
      </Block>

      <Block id="achievements" title="Achievements" intro="Hackathons, contests, club roles, certifications. Items from your resume's achievements section are included automatically.">
        <ul className="list">{(S.achievement || []).map((s: Json) => (
          <li key={s.id} className="spread"><span>{s.input.text}</span><button className="btn ghost small" onClick={() => del(s.id)}><LuTrash2 /> Delete</button></li>))}</ul>
        <form className="row" style={{ marginTop: ".75rem" }} onSubmit={(e) => { e.preventDefault(); run(() => api.post("/profile/achievements", { text: ach }), "Added.").then(() => setAch("")); }}>
          <input className="input grow" placeholder="e.g. Finalist (top 10 of 140 teams), Smart India Hackathon 2025" value={ach} onChange={(e) => setAch(e.target.value)} aria-label="Achievement" />
          <button className="btn" disabled={ach.trim().length < 6}>Add</button>
        </form>
      </Block>

      <p className="small muted" style={{ marginTop: "2.5rem" }}>Account created {fmtDate(user?.created_at)}. Download or delete all your data from Settings.</p>
      {proj && <ProjectForm initial={proj === "new" ? undefined : proj} onClose={() => setProj(null)} onSaved={(tid) => { track(tid); setProj(null); toast.push({ text: "Project saved — reviewing now." }); reload(); }} />}
    </div>
  );
}
