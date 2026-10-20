import { useEffect, useState } from "react";
import { LuDownload, LuTrash2 } from "react-icons/lu";
import { api, Json } from "../api";
import { navigate } from "../router";
import { useAuth, useToast } from "../state";
import { ErrorNote, Loading, Modal, useLoad } from "../ui";

export default function Settings() {
  const { data, error, loading, reload } = useLoad(() => api.get("/settings"), []);
  const { setUser } = useAuth();
  const toast = useToast();
  const [f, setF] = useState<Json>({});
  const [test, setTest] = useState<Json | null>(null);
  const [testing, setTesting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [typed, setTyped] = useState("");

  useEffect(() => {
    if (!data) return;
    const p = data.preferences;
    setF({ llm_provider: p.llm_provider || "default", openai_api_key: p.openai_api_key ? "set" : "", openai_model: p.openai_model || "",
      openai_model_smart: p.openai_model_smart || "", ollama_base_url: p.ollama_base_url || "", ollama_model: p.ollama_model || "",
      stt: p.stt || data.server_defaults.stt, tts: p.tts || data.server_defaults.tts, email_reminders: p.email_reminders ?? true });
  }, [data]);

  if (loading && !data) return <div className="page"><Loading /></div>;
  if (error) return <div className="page"><ErrorNote error={error} retry={reload} /></div>;
  const d = data.server_defaults;
  const set = (k: string) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  async function save() {
    try {
      const body = { ...f };
      if (body.openai_api_key === "set") delete body.openai_api_key;
      const res = await api.put("/settings", body);
      setUser(res.user);
      toast.push({ text: "Settings saved." });
      setTest(null);
      reload();
    } catch (e) { toast.push({ kind: "error", text: (e as Error).message }); }
  }

  const providers = [
    { value: "default", label: "College default", hint: `Uses the server's setting (${d.provider === "mock" ? "offline mode" : d.provider}).` },
    { value: "openai", label: "OpenAI", hint: d.server_has_openai_key ? "The college key is used unless you add your own." : "Add your own API key below." },
    { value: "ollama", label: "Local model (Ollama)", hint: "Runs on the college server or your laptop — nothing leaves the machine. Slower, slightly lower quality." },
    { value: "mock", label: "Offline (no AI)", hint: "Reviews and scores still work — they are rule-based. Rewrites use templates and the chat answers only common questions." },
  ];
  return (
    <div className="page" style={{ maxWidth: 820 }}>
      <header className="page-head"><div><h1>Settings</h1><p>Choose which AI writes your rewrites, runs interviews and answers chat. Scores never depend on it — they come from the written benchmarks.</p></div></header>

      <section className="sheet pad stack" style={{ "--gap": "1.1rem" } as React.CSSProperties}>
        <h2>AI provider</h2>
        <p className="small muted">Currently using: <b>{data.effective.provider === "mock" ? "offline mode" : `${data.effective.provider} (${data.effective.model})`}</b></p>
        <fieldset style={{ border: 0, padding: 0, margin: 0 }} className="stack">
          <legend className="sr-only">AI provider</legend>
          {providers.map((p) => (
            <label key={p.value} className="check">
              <input type="radio" name="provider" checked={f.llm_provider === p.value} onChange={() => setF({ ...f, llm_provider: p.value })} />
              <span><b>{p.label}</b><span className="small muted" style={{ display: "block" }}>{p.hint}</span></span>
            </label>
          ))}
        </fieldset>
        {f.llm_provider === "openai" && (
          <div className="grid-2">
            <div className="field"><label htmlFor="key">Your OpenAI API key (optional)</label>
              <input id="key" className="input" type="password" autoComplete="off" placeholder={f.openai_api_key === "set" ? "Saved (hidden)" : "sk-…"}
                value={f.openai_api_key === "set" ? "" : f.openai_api_key} onChange={set("openai_api_key")} />
              <span className="hint">Stored encrypted. Leave empty to use the college key.</span></div>
            <div className="field"><label htmlFor="om">Model</label><input id="om" className="input" placeholder={d.openai_model} value={f.openai_model} onChange={set("openai_model")} />
              <span className="hint">Scoring/code review model: {f.openai_model_smart || d.openai_model_smart}</span></div>
          </div>
        )}
        {f.llm_provider === "ollama" && (
          <div className="grid-2">
            <div className="field"><label htmlFor="ou">Ollama URL</label><input id="ou" className="input" placeholder={d.ollama_base_url} value={f.ollama_base_url} onChange={set("ollama_base_url")} /></div>
            <div className="field"><label htmlFor="omod">Model</label><input id="omod" className="input" placeholder={d.ollama_model} value={f.ollama_model} onChange={set("ollama_model")} />
              <span className="hint">e.g. qwen2.5:7b-instruct or llama3.1:8b (run <code>ollama pull</code> first)</span></div>
          </div>
        )}
        <div className="row">
          <button className="btn" onClick={save}>Save</button>
          <button className="btn secondary" disabled={testing} onClick={async () => {
            setTesting(true);
            try { setTest(await api.post("/settings/test")); } catch (e) { setTest({ ok: false, message: (e as Error).message }); } finally { setTesting(false); }
          }}>{testing ? "Testing…" : "Test connection"}</button>
          {test && <span className={test.ok ? "tag ok" : "tag bad"}>{test.ok ? `Working: ${test.provider}${test.model ? ` (${test.model})` : ""}` : `Failed: ${test.message}`}</span>}
        </div>
      </section>

      <section className="sheet pad stack section" style={{ "--gap": "1rem" } as React.CSSProperties}>
        <h2>Voice interviews</h2>
        <div className="grid-2">
          <div className="field"><label htmlFor="stt">Speech to text</label>
            <select id="stt" className="select" value={f.stt} onChange={set("stt")}>
              <option value="browser">Browser (free; Chrome/Edge)</option>
              <option value="openai">OpenAI transcription</option>
              <option value="whisper">Local Whisper server</option>
            </select>
            <span className="hint">{f.stt === "browser" ? "Chrome and Edge send your audio to their own speech service. Choose Local Whisper or answer by typing to keep everything on MSOT servers."
              : f.stt === "openai" ? "Audio is sent to OpenAI for transcription." : "Audio stays on the server running Whisper."}</span></div>
          <div className="field"><label htmlFor="tts">Interviewer voice</label>
            <select id="tts" className="select" value={f.tts} onChange={set("tts")}>
              <option value="browser">Browser voice (free)</option>
              <option value="openai">OpenAI voice</option>
            </select></div>
        </div>
        <label className="check"><input type="checkbox" checked={!!f.email_reminders} onChange={(e) => setF({ ...f, email_reminders: e.target.checked })} /> Email me follow-up and interview reminders</label>
        <div><button className="btn" onClick={save}>Save</button></div>
      </section>

      <section className="section stack" style={{ "--gap": "1rem" } as React.CSSProperties}>
        <h2>Your data</h2>
        <p className="muted">Download everything we store about you (files decrypted, reviews, interviews, applications), or delete it all permanently.</p>
        <div className="row">
          <a className="btn secondary" href="/api/me/export"><LuDownload /> Download my data</a>
          <button className="btn danger" onClick={() => setConfirmDelete(true)}><LuTrash2 /> Delete my account and data</button>
        </div>
      </section>

      {confirmDelete && (
        <Modal title="Delete everything?" onClose={() => setConfirmDelete(false)} footer={<>
          <button className="btn ghost" onClick={() => setConfirmDelete(false)}>Cancel</button>
          <button className="btn danger" disabled={typed !== "DELETE"} onClick={async () => {
            await api.del("/me", { confirm: "DELETE" });
            setUser(null);
            navigate("/login", true);
          }}>Delete permanently</button></>}>
          <p>This removes your resume, LinkedIn, reviews, interviews, applications and account. It cannot be undone.</p>
          <div className="field" style={{ marginTop: "1rem" }}><label htmlFor="typed">Type DELETE to confirm</label>
            <input id="typed" className="input" value={typed} onChange={(e) => setTyped(e.target.value)} /></div>
        </Modal>
      )}
    </div>
  );
}
