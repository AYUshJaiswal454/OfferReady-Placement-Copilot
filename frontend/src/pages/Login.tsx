import { FormEvent, useState } from "react";
import { api } from "../api";
import { Logo } from "../App";
import { navigate } from "../router";
import { useAuth } from "../state";
import { Segmented } from "../ui";

export default function Login() {
  const { setUser } = useAuth();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [form, setForm] = useState({ name: "", email: "", password: "", roll_no: "", batch_year: "2026", branch: "CSE" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k: string) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = mode === "login"
        ? await api.post("/auth/login", { email: form.email, password: form.password })
        : await api.post("/auth/signup", { ...form, batch_year: Number(form.batch_year) || null, roll_no: form.roll_no || null });
      setUser(res.user);
      navigate(res.user.role === "admin" ? "/admin" : "/", true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth">
      <section className="auth-side">
        <div className="row" style={{ gap: ".6rem" }}>
          <span style={{ width: 34, height: 34, display: "inline-block" }}><Logo /></span>
          <b className="serif" style={{ fontSize: "1.4rem" }}>OfferReady</b>
        </div>
        <div>
          <h1>Know you're <span className="marked">ready</span> before the interviewer does.</h1>
          <p>Upload your resume, LinkedIn and GitHub. Get every problem marked, with the exact fix — then practise, apply and track in one place.</p>
          <div className="sample" aria-hidden>
            <span className="strike">Worked on a website using React.</span>
            <span className="fix">Start with what you built and the result: "Built a React storefront used by 300 students, cutting checkout time by 40%."</span>
          </div>
        </div>
        <p className="small" style={{ fontSize: "1rem", color: "#98A3B3" }}>For students and the placement cell of MSOT.</p>
      </section>
      <main className="auth-main">
        <h2 style={{ fontSize: "var(--step-3)" }}>{mode === "login" ? "Sign in" : "Create your account"}</h2>
        <div style={{ margin: "1.25rem 0" }}>
          <Segmented label="Sign in or sign up" value={mode} onChange={(v) => { setMode(v); setError(""); }}
            options={[{ value: "login", label: "Sign in" }, { value: "signup", label: "New student" }]} />
        </div>
        <form onSubmit={submit} className="stack" style={{ "--gap": "1rem" } as React.CSSProperties}>
          {mode === "signup" && (
            <div className="field"><label htmlFor="name">Full name</label>
              <input id="name" className="input" value={form.name} onChange={set("name")} required minLength={2} autoComplete="name" /></div>
          )}
          <div className="field"><label htmlFor="email">Email</label>
            <input id="email" className="input" type="email" value={form.email} onChange={set("email")} required autoComplete="email" /></div>
          <div className="field"><label htmlFor="password">Password</label>
            <input id="password" className="input" type="password" value={form.password} onChange={set("password")} required minLength={mode === "signup" ? 8 : 1}
              autoComplete={mode === "login" ? "current-password" : "new-password"} />
            {mode === "signup" && <span className="hint">At least 8 characters.</span>}</div>
          {mode === "signup" && (
            <div className="grid-2" style={{ gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: ".75rem" }}>
              <div className="field"><label htmlFor="roll">Roll no.</label><input id="roll" className="input" value={form.roll_no} onChange={set("roll_no")} /></div>
              <div className="field"><label htmlFor="batch">Batch</label>
                <select id="batch" className="select" value={form.batch_year} onChange={set("batch_year")}>
                  {[2025, 2026, 2027, 2028, 2029].map((y) => <option key={y}>{y}</option>)}
                </select></div>
              <div className="field"><label htmlFor="branch">Branch</label>
                <select id="branch" className="select" value={form.branch} onChange={set("branch")}>
                  {["CSE", "IT", "ECE", "EEE", "ME", "CE", "AI&DS", "MCA", "Other"].map((b) => <option key={b}>{b}</option>)}
                </select></div>
            </div>
          )}
          {error && <p className="error-text" role="alert">{error}</p>}
          <button className="btn" type="submit" disabled={busy} style={{ width: "100%" }}>{busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}</button>
        </form>
        <div className="notice info small" style={{ marginTop: "1.5rem" }}>
          <div>Demo student: <b>demo@student.msot.edu</b>, password demo12345</div>
          <div>Demo placement cell: <b>admin@msot.edu</b>, password admin12345</div>
        </div>
      </main>
    </div>
  );
}
