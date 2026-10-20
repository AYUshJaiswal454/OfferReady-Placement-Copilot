import { api, Json } from "../../api";
import { Link } from "../../router";
import { Bar, ErrorNote, Histogram, Loading, useLoad } from "../../ui";

const INR = 84;

export default function AdminOverview() {
  const { data, error, loading, reload } = useLoad(() => api.get("/admin/overview"), []);
  if (loading && !data) return <div className="page"><Loading /></div>;
  if (error) return <div className="page"><ErrorNote error={error} retry={reload} /></div>;
  const lv = data.levels || {};
  const funnelOrder = ["saved", "applied", "shortlisted", "interview", "offer", "rejected"];
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Cohort readiness</h1>
          <p>{data.students} students registered, {data.with_score} with a readiness score. Use the common gaps to plan workshops.</p>
        </div>
        <Link to="/admin/jobs" className="btn">Post a job</Link>
      </header>

      <div className="grid-2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
        <div className="sheet pad"><div className="muted small">Average score</div><div className="score-mini num">{data.average ?? "—"}</div><div className="small muted">median {data.median ?? "—"}</div></div>
        <div className="sheet pad"><div className="muted small">Placement ready (75+)</div><div className="score-mini num" style={{ color: "var(--tick)" }}>{lv["Placement ready"] || 0}</div></div>
        <div className="sheet pad"><div className="muted small">Almost ready (50–74)</div><div className="score-mini num" style={{ color: "var(--amber)" }}>{lv["Almost ready"] || 0}</div></div>
        <div className="sheet pad"><div className="muted small">Not ready (under 50)</div><div className="score-mini num" style={{ color: "var(--red)" }}>{lv["Not ready"] || 0}</div><div className="small muted">{lv["No data"] || 0} haven't started</div></div>
      </div>

      <div className="two-col section">
        <section>
          <h2 style={{ marginBottom: ".75rem" }}>Most common gaps</h2>
          {data.common_gaps.length === 0 ? <p className="muted">Gaps appear once students upload resumes.</p> : (
            <table className="scheme">
              <thead><tr><th>Benchmark check that fails</th><th style={{ width: "30%" }}>Share of students</th><th className="num">Students</th></tr></thead>
              <tbody>{data.common_gaps.map((g: Json) => (
                <tr key={g.key}><td>{g.title}</td><td><Bar value={g.share * 100} /></td><td className="num">{g.students} <span className="muted">({Math.round(g.share * 100)}%)</span></td></tr>
              ))}</tbody>
            </table>
          )}
          <h2 style={{ margin: "2rem 0 .75rem" }}>Average by component</h2>
          <table className="scheme"><tbody>
            {Object.entries(data.components as Record<string, Json>).map(([k, c]) => (
              <tr key={k}><td>{c.label}</td><td style={{ width: "40%" }}><Bar value={c.average} missing={c.average == null} /></td><td className="num">{c.average ?? "—"} <span className="muted small">n={c.n}</span></td></tr>
            ))}
          </tbody></table>
        </section>
        <aside className="stack" style={{ "--gap": "1.25rem" } as React.CSSProperties}>
          <div className="sheet pad">
            <b>Score distribution</b>
            <Histogram bins={data.distribution.map((b: Json) => ({ label: b.bucket, count: b.count, hot: Number(b.bucket.split("–")[0]) >= 75 }))} />
          </div>
          <div className="sheet pad">
            <b>Applications</b>
            <table className="scheme small" style={{ marginTop: ".5rem" }}><tbody>
              {funnelOrder.map((s) => <tr key={s}><td style={{ textTransform: "capitalize" }}>{s}</td><td className="num">{data.funnel[s] || 0}</td></tr>)}
            </tbody></table>
          </div>
          <div className="sheet pad small">
            <b>{data.usage.projected ? "Projected AI cost" : "AI cost so far"}</b>
            <p style={{ marginTop: ".4rem" }}>Total ₹{(data.usage.total_cost_usd * INR).toFixed(2)} (${data.usage.total_cost_usd.toFixed(4)}) across {data.usage.students} students, about <b>₹{(data.usage.cost_per_student_usd * INR).toFixed(2)} per student</b>.</p>
            {data.usage.projected && <p className="muted" style={{ marginTop: ".3rem" }}>Running in offline mode, so nothing was spent. This is what the same calls would cost on the configured OpenAI model.</p>}
            <details style={{ marginTop: ".5rem" }}><summary>By feature</summary>
              <table className="data" style={{ marginTop: ".4rem" }}><thead><tr><th>Feature</th><th>Calls</th><th>₹</th></tr></thead><tbody>
                {data.usage.by_feature.map((f: Json, i: number) => <tr key={i}><td>{f.feature} <span className="muted">({f.provider})</span></td><td>{f.calls}</td><td>{(f.cost * INR).toFixed(3)}</td></tr>)}
              </tbody></table>
            </details>
          </div>
        </aside>
      </div>
    </div>
  );
}
