import { useState } from "react";
import { api } from "../api";
import { useAuth } from "../state";

export default function Consent() {
  const { user, setUser, logout } = useAuth();
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  return (
    <div className="page" style={{ maxWidth: 760, margin: "0 auto", paddingTop: "3rem" }}>
      <h1>Before we start, {user?.name?.split(" ")[0]}</h1>
      <p className="muted" style={{ marginTop: ".5rem", fontSize: "var(--step-1)" }}>Here is exactly what OfferReady does with your data.</p>
      <div className="sheet pad stack" style={{ marginTop: "1.5rem", "--gap": "1rem" } as React.CSSProperties}>
        <div>
          <h3>What we read</h3>
          <p>Only what you give us: your resume and LinkedIn PDF (or pasted text), your public GitHub, LeetCode or Codeforces username,
            project links, and your mock-interview answers. We never log in to any site as you and never scrape LinkedIn.</p>
        </div>
        <div>
          <h3>Why</h3>
          <p>To review your profile against the MSOT placement benchmarks, compute your readiness score, run mock interviews and match you to jobs.</p>
        </div>
        <div>
          <h3>Where it is kept</h3>
          <p>Uploaded files are encrypted at rest on the MSOT server. AI features send the relevant text to the AI provider chosen
            in Settings (OpenAI, or a local Ollama model that keeps everything on the server).</p>
        </div>
        <div>
          <h3>Who can see it</h3>
          <p>Only you. The placement cell sees your readiness score in cohort statistics, and your full report only when you apply
            to an MSOT job and choose to share it.</p>
        </div>
        <div>
          <h3>Your control</h3>
          <p>You can see, edit, download or delete everything from My profile and Settings at any time. Deleting removes it permanently.</p>
        </div>
        <label className="check">
          <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
          <span>I agree that OfferReady may process the data I provide for these purposes.</span>
        </label>
        <div className="row">
          <button className="btn" disabled={!checked || busy} onClick={async () => {
            setBusy(true);
            const res = await api.post("/me/consent", { accept: true });
            setUser(res.user);
          }}>Agree and continue</button>
          <button className="btn ghost" onClick={logout}>Not now</button>
        </div>
      </div>
    </div>
  );
}
