import { useState } from "react";
import { api, fmtDate, Json, timeAgo } from "../../api";
import { Link } from "../../router";
import { ChecksList, Empty, ErrorNote, Loading, ScoreBlock, useLoad } from "../../ui";

function StudentReport({ id }: { id: number }) {
  const { data, error, loading, reload } = useLoad(() => api.get(`/admin/students/${id}/report`), [id]);
  if (loading && !data) return <div className="page"><Loading /></div>;
  if (error) return <div className="page"><Link to="/admin/students" className="small">All students</Link><div style={{ marginTop: "1rem" }}><ErrorNote error={error} retry={reload} /></div></div>;
  const r = data.reviews;
  return (
    <div className="page">
      <Link to="/admin/students" className="small">All students</Link>
      <header className="page-head" style={{ marginTop: ".4rem" }}>
        <div><h1>{data.user.name}</h1><p>{data.user.roll_no || data.user.email}, batch {data.user.batch_year} {data.user.branch}. Shared with the placement cell through an MSOT application. This view is logged.</p></div>
      </header>
      <ScoreBlock score={data.readiness.score} level={data.readiness.level} />
      {[["resume", "Resume"], ["github", "GitHub"], ["linkedin", "LinkedIn"], ["coding", "Coding practice"]].map(([k, label]) => r[k]?.[0] && (
        <section className="section" key={k}>
          <div className="spread"><h2>{label}</h2><span className="score-mini num">{Math.round(r[k][0].score)}</span></div>
          <ChecksList checks={r[k][0].checks} />
        </section>
      ))}
      {r.project?.map((p: Json) => (
        <section className="section" key={p.id}>
          <div className="spread"><h2>Project: {p.data?.project?.name}</h2><span className="score-mini num">{Math.round(p.score)}</span></div>
          <ChecksList checks={p.checks} />
        </section>
      ))}
      {data.interview && <section className="section"><h2>Mock interview</h2><p className="num" style={{ marginTop: ".4rem" }}>{Math.round(data.interview.score)} / 100 on {fmtDate(data.interview.ended_at)}</p></section>}
    </div>
  );
}

export default function AdminStudents({ id }: { id?: number }) {
  const [q, setQ] = useState("");
  const { data, error, loading, reload } = useLoad(() => api.get("/admin/students", { q }), [q]);
  if (id) return <StudentReport id={id} />;
  return (
    <div className="page">
      <header className="page-head">
        <div><h1>Students</h1><p>Readiness scores for the whole cohort. Full reports are visible only for students who shared them in an MSOT application.</p></div>
        <input className="input" style={{ maxWidth: 280 }} placeholder="Search name, email or roll no." value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search students" />
      </header>
      {loading && !data ? <Loading /> : error ? <ErrorNote error={error} retry={reload} /> : data.students.length === 0 ? <Empty title="No students found" /> : (
        <div className="table-wrap"><table className="data">
          <thead><tr><th>Student</th><th>Batch</th><th>Target role</th><th>Readiness</th><th>Last active</th><th>Report</th></tr></thead>
          <tbody>{data.students.map((s: Json) => (
            <tr key={s.id}>
              <td><b>{s.name}</b><div className="small muted">{s.roll_no || s.email}</div></td>
              <td>{s.batch_year} {s.branch}</td>
              <td>{s.target_role || <span className="muted">—</span>}</td>
              <td><span className="num">{s.readiness != null ? Math.round(s.readiness) : "—"}</span> <span className="small muted">{s.level}</span></td>
              <td className="small">{timeAgo(s.last_seen_at || s.created_at)}</td>
              <td>{s.report_shared ? <Link to={`/admin/students/${s.id}`}>View</Link> : <span className="small muted">Private</span>}</td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
    </div>
  );
}
