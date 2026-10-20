import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, Json } from "./api";
import { navigate } from "./router";

// ------------------------------------------------------------------ auth
type User = Json;
type AuthCtx = { user: User | null; loading: boolean; refresh: () => Promise<void>; setUser: (u: User | null) => void; logout: () => Promise<void> };
const Auth = createContext<AuthCtx>({} as AuthCtx);
export const useAuth = () => useContext(Auth);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const refresh = useCallback(async () => {
    try {
      const res = await api.get("/auth/me");
      setUser(res.user);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);
  const logout = useCallback(async () => {
    await api.post("/auth/logout").catch(() => null);
    setUser(null);
    navigate("/login");
  }, []);
  useEffect(() => {
    refresh();
    const onUnauth = () => setUser(null);
    window.addEventListener("or:unauthenticated", onUnauth);
    return () => window.removeEventListener("or:unauthenticated", onUnauth);
  }, [refresh]);
  return <Auth.Provider value={{ user, loading, refresh, setUser, logout }}>{children}</Auth.Provider>;
}

// ------------------------------------------------------------------ toasts
type Toast = { id: number; text: ReactNode; kind?: "error" | "info"; href?: string; linkText?: string };
type ToastCtx = { push: (t: Omit<Toast, "id">) => void };
const Toasts = createContext<ToastCtx>({ push: () => undefined });
export const useToast = () => useContext(Toasts);

// ------------------------------------------------------------------ background tasks
type Task = { id: number; kind: string; label: string; status: string; progress: number; message?: string; error?: string };
type TasksCtx = { tasks: Task[]; track: (id: number | number[]) => void };
const Tasks = createContext<TasksCtx>({ tasks: [], track: () => undefined });
export const useTasks = () => useContext(Tasks);

const DONE_LINKS: Record<string, [string, string]> = {
  review_resume: ["/report#resume", "See resume review"], review_linkedin: ["/report#linkedin", "See LinkedIn review"],
  review_github: ["/report#github", "See GitHub review"], review_project: ["/report#projects", "See project review"],
  review_coding: ["/report#coding", "See coding review"], score_interview: ["/interview", "See interview feedback"],
};

export function AppProviders({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const watched = useRef<Set<number>>(new Set());
  const { user } = useAuth();

  const push = useCallback((t: Omit<Toast, "id">) => {
    const id = Date.now() + Math.random();
    setToasts((xs) => [...xs, { ...t, id }]);
    setTimeout(() => setToasts((xs) => xs.filter((x) => x.id !== id)), t.kind === "error" ? 7000 : 5500);
  }, []);

  const pollRef = useRef<() => void>(() => undefined);
  const track = useCallback((id: number | number[]) => {
    (Array.isArray(id) ? id : [id]).forEach((x) => x && watched.current.add(x));
    setTimeout(() => pollRef.current(), 300);
  }, []);

  const poll = useCallback(async () => {
    if (!user) return;
    try {
      const res = await api.get("/tasks");
      const active: Task[] = res.tasks;
      active.forEach((t) => (t.status === "queued" || t.status === "running") && watched.current.add(t.id));
      const ids = [...watched.current];
      let finished: Task[] = [];
      if (ids.length) {
        const st = await api.get("/tasks", { ids: ids.join(",") });
        finished = st.tasks.filter((t: Task) => t.status === "done" || t.status === "failed");
        finished.forEach((t) => watched.current.delete(t.id));
      }
      setTasks(active.filter((t) => t.status === "queued" || t.status === "running"));
      for (const t of finished) {
        window.dispatchEvent(new CustomEvent("or:task-done", { detail: t }));
        const link = DONE_LINKS[t.kind];
        if (t.status === "failed") push({ kind: "error", text: `${t.label} failed: ${t.error || "unknown error"}` });
        else if (link) push({ text: `${t.label} is ready.`, href: link[0], linkText: link[1] });
      }
    } catch { /* offline or logged out */ }
  }, [user, push]);
  pollRef.current = poll;

  useEffect(() => {
    if (!user) return;
    poll();
    const iv = setInterval(() => {
      if (watched.current.size || tasks.length) poll();
    }, 1800);
    const slow = setInterval(poll, 15000);
    return () => { clearInterval(iv); clearInterval(slow); };
  }, [user, poll, tasks.length]);

  return (
    <Toasts.Provider value={{ push }}>
      <Tasks.Provider value={{ tasks, track }}>
        {children}
        <div className="tasks-float" aria-live="polite">
          {tasks.slice(0, 3).map((t) => (
            <div className="task-line" key={t.id}>
              <div className="row"><b>{t.label}</b><span className="small muted">{t.status === "queued" ? "Waiting…" : `${t.progress}%`}</span></div>
              {t.message && <div className="small muted">{t.message}</div>}
              <div className="progress" style={{ marginTop: ".4rem" }}><span style={{ width: `${Math.max(6, t.progress)}%` }} /></div>
            </div>
          ))}
          {toasts.map((t) => (
            <div key={t.id} className={`toast ${t.kind === "error" ? "error" : ""}`} role="status">
              <span className="grow">{t.text}</span>
              {t.href && <a href={t.href} onClick={(e) => { e.preventDefault(); navigate(t.href!); }}>{t.linkText || "Open"}</a>}
            </div>
          ))}
        </div>
      </Tasks.Provider>
    </Toasts.Provider>
  );
}

export function useTaskDone(handler: (t: Task) => void, deps: unknown[] = []) {
  useEffect(() => {
    const fn = (e: Event) => handler((e as CustomEvent).detail);
    window.addEventListener("or:task-done", fn);
    return () => window.removeEventListener("or:task-done", fn);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}
