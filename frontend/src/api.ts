// Thin client for the OfferReady API. Cookie session + CSRF header on every write.

export type Json = any;

export class ApiError extends Error {
  status: number;
  code: string;
  details?: Json;
  constructor(status: number, message: string, code = "error", details?: Json) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

const HEADERS = { "X-Requested-With": "offerready" };

async function handle(res: Response): Promise<Json> {
  const type = res.headers.get("content-type") || "";
  if (!res.ok) {
    let body: Json = {};
    try { body = type.includes("json") ? await res.json() : { error: await res.text() }; } catch { /* ignore */ }
    if (res.status === 401 && !location.pathname.startsWith("/login")) window.dispatchEvent(new Event("or:unauthenticated"));
    throw new ApiError(res.status, body.error || `Request failed (${res.status})`, body.code, body.details);
  }
  return type.includes("json") ? res.json() : res;
}

export const api = {
  get: (path: string, params?: Record<string, string | number | boolean | undefined | null>) => {
    const q = params ? "?" + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
      .map(([k, v]) => [k, String(v)])).toString() : "";
    return fetch(`/api${path}${q === "?" ? "" : q}`, { credentials: "same-origin" }).then(handle);
  },
  post: (path: string, body?: Json) =>
    fetch(`/api${path}`, { method: "POST", credentials: "same-origin", headers: { ...HEADERS, "content-type": "application/json" },
      body: JSON.stringify(body ?? {}) }).then(handle),
  put: (path: string, body?: Json) =>
    fetch(`/api${path}`, { method: "PUT", credentials: "same-origin", headers: { ...HEADERS, "content-type": "application/json" },
      body: JSON.stringify(body ?? {}) }).then(handle),
  patch: (path: string, body?: Json) =>
    fetch(`/api${path}`, { method: "PATCH", credentials: "same-origin", headers: { ...HEADERS, "content-type": "application/json" },
      body: JSON.stringify(body ?? {}) }).then(handle),
  del: (path: string, body?: Json) =>
    fetch(`/api${path}`, { method: "DELETE", credentials: "same-origin", headers: { ...HEADERS, "content-type": "application/json" },
      body: body ? JSON.stringify(body) : undefined }).then(handle),
  upload: (path: string, file: Blob, fields: Record<string, string> = {}, filename?: string) => {
    const fd = new FormData();
    fd.append("file", file, filename || (file as File).name || "upload");
    Object.entries(fields).forEach(([k, v]) => fd.append(k, v));
    return fetch(`/api${path}`, { method: "POST", credentials: "same-origin", headers: HEADERS, body: fd }).then(handle);
  },
};

export type ChatEvent = { type: "delta"; text: string } | { type: "cards"; cards: Json[] } | { type: "done"; message_id: number | null }
  | { type: "error"; message: string };

export async function streamChat(message: string, onEvent: (e: ChatEvent) => void): Promise<void> {
  const res = await fetch("/api/chat", {
    method: "POST", credentials: "same-origin", headers: { ...HEADERS, "content-type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!res.ok || !res.body) {
    await handle(res);
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const line = chunk.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      try { onEvent(JSON.parse(line.slice(5))); } catch { /* ignore malformed */ }
    }
  }
}

export function fileUrl(id: number | string | undefined | null): string {
  return id ? `/api/files/${id}` : "";
}

export function timeAgo(iso?: string | null): string {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  const d = Math.floor(s / 86400);
  return d === 1 ? "yesterday" : d < 30 ? `${d} days ago` : new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

export function fmtDate(iso?: string | null, withTime = false): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric",
    ...(withTime ? { hour: "numeric", minute: "2-digit" } : {}) });
}
