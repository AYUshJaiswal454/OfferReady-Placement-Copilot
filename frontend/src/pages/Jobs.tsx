import { Fragment, useEffect, useState } from "react";
import { LuBookmark, LuExternalLink, LuPlus, LuSearch } from "react-icons/lu";
import { api, Json, timeAgo } from "../api";
import { Link } from "../router";
import { useToast } from "../state";
import { Empty, ErrorNote, Loading, Modal, Segmented } from "../ui";

function JobRow({ r, onSave, onOpen }: { r: Json; onSave: () => void; onOpen: () => void }) {
  const j = r.job;
  const [open, setOpen] = useState(false);
  return (
    <li>
      <div className="job">
        <div className="job-match" title="Match with your profile">{r.match}<small>match</small></div>
        <div style={{ minWidth: 0 }}>
          <h3>{j.title}</h3>
          <div className="meta">
            {j.company}{j.location ? `, ${j.location}` : ""} — {j.employment_type === "internship" ? "Internship" : j.employment_type === "fulltime" ? "Full-time" : j.employment_type}
            {j.salary ? `, ${j.salary}` : ""}{j.posted_at ? `, posted ${timeAgo(j.posted_at)}` : ""}
          </div>
          <div className="why">{r.reasons.slice(1, 4).join(". ")}.</div>
          <div className="skills">
            {r.matched_skills.map((s: string) => <span className="tag have" key={s} title="You have this">{s}</span>)}
            {r.missing_skills.map((s: string) => <span className="tag miss" key={s} title="Asked for; not on your profile">{s}</span>)}
          </div>
          <div className="small muted" style={{ marginTop: ".45rem" }}>
            Source: {j.source_label}{j.also_on?.length ? ` (also on ${j.also_on.map((a: Json) => a.source).join(", ")})` : ""}
            {" "}<button className="btn ghost small" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? "Hide description" : "Show description"}</button>
          </div>
          {open && <p className="small" style={{ whiteSpace: "pre-wrap", marginTop: ".5rem", maxWidth: "75ch" }}>{j.description}</p>}
        </div>
        <div className="job-actions">
          <a className="btn small" href={j.url} target="_blank" rel="noreferrer" onClick={onOpen}>Open and apply <LuExternalLink /></a>
          {r.application ? <span className="tag ok" style={{ justifyContent: "center" }}>{r.application.status}</span>
            : <button className="btn small secondary" onClick={onSave}><LuBookmark /> Save</button>}
        </div>
      </div>
    </li>
  );
}

function MsotRow({ r, onApply }: { r: Json; onApply: () => void }) {
  const j = r.job;
  return (
    <li>
      <div className="job">
        <div className="job-match">{r.match}<small>match</small></div>
        <div>
          <div className="row" style={{ gap: ".5rem" }}><span className="tag msot">MSOT</span><h3>{j.title}</h3></div>
          <div className="meta">{j.company}{j.location ? `, ${j.location}` : ""}{j.stipend ? `, ${j.stipend}` : ""}{j.deadline ? `. Apply by ${j.deadline}` : ""}</div>
          <p className="small" style={{ marginTop: ".4rem" }}>{j.description.slice(0, 260)}{j.description.length > 260 ? "…" : ""}</p>
          {!r.eligible && <div className="notice small" style={{ marginTop: ".5rem" }}>Not eligible yet: {r.ineligible_reasons.join("; ")}. <Link to="/readiness">See how to raise your score</Link></div>}
        </div>
        <div className="job-actions">
          {r.application ? <span className="tag ok" style={{ justifyContent: "center" }}>{r.application.status}</span>
            : <button className="btn small marker" disabled={!r.eligible} onClick={onApply}>Apply through MSOT</button>}
        </div>
      </div>
    </li>
  );
}

const GOOD_MATCH = 50;   // below this a result is shown under "Weaker matches"

