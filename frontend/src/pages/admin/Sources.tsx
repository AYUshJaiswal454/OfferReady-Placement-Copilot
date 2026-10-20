import { LuRefreshCw } from "react-icons/lu";
import { api, Json, timeAgo } from "../../api";
import { useToast } from "../../state";
import { ErrorNote, Loading, useLoad } from "../../ui";

export default function AdminSources() {
  const { data, error, loading, reload } = useLoad(() => api.get("/admin/sources"), []);
  const toast = useToast();
  async function refresh(source?: string) {
    await api.post("/admin/sources/refresh", source ? { source } : {});
    toast.push({ text: `Refreshing ${source || "all sources"} in the background.` });
    setTimeout(reload, 4000);
  }
  if (loading && !data) return <div className="page"><Loading /></div>;
  if (error) return <div className="page"><ErrorNote error={error} retry={reload} /></div>;
  return (
    <div className="page">
      <header className="page-head">
        <div><h1>Job sources</h1><p>{data.policy}</p></div>
        <button className="btn" onClick={() => refresh()}><LuRefreshCw /> Refresh all</button>
      </header>
      {data.offline_mode && <div className="notice info" style={{ marginBottom: "1rem" }}>Offline mode is on (<code>OFFLINE_MODE=true</code>): external sources are paused and only the sample jobs and the MSOT board are used. Turn it off in <code>.env</code> to collect live jobs.</div>}
      <div className="table-wrap"><table className="data">
        <thead><tr><th>Source</th><th>Kind</th><th>Terms we follow</th><th>Active jobs</th><th>Last run</th><th /></tr></thead>
        <tbody>{data.sources.map((s: Json) => (
          <tr key={s.name}>
            <td><b>{s.label}</b><div className="small">{!s.enabled ? <span className="tag">Disabled</span>
              : s.needs_key && !s.configured ? <span className="tag warn">Needs API key</span> : <span className="tag ok">Enabled</span>}</div></td>
            <td className="small">{s.kind}</td>
            <td className="small" style={{ maxWidth: 380 }}>{s.terms}</td>
            <td className="num">{s.active_jobs}</td>
            <td className="small">{s.health?.last_run_at ? timeAgo(s.health.last_run_at) : data.offline_mode && s.name !== "demo" ? "paused" : "never"}{s.health?.last_error && <div className={s.health.last_error.startsWith("Skipped") ? "muted" : "error-text"}>{s.health.last_error}</div>}</td>
            <td>{s.enabled && (!s.needs_key || s.configured) && <button className="btn small secondary" onClick={() => refresh(s.name)}>Run</button>}</td>
          </tr>
        ))}</tbody>
      </table></div>
      <p className="muted small" style={{ marginTop: "1rem" }}>Not collected automatically (terms prohibit it): {data.not_scraped.join(", ")}. Students get search links for these sites instead and can add jobs they find manually.</p>
    </div>
  );
}
