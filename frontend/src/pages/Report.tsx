import { useEffect, useState } from "react";
import { LuExternalLink, LuPrinter, LuRefreshCw } from "react-icons/lu";
import { api, fileUrl, fmtDate, Json } from "../api";
import ResumeViewer from "../components/ResumeViewer";
import { Link } from "../router";
import { useTasks, useTaskDone, useToast } from "../state";
import { ChecksList, CopyBlock, Empty, ErrorNote, Loading, ScoreBlock, useLoad } from "../ui";

const SECTIONS = [["resume", "Resume"], ["projects", "Projects"], ["github", "GitHub"], ["linkedin", "LinkedIn"], ["coding", "Coding practice"],
  ["achievements", "Achievements"], ["interview", "Mock interview"]];

function Rerun({ sourceId }: { sourceId?: number }) {
  const { track } = useTasks();
  const toast = useToast();
  if (!sourceId) return null;
  return (
    <button className="btn small secondary no-print" onClick={async () => {
      try { const r = await api.post(`/profile/sources/${sourceId}/rerun`); track(r.task_id); toast.push({ text: "Re-running the review…" }); }
      catch (e) { toast.push({ kind: "error", text: (e as Error).message }); }
    }}><LuRefreshCw /> Re-run</button>
  );
}

function SectionHead({ id, title, review, extra }: { id: string; title: string; review?: Json; extra?: React.ReactNode }) {
  return (
    <div className="spread" style={{ marginBottom: ".9rem" }} id={id}>
      <div>
        <h2>{title}</h2>
        {review && <p className="small muted" style={{ marginTop: ".25rem" }}>Checked {fmtDate(review.created_at, true)} against benchmark {review.benchmark_version}</p>}
      </div>
      <div className="row">
        {review && <span className="score-mini num">{Math.round(review.score)}<span className="muted small"> / 100</span></span>}
        {extra}
      </div>
    </div>
  );
}

