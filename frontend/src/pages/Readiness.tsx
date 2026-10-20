import { api, fmtDate, Json } from "../api";
import { Link } from "../router";
import { useTaskDone } from "../state";
import { Bar, ErrorNote, LineChart, Loading, ScoreBlock, useLoad } from "../ui";

const TARGETS: Record<string, string> = {
  resume: "/report#resume", projects: "/report#projects", interview: "/interview", github: "/report#github",
  coding: "/report#coding", linkedin: "/report#linkedin", achievements: "/report#achievements",
};
const EFFORT: Record<string, string> = { quick: "Quick fix", medium: "An hour or two", long: "A few days" };
const ORDER = ["resume", "projects", "interview", "github", "coding", "linkedin", "achievements"];

export default function Readiness() {
  const { data, error, loading, reload } = useLoad(() => api.get("/readiness"), []);
  useTaskDone(() => reload(), [reload]);
  if (loading && !data) return <div className="page"><Loading /></div>;
  if (error) return <div className="page"><ErrorNote error={error} retry={reload} /></div>;
  const comps = data.components;
  const history = (data.history || []).map((h: Json) => ({ x: fmtDate(h.created_at), y: h.score }));
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Placement readiness</h1>
          <p>One score out of 100 from seven parts of your profile, weighted the way MSOT recruiters weigh them. It updates every time you fix something.</p>
        </div>
      </header>
      <div className="two-col">
        <div className="stack" style={{ "--gap": "2rem" } as React.CSSProperties}>
          <div>
            <ScoreBlock score={data.score} level={data.level}
              sub={data.potential > data.score ? `${Math.round(data.potential)} if you finish the five actions below` : undefined} />
            <div className="bands" aria-label="Score levels">
              <span className={data.score < 50 ? "on" : ""}><b>0–49</b> Not ready</span>
              <span className={data.score >= 50 && data.score < 75 ? "on" : ""}><b>50–74</b> Almost ready</span>
              <span className={data.score >= 75 ? "on" : ""}><b>75–100</b> Placement ready</span>
            </div>
            <p className="muted small" style={{ marginTop: ".5rem" }}>Profile {Math.round(data.completeness * 100)}% complete.</p>
          </div>

          <section>
            <h2 style={{ marginBottom: ".5rem" }}>Raise it most with these five</h2>
            <p className="muted small" style={{ marginBottom: ".5rem" }}>Gains are computed exactly from the formula; quick fixes are ranked ahead of long ones with similar gain.</p>
            <ol className="actions">
              {data.top_actions.map((a: Json, i: number) => (
                <li key={i}>
                  <div>
                    <b>{a.title}</b> <span className="tag" style={{ marginLeft: ".3rem" }}>{a.component_label}</span>
                    <div className="muted" style={{ marginTop: ".2rem" }}>{a.detail}</div>
                    {a.also_fixes?.length > 0 && <div className="small muted" style={{ marginTop: ".2rem" }}>Also clears: {a.also_fixes.join(", ")}.</div>}
                    <div className="small" style={{ marginTop: ".3rem" }}>
                      <Link to={a.check_id === "MISSING" ? (a.target === "interview" ? "/interview" : `/profile#${a.target}`) : TARGETS[a.component]}>
                        {a.check_id === "MISSING" ? "Add it" : "See the details"}</Link>
                      <span className="muted" style={{ marginLeft: ".6rem" }}>{EFFORT[a.effort] || a.effort}</span>
                    </div>
                  </div>
                  <span className="gain">+{a.gain.toFixed(1)}</span>
                </li>
              ))}
            </ol>
          </section>

          <section>
            <h2 style={{ marginBottom: ".75rem" }}>How the score is made</h2>
            <table className="scheme">
              <thead><tr><th>Part</th><th className="num">Weight</th><th style={{ width: "35%" }}>Score</th><th className="num">Points</th></tr></thead>
              <tbody>
                {ORDER.map((k) => {
                  const c = comps[k];
                  return (
                    <tr key={k}>
                      <td><Link to={TARGETS[k]}>{c.label}</Link>{c.count ? <span className="muted small"> ({c.count} projects)</span> : null}</td>
                      <td className="num">{c.weight}%</td>
                      <td><div className="row" style={{ flexWrap: "nowrap" }}><Bar value={c.score} missing={c.score == null} /><span className="num small" style={{ minWidth: "2.5rem" }}>{c.score == null ? "—" : Math.round(c.score)}</span></div></td>
                      <td className="num"><b>{c.points.toFixed(1)}</b> <span className="muted">/ {c.weight}</span></td>
                    </tr>
                  );
                })}
                <tr><td><b>Total</b></td><td className="num">100%</td><td /><td className="num"><b>{data.score.toFixed(1)}</b> <span className="muted">/ 100</span></td></tr>
              </tbody>
            </table>
            <p className="muted small" style={{ marginTop: ".6rem" }}>Projects = average of your best three project reviews (at least two expected). Formula {data.formula_version}.</p>
          </section>
        </div>
        <aside className="stack" style={{ "--gap": "1rem" } as React.CSSProperties}>
          <div className="sheet pad">
            <b>Progress over time</b>
            {history.length > 1 ? <div style={{ marginTop: ".75rem" }}><LineChart points={history} /></div>
              : <p className="muted small" style={{ marginTop: ".5rem" }}>Your score history appears here as you fix things and re-run reviews.</p>}
          </div>
          {history.length > 1 && (
            <div className="sheet pad small">
              <b>Changes</b>
              <ul className="list" style={{ marginTop: ".4rem" }}>
                {data.history.slice(-6).reverse().map((h: Json, i: number, arr: Json[]) => {
                  const prev = arr[i + 1];
                  const delta = prev ? h.score - prev.score : 0;
                  return <li key={i} style={{ padding: ".4rem 0" }} className="spread"><span>{fmtDate(h.created_at, true)}</span>
                    <span className="num">{Math.round(h.score)}{prev && delta !== 0 && <span style={{ color: delta > 0 ? "var(--tick)" : "var(--red)", marginLeft: ".35rem" }}>{delta > 0 ? "+" : ""}{delta.toFixed(1)}</span>}</span></li>;
                })}
              </ul>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