export default function Jobs() {
  const [query, setQuery] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [type, setType] = useState("all");
  const [remote, setRemote] = useState(false);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Json | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [applyTo, setApplyTo] = useState<Json | null>(null);
  const [share, setShare] = useState(true);
  const [paste, setPaste] = useState(false);
  const [pasteForm, setPasteForm] = useState({ title: "", company: "", url: "", description: "" });
  const [askApplied, setAskApplied] = useState<Json | null>(null);
  const toast = useToast();

  async function load(q = query, p = page) {
    setLoading(true);
    try {
      const res = await api.get("/jobs", { q: q || undefined, type, remote: remote ? 1 : undefined, page: p });
      if (res.error) { setError(res.error); } else { setError(null); setData(res); if (draft === "" || q === null) setDraft(res.query); }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [query, type, remote, page]);

  // "Did you apply?" when the student comes back from a job page.
  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState === "visible") {
        const pending = sessionStorage.getItem("or-opened-job");
        if (pending) { setAskApplied(JSON.parse(pending)); sessionStorage.removeItem("or-opened-job"); }
      }
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  async function save(jobId: number, status = "saved") {
    try {
      await api.post("/applications", { job_id: jobId, status });
      toast.push({ text: status === "applied" ? "Marked as applied — we'll remind you to follow up in 7 days." : "Saved to your tracker.", href: "/tracker", linkText: "Open tracker" });
      load();
    } catch (e) { toast.push({ kind: "error", text: (e as Error).message }); }
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Jobs and internships</h1>
          <p>Ranked by how well each one fits your skills, target role, level and location — with the reason for every match.</p>
        </div>
        <button className="btn secondary" onClick={() => setPaste(true)}><LuPlus /> Add a job you found</button>
      </header>

      <div className="sheet pad stack" style={{ "--gap": ".75rem" } as React.CSSProperties}>
        <label className="label" htmlFor="q">Search query (boolean: AND, OR, NOT, "quotes", brackets)</label>
        <textarea id="q" className="textarea query-box" rows={2} value={draft} onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); setPage(1); setQuery(draft); } }} />
        <div className="spread">
          <div className="row">
            <Segmented label="Type" value={type} onChange={(v) => { setPage(1); setType(v); }} options={[{ value: "all", label: "All" }, { value: "internship", label: "Internships" }, { value: "fulltime", label: "Full-time" }]} />
            <label className="check"><input type="checkbox" checked={remote} onChange={(e) => { setPage(1); setRemote(e.target.checked); }} /> Remote only</label>
          </div>
          <div className="row">
            {data && draft !== data.default_query.query && <button className="btn ghost small" onClick={() => { setDraft(data.default_query.query); setPage(1); setQuery(null); }}>Use my profile's query</button>}
            <button className="btn" onClick={() => { setPage(1); setQuery(draft); }}><LuSearch /> Search</button>
          </div>
        </div>
        {data && <p className="small muted">Built from your skills ({data.default_query.skills.join(", ") || "add skills via your resume"}), target role and locations. Edit it freely.</p>}
      </div>

      {error && <div style={{ marginTop: "1rem" }}><ErrorNote error={error} /></div>}

      {data && (data.msot.eligible.length > 0 || data.msot.ineligible.length > 0) && (
        <section className="section pinned">
          <h3>From the MSOT placement cell</h3>
          <ul className="list">
            {[...data.msot.eligible, ...data.msot.ineligible].map((r: Json) => <MsotRow key={`m${r.job.id}`} r={r} onApply={() => setApplyTo(r.job)} />)}
          </ul>
        </section>
      )}

      <section className="section">
        <div className="spread" style={{ marginBottom: ".5rem" }}>
          <h2>{data ? `${data.total} matching openings` : "Openings"}</h2>
          {loading && <span className="spinner" />}
        </div>
        {data && data.results.length === 0 && !loading ? (
          <Empty title="Nothing matches this query">Try removing a location or skill from the query, or switch the type to All.</Empty>
        ) : data ? (
          <ul className="list">
            {data.results.map((r: Json, i: number) => {
              const firstWeak = r.match < GOOD_MATCH && (i === 0 || data.results[i - 1].match >= GOOD_MATCH);
              return (
                <Fragment key={r.job.id}>
                  {firstWeak && <li className="weak-divider"><h3>Weaker matches</h3><p className="small muted">These share a few keywords with your query but fit your skills or target role less well.</p></li>}
                  <JobRow r={r} onSave={() => save(r.job.id)}
                    onOpen={() => sessionStorage.setItem("or-opened-job", JSON.stringify({ id: r.job.id, title: r.job.title, company: r.job.company }))} />
                </Fragment>
              );
            })}
          </ul>
        ) : loading ? <Loading /> : null}
        {data && data.total > data.per_page && (
          <div className="row" style={{ justifyContent: "center", marginTop: "1rem" }}>
            <button className="btn secondary small" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
            <span className="small muted">Page {page} of {Math.ceil(data.total / data.per_page)}</span>
            <button className="btn secondary small" disabled={page * data.per_page >= data.total} onClick={() => setPage(page + 1)}>Next</button>
          </div>
        )}
      </section>

      {data && (
        <section className="section">
          <h2 style={{ marginBottom: ".4rem" }}>Search on other sites</h2>
          <p className="muted small" style={{ marginBottom: ".75rem" }}>These sites don't allow automated collection, so we don't scrape them. These links open the same search in your browser; add anything you apply to with "Add a job you found".</p>
          <div className="row">{data.deep_links.map((d: Json) => <a key={d.site} className="btn secondary small" href={d.url} target="_blank" rel="noreferrer">{d.site} <LuExternalLink /></a>)}</div>
        </section>
      )}

      {applyTo && (
        <Modal title={`Apply: ${applyTo.title}`} onClose={() => setApplyTo(null)} footer={<>
          <button className="btn ghost" onClick={() => setApplyTo(null)}>Cancel</button>
          <button className="btn" onClick={async () => {
            try {
              await api.post(`/msot/jobs/${applyTo.id}/apply`, { share_report: share });
              toast.push({ text: "Applied. The placement cell will update your status in the tracker.", href: "/tracker", linkText: "Open tracker" });
              setApplyTo(null); load();
            } catch (e) { toast.push({ kind: "error", text: (e as Error).message }); }
          }}>Apply</button></>}>
          <p>{applyTo.company}{applyTo.location ? `, ${applyTo.location}` : ""}</p>
          <label className="check" style={{ marginTop: "1rem" }}>
            <input type="checkbox" checked={share} onChange={(e) => setShare(e.target.checked)} />
            <span>Share my readiness report (resume, project and interview reviews) with the MSOT placement cell for this application.</span>
          </label>
        </Modal>
      )}

      {askApplied && (
        <Modal title="Did you apply?" onClose={() => setAskApplied(null)} footer={<>
          <button className="btn ghost" onClick={() => setAskApplied(null)}>Not yet</button>
          <button className="btn secondary" onClick={() => { save(askApplied.id, "saved"); setAskApplied(null); }}>Save for later</button>
          <button className="btn" onClick={() => { save(askApplied.id, "applied"); setAskApplied(null); }}>Yes, I applied</button></>}>
          <p>You opened <b>{askApplied.title}</b> at {askApplied.company}. Track it so you get a follow-up reminder.</p>
        </Modal>
      )}

      {paste && (
        <Modal title="Add a job you found" onClose={() => setPaste(false)} footer={<>
          <button className="btn ghost" onClick={() => setPaste(false)}>Cancel</button>
          <button className="btn" disabled={!pasteForm.title || !pasteForm.company} onClick={async () => {
            try {
              const res = await api.post("/jobs/import", { ...pasteForm, url: pasteForm.url || null, description: pasteForm.description || null });
              toast.push({ text: res.match ? `Added to your tracker — ${res.match.match}% match.` : "Added to your tracker.", href: "/tracker", linkText: "Open tracker" });
              setPaste(false); setPasteForm({ title: "", company: "", url: "", description: "" });
            } catch (e) { toast.push({ kind: "error", text: (e as Error).message }); }
          }}>Add to tracker</button></>}>
          <div className="stack" style={{ "--gap": ".75rem" } as React.CSSProperties}>
            <p className="small muted">From LinkedIn, Naukri, a referral or a company site. Paste the description to see how well it matches you.</p>
            <div className="field"><label htmlFor="pt">Job title</label><input id="pt" className="input" value={pasteForm.title} onChange={(e) => setPasteForm({ ...pasteForm, title: e.target.value })} /></div>
            <div className="field"><label htmlFor="pc">Company</label><input id="pc" className="input" value={pasteForm.company} onChange={(e) => setPasteForm({ ...pasteForm, company: e.target.value })} /></div>
            <div className="field"><label htmlFor="pu">Link (optional)</label><input id="pu" className="input" value={pasteForm.url} onChange={(e) => setPasteForm({ ...pasteForm, url: e.target.value })} /></div>
            <div className="field"><label htmlFor="pd">Description (optional)</label><textarea id="pd" className="textarea" value={pasteForm.description} onChange={(e) => setPasteForm({ ...pasteForm, description: e.target.value })} /></div>
          </div>
        </Modal>
      )}
    </div>
  );
}