function ResumeSection({ review }: { review?: Json }) {
  const [focus, setFocus] = useState<string | null>(null);
  if (!review) return <Empty title="No resume yet" action={<Link to="/" className="btn">Upload it in the Copilot</Link>}>Your resume is 25% of your readiness score.</Empty>;
  const data = review.data || {};
  return (
    <div className="stack" style={{ "--gap": "1.5rem" } as React.CSSProperties}>
      <p style={{ fontSize: "var(--step-1)" }} className="serif">{review.summary}</p>
      {data.warnings?.map((w: string) => <div className="notice" key={w}>{w}</div>)}
      <ResumeViewer review={review} focusCheck={focus} onPick={setFocus} />
      {focus && <button className="btn small secondary no-print" onClick={() => setFocus(null)}>Show all marks</button>}
      <ChecksList checks={review.checks} activeId={focus || undefined} onToggle={setFocus}
        onEvidence={(c) => { setFocus(c.id); document.querySelector(".viewer")?.scrollIntoView({ behavior: "smooth" }); }} />
      {review.rewrites?.bullets?.length > 0 && (
        <div>
          <h3 style={{ marginBottom: ".6rem" }}>Suggested rewrites</h3>
          <p className="muted small" style={{ marginBottom: ".75rem" }}>Replace anything in [brackets] with your real numbers — never invent results.</p>
          <ul className="list">
            {review.rewrites.bullets.map((b: Json, i: number) => (
              <li key={i}>
                <div className="muted" style={{ textDecoration: "line-through", textDecorationColor: "var(--red)" }}>{b.text}</div>
                <div style={{ marginTop: ".35rem" }}><CopyBlock text={b.rewrite} /></div>
              </li>
            ))}
          </ul>
        </div>
      )}
      {data.insights?.length > 0 && (
        <div>
          <h3 style={{ marginBottom: ".6rem" }}>More suggestions</h3>
          <ul className="list">
            {data.insights.map((ins: Json, i: number) => <li key={i}><b>{ins.title}.</b> {ins.text}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

function ProjectBlock({ review }: { review: Json }) {
  const d = review.data || {};
  const p = d.project || {};
  const shots = d.screenshots || {};
  const ai = d.repo?.ai_review;
  return (
    <div className="sheet pad stack" style={{ "--gap": "1rem" } as React.CSSProperties}>
      <div className="spread">
        <div>
          <h3>{p.name}</h3>
          <div className="row small" style={{ marginTop: ".3rem" }}>
            {p.repo_url && <a href={p.repo_url} target="_blank" rel="noreferrer">Repository <LuExternalLink /></a>}
            {p.live_url && <a href={p.live_url} target="_blank" rel="noreferrer">Live site <LuExternalLink /></a>}
            {d.repo?.languages && Object.keys(d.repo.languages).slice(0, 4).map((l: string) => <span className="tag" key={l}>{l}</span>)}
          </div>
        </div>
        <div className="row"><span className="score-mini num">{Math.round(review.score)}<span className="muted small"> / 100</span></span><Rerun sourceId={review.source_id} /></div>
      </div>
      {(shots.desktop || shots.mobile) && (
        <div className="shots">
          {shots.desktop && <figure style={{ flex: "1 1 360px", maxWidth: 520 }}><img src={fileUrl(shots.desktop)} alt={`${p.name} on desktop`} loading="lazy" /><figcaption>Desktop, as a recruiter sees it</figcaption></figure>}
          {shots.mobile && <figure style={{ width: 150 }}><img src={fileUrl(shots.mobile)} alt={`${p.name} on a phone`} loading="lazy" /><figcaption>Phone (390 px)</figcaption></figure>}
        </div>
      )}
      <ChecksList checks={review.checks} />
      {ai?.summary && <div className="notice info"><b>AI code review:</b> {ai.summary}</div>}
      {d.insights?.map((ins: Json, i: number) => <div className="notice" key={i}><b>{ins.title}.</b> {ins.text}</div>)}
    </div>
  );
}

function LinkedinSection({ review }: { review?: Json }) {
  if (!review) return <Empty title="No LinkedIn yet" action={<Link to="/profile#linkedin" className="btn">Add LinkedIn</Link>}>Upload the PDF export or paste your profile text — you'll get ready-to-paste rewrites.</Empty>;
  const rw = review.rewrites || {};
  return (
    <div className="stack" style={{ "--gap": "1.25rem" } as React.CSSProperties}>
      <p className="serif" style={{ fontSize: "var(--step-1)" }}>{review.summary}</p>
      <ChecksList checks={review.checks} />
      {rw.headline?.length > 0 && <div><h3 style={{ marginBottom: ".5rem" }}>Headline options</h3><div className="stack" style={{ "--gap": ".5rem" } as React.CSSProperties}>{rw.headline.map((h: string) => <CopyBlock key={h} text={h} />)}</div></div>}
      {rw.about && <div><h3 style={{ marginBottom: ".5rem" }}>About section draft</h3><CopyBlock text={rw.about} /></div>}
      {rw.skills_to_add?.length > 0 && <div><h3 style={{ marginBottom: ".5rem" }}>Skills to add (if you have them)</h3><div className="row">{rw.skills_to_add.map((s: string) => <span key={s} className="tag">{s}</span>)}</div></div>}
    </div>
  );
}

function SimpleSection({ review, empty, children }: { review?: Json; empty: React.ReactNode; children?: React.ReactNode }) {
  if (!review) return <>{empty}</>;
  return <div className="stack" style={{ "--gap": "1rem" } as React.CSSProperties}><p className="serif" style={{ fontSize: "var(--step-1)" }}>{review.summary}</p>{children}<ChecksList checks={review.checks} /></div>;
}

export default function Report() {
  const { data, error, loading, reload } = useLoad(() => api.get("/report"), []);
  useTaskDone(() => reload(), [reload]);
  useEffect(() => {
    if (data && location.hash) setTimeout(() => document.getElementById(location.hash.slice(1))?.scrollIntoView({ behavior: "smooth" }), 150);
  }, [data]);
  if (loading && !data) return <div className="page"><Loading label="Putting your report together…" /></div>;
  if (error) return <div className="page"><ErrorNote error={error} retry={reload} /></div>;
  const r = data.reviews;
  const resume = r.resume?.[0];
  const github = r.github?.[0];
  const coding = r.coding?.[0];
  const ach = r.achievements?.[0];
  const iv = data.interview;
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Placement review for {data.user.name}</h1>
          <p>{data.user.target_role ? `Target: ${data.user.target_role}. ` : ""}Generated {fmtDate(new Date().toISOString())}. Every score comes from the written MSOT benchmarks; nothing is guessed.</p>
        </div>
        <button className="btn secondary no-print" onClick={() => window.print()}><LuPrinter /> Print or save as PDF</button>
      </header>

      <div className="sheet pad">
        <div className="spread">
          <ScoreBlock score={data.readiness.score} level={data.readiness.level} />
          <nav aria-label="Report sections" className="row no-print small">
            {SECTIONS.map(([id, label]) => <a key={id} href={`#${id}`}>{label}</a>)}
          </nav>
        </div>
        {data.readiness.top_actions?.length > 0 && (
          <>
            <h3 style={{ margin: "1.25rem 0 .25rem" }}>Do these five things next</h3>
            <ol className="actions">
              {data.readiness.top_actions.map((a: Json, i: number) => (
                <li key={i}><div><b>{a.title}</b><div className="muted">{a.detail}</div></div><span className="gain">+{a.gain.toFixed(1)}</span></li>
              ))}
            </ol>
          </>
        )}
      </div>

      <section className="section"><SectionHead id="resume" title="Resume" review={resume} extra={<Rerun sourceId={resume?.source_id} />} /><ResumeSection review={resume} /></section>

      <section className="section">
        <SectionHead id="projects" title="Projects" />
        {r.project?.length ? <div className="stack" style={{ "--gap": "1.25rem" } as React.CSSProperties}>{r.project.map((p: Json) => <ProjectBlock key={p.id} review={p} />)}</div>
          : <Empty title="No projects reviewed yet" action={<Link to="/profile#projects" className="btn">Add a project</Link>}>Add each project's GitHub repo and live link. We clone the repo, scan for secrets, read the code and open the live site on desktop and mobile.</Empty>}
      </section>

      <section className="section">
        <SectionHead id="github" title="GitHub profile" review={github} extra={<Rerun sourceId={github?.source_id} />} />
        <SimpleSection review={github} empty={<Empty title="GitHub not connected" action={<Link to="/profile#github" className="btn">Add your username</Link>} />}>
          {github?.data?.extracted?.top_repos?.length > 0 && (
            <div className="row">{github.data.extracted.top_repos.slice(0, 6).map((t: Json) => <a key={t.name} className="tag" href={t.url} target="_blank" rel="noreferrer">{t.name}</a>)}</div>
          )}
        </SimpleSection>
      </section>

      <section className="section"><SectionHead id="linkedin" title="LinkedIn" review={r.linkedin?.[0]} extra={<Rerun sourceId={r.linkedin?.[0]?.source_id} />} /><LinkedinSection review={r.linkedin?.[0]} /></section>

      <section className="section">
        <SectionHead id="coding" title="Coding practice" review={coding} />
        <SimpleSection review={coding} empty={<Empty title="No coding profile" action={<Link to="/profile#coding" className="btn">Add LeetCode or Codeforces</Link>} />} />
      </section>

      <section className="section">
        <SectionHead id="achievements" title="Co-curricular achievements" review={ach} />
        <SimpleSection review={ach} empty={<Empty title="No achievements yet" action={<Link to="/profile#achievements" className="btn">Add achievements</Link>} />} />
      </section>

      <section className="section">
        <SectionHead id="interview" title="Mock interview" />
        {iv ? (
          <div className="sheet pad">
            <div className="spread"><span className="score-mini num">{Math.round(iv.score)}<span className="muted small"> / 100</span></span><Link to={`/interview/${iv.id}`}>Full feedback and transcript</Link></div>
            <table className="scheme" style={{ marginTop: ".75rem" }}><tbody>
              {(iv.result?.dimensions || []).map((d: Json) => <tr key={d.key}><td>{d.label}</td><td className="muted small">{d.reason}</td><td className="num">{d.score} / 5</td></tr>)}
            </tbody></table>
          </div>
        ) : <Empty title="No mock interview yet" action={<Link to="/interview" className="btn">Take a 15-minute interview</Link>}>Questions come from your own projects and target role.</Empty>}
      </section>
    </div>
  );
}
