import { ReactNode, useEffect, useRef, useState } from "react";
import {
  LuBell, LuBriefcase, LuClipboardCheck, LuFileText, LuKanban, LuLayoutDashboard, LuLogOut, LuMessageSquare,
  LuMic, LuMoon, LuRadar, LuSettings, LuSun, LuUser, LuUsers,
} from "react-icons/lu";
import { api, timeAgo } from "./api";
import { Link, match, navigate, usePath } from "./router";
import { useAuth } from "./state";
import { useLoad } from "./ui";
import Login from "./pages/Login";
import Consent from "./pages/Consent";
import Copilot from "./pages/Copilot";
import Report from "./pages/Report";
import Readiness from "./pages/Readiness";
import Interview from "./pages/Interview";
import Jobs from "./pages/Jobs";
import Tracker from "./pages/Tracker";
import Profile from "./pages/Profile";
import Settings from "./pages/Settings";
import AdminOverview from "./pages/admin/Overview";
import AdminJobs from "./pages/admin/JobsAdmin";
import AdminStudents from "./pages/admin/Students";
import AdminSources from "./pages/admin/Sources";

export function Logo() {
  return (
    <svg viewBox="0 0 64 64" aria-hidden>
      <rect width="64" height="64" rx="14" fill="#14213D" />
      <rect x="12" y="36" width="40" height="10" rx="2" fill="#FFE14D" />
      <path d="M18 30l9 9 19-21" fill="none" stroke="#F3F5F1" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

const STUDENT_NAV = [
  { to: "/", label: "Copilot", icon: LuMessageSquare },
  { to: "/report", label: "Review report", icon: LuFileText },
  { to: "/readiness", label: "Readiness", icon: LuClipboardCheck },
  { to: "/interview", label: "Mock interview", icon: LuMic },
  { to: "/jobs", label: "Jobs", icon: LuBriefcase },
  { to: "/tracker", label: "Applications", icon: LuKanban },
  { to: "/profile", label: "My profile", icon: LuUser },
];
const ADMIN_NAV = [
  { to: "/admin", label: "Cohort overview", icon: LuLayoutDashboard },
  { to: "/admin/jobs", label: "MSOT job board", icon: LuBriefcase },
  { to: "/admin/students", label: "Students", icon: LuUsers },
  { to: "/admin/sources", label: "Job sources", icon: LuRadar },
];

function useTheme(): [string, () => void] {
  const [theme, setTheme] = useState<string>(() => {
    try { return localStorage.getItem("or-theme") || ""; } catch { return ""; }
  });
  useEffect(() => {
    if (theme) document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
  }, [theme]);
  const toggle = () => {
    const dark = theme ? theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    const next = dark ? "light" : "dark";
    setTheme(next);
    try { localStorage.setItem("or-theme", next); } catch { /* storage unavailable */ }
  };
  return [theme, toggle];
}

function Notifications() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const { data, reload } = useLoad(() => api.get("/notifications"), []);
  useEffect(() => {
    const iv = setInterval(reload, 30000);
    const onDoc = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    return () => { clearInterval(iv); document.removeEventListener("mousedown", onDoc); };
  }, [reload]);
  const unread = data?.unread || 0;
  return (
    <div style={{ position: "relative" }} ref={ref}>
      <button className="icon-btn" aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`} aria-expanded={open}
        onClick={async () => {
          setOpen(!open);
          if (!open && unread) { await api.post("/notifications/read", {}); setTimeout(reload, 4000); }
        }}>
        <LuBell />
        {unread > 0 && <span className="badge-dot">{unread > 9 ? "9+" : unread}</span>}
      </button>
      {open && (
        <div className="popover">
          {(data?.notifications || []).length === 0 ? (
            <p className="muted" style={{ padding: "1rem" }}>No notifications yet. Follow-up reminders and placement-cell updates appear here.</p>
          ) : (
            <ul className="list">
              {data.notifications.map((n: any) => (
                <li key={n.id} className={n.read_at ? "" : "unread"}>
                  <a href={n.link || "#"} onClick={(e) => { e.preventDefault(); setOpen(false); n.link && navigate(n.link); }} style={{ textDecoration: "none" }}>
                    <b>{n.title}</b>
                    {n.body && <div className="small muted">{n.body}</div>}
                    <div className="small muted">{timeAgo(n.created_at)}</div>
                  </a>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function Shell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const [theme, toggleTheme] = useTheme();
  const admin = user?.role === "admin";
  const nav = admin ? ADMIN_NAV : STUDENT_NAV;
  const initials = (user?.name || "?").split(" ").map((p: string) => p[0]).slice(0, 2).join("");
  const dark = theme ? theme === "dark" : typeof matchMedia !== "undefined" && matchMedia("(prefers-color-scheme: dark)").matches;
  return (
    <div className="shell">
      <a href="#main" className="sr-only">Skip to content</a>
      <nav className="rail" aria-label="Main">
        <Link to={admin ? "/admin" : "/"} className="brand" aria-current={undefined}><Logo /><b>OfferReady</b></Link>
        {admin && <div className="nav-group">MSOT placement cell</div>}
        {nav.map((n) => (
          <Link key={n.to} to={n.to} className="nav-link"><n.icon />{n.label}</Link>
        ))}
        {!admin && <Link to="/settings" className="nav-link" style={{ marginTop: ".5rem" }}><LuSettings />Settings</Link>}
        <div className="rail-foot">
          <div className="who">
            <span className="avatar">{initials}</span>
            <div className="who-text">
              <div><b>{user?.name}</b></div>
              <div className="small muted">{admin ? "Placement admin" : user?.target_role || user?.email}</div>
            </div>
          </div>
          <div className="row" style={{ gap: ".25rem" }}>
            <button className="btn ghost small" onClick={toggleTheme} aria-label="Toggle dark mode">{dark ? <LuSun /> : <LuMoon />}{dark ? "Light" : "Dark"}</button>
            <button className="btn ghost small" onClick={logout}><LuLogOut />Sign out</button>
          </div>
        </div>
      </nav>
      <div className="main">
        <header className="topbar">
          <Link to={admin ? "/admin" : "/"} className="brand mobile-brand" aria-current={undefined} style={{ padding: 0 }}><Logo /><b>OfferReady</b></Link>
          <div className="row" style={{ gap: ".25rem" }}>
            {!admin && <Notifications />}
            <button className="icon-btn" onClick={toggleTheme} aria-label="Toggle dark mode">{dark ? <LuSun /> : <LuMoon />}</button>
            <Link to={admin ? "/admin" : "/settings"} className="icon-btn" aria-label="Settings" aria-current={undefined}><LuSettings /></Link>
          </div>
        </header>
        <main id="main">{children}</main>
      </div>
      <nav className="mobile-nav" aria-label="Main">
        {(admin ? ADMIN_NAV : [STUDENT_NAV[0], STUDENT_NAV[1], STUDENT_NAV[3], STUDENT_NAV[4], STUDENT_NAV[5]]).map((n) => (
          <Link key={n.to} to={n.to}><n.icon />{n.label.split(" ")[0]}</Link>
        ))}
      </nav>
    </div>
  );
}

const STUDENT_ROUTES: [string, (p: Record<string, string>) => ReactNode][] = [
  ["/", () => <Copilot />],
  ["/report", () => <Report />],
  ["/readiness", () => <Readiness />],
  ["/interview", () => <Interview />],
  ["/interview/:id", (p) => <Interview id={Number(p.id)} />],
  ["/jobs", () => <Jobs />],
  ["/tracker", () => <Tracker />],
  ["/profile", () => <Profile />],
  ["/settings", () => <Settings />],
];
const ADMIN_ROUTES: [string, (p: Record<string, string>) => ReactNode][] = [
  ["/admin", () => <AdminOverview />],
  ["/admin/jobs", () => <AdminJobs />],
  ["/admin/jobs/:id", (p) => <AdminJobs id={Number(p.id)} />],
  ["/admin/students", () => <AdminStudents />],
  ["/admin/students/:id", (p) => <AdminStudents id={Number(p.id)} />],
  ["/admin/sources", () => <AdminSources />],
];

export default function App() {
  const { user, loading } = useAuth();
  const path = usePath();

  useEffect(() => {
    if (loading) return;
    if (!user && path !== "/login") navigate("/login", true);
    else if (user && path === "/login") navigate(user.role === "admin" ? "/admin" : "/", true);
    else if (user?.role === "admin" && !path.startsWith("/admin")) navigate("/admin", true);
    else if (user?.role === "student" && path.startsWith("/admin")) navigate("/", true);
  }, [user, loading, path]);

  if (loading) return <div className="page"><p className="muted" style={{ padding: "3rem 0" }}>Loading…</p></div>;
  if (!user) return <Login />;
  if (user.role === "student" && !user.consent_at) return <Consent />;
  const routes = user.role === "admin" ? ADMIN_ROUTES : STUDENT_ROUTES;
  for (const [pattern, render] of routes) {
    const params = match(pattern, path);
    if (params) return <Shell>{render(params)}</Shell>;
  }
  return (
    <Shell>
      <div className="page"><div className="empty"><h3>This page doesn't exist</h3><p>Use the menu to find what you need.</p></div></div>
    </Shell>
  );
}

