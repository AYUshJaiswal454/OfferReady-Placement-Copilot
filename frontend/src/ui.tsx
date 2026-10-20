import { ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { LuCheck, LuChevronDown, LuChevronRight, LuCopy, LuMinus, LuX } from "react-icons/lu";
import { Json } from "./api";

// ------------------------------------------------------------------ data loading
export function useLoad<T = Json>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);
  const reload = useCallback(async () => {
    const n = ++seq.current;
    setLoading(true);
    try {
      const d = await fn();
      if (n === seq.current) { setData(d); setError(null); }
    } catch (e) {
      if (n === seq.current) setError((e as Error).message);
    } finally {
      if (n === seq.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => { reload(); }, [reload]);
  return { data, error, loading, reload, setData };
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <div className="row muted" style={{ padding: "2rem 0" }}><span className="spinner" /> {label}</div>;
}

export function ErrorNote({ error, retry }: { error: string; retry?: () => void }) {
  return (
    <div className="notice bad row">
      <span className="grow">{error}</span>
      {retry && <button className="btn small secondary" onClick={retry}>Try again</button>}
    </div>
  );
}

// ------------------------------------------------------------------ marks & scores
export function Mark({ status }: { status: string }) {
  const label = { pass: "Pass", warn: "Needs work", fail: "Fail", na: "Not applicable" }[status] || status;
  return (
    <span className={`mark ${status}`} title={label} aria-label={label}>
      {status === "pass" ? <LuCheck /> : status === "fail" ? <LuX /> : status === "warn" ? "~" : <LuMinus />}
    </span>
  );
}

export function levelClass(level?: string) {
  return level === "Placement ready" ? "ready" : level === "Almost ready" ? "almost" : "not";
}

export function ScoreBlock({ score, level, sub }: { score: number | null | undefined; level?: string; sub?: ReactNode }) {
  return (
    <div className="score-block">
      <span className="score-num num">{score == null ? "—" : Math.round(score)}</span>
      <span className="score-of">/ 100</span>
      {level && <span className={`level ${levelClass(level)}`} style={{ paddingBottom: ".35rem" }}>{level}</span>}
      {sub && <span className="muted" style={{ paddingBottom: ".4rem" }}>{sub}</span>}
    </div>
  );
}

export function Bar({ value, max = 100, missing = false }: { value: number | null | undefined; max?: number; missing?: boolean }) {
  const pct = value == null ? 0 : Math.max(0, Math.min(100, (value / max) * 100));
  return <div className={`bar ${missing ? "missing" : ""}`} role="img" aria-label={missing ? "Not added yet" : `${Math.round(pct)}%`}>
    <span style={{ width: `${pct}%` }} />
  </div>;
}

// ------------------------------------------------------------------ prose (tiny, safe markdown: **bold**, bullets, links)
function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|https?:\/\/[^\s)]+)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("**")) out.push(<strong key={i++}>{tok.slice(2, -2)}</strong>);
    else if (tok.startsWith("`")) out.push(<code key={i++}>{tok.slice(1, -1)}</code>);
    else out.push(<a key={i++} href={tok} target="_blank" rel="noreferrer">{tok}</a>);
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Prose({ text }: { text: string }) {
  const blocks = text.split(/\n{2,}/);
  return (
    <div className="prose">
      {blocks.map((b, bi) => {
        const lines = b.split("\n");
        if (lines.every((l) => /^\s*[•\-*]\s+/.test(l))) {
          return <ul key={bi}>{lines.map((l, li) => <li key={li}>{inline(l.replace(/^\s*[•\-*]\s+/, ""))}</li>)}</ul>;
        }
        const head = lines.filter((l) => !/^\s*[•\-*]\s+/.test(l));
        const items = lines.filter((l) => /^\s*[•\-*]\s+/.test(l));
        return (
          <div key={bi}>
            {head.length > 0 && <p>{head.map((l, li) => <span key={li}>{inline(l)}{li < head.length - 1 && <br />}</span>)}</p>}
            {items.length > 0 && <ul>{items.map((l, li) => <li key={li}>{inline(l.replace(/^\s*[•\-*]\s+/, ""))}</li>)}</ul>}
          </div>
        );
      })}
    </div>
  );
}

// ------------------------------------------------------------------ checks (marking scheme)
export type Check = { id: string; title: string; group: string; max: number; score: number; status: string; summary: string;
  why: string; evidence: Json[]; fixes: string[]; details: Json };

/** True while the page is being printed (or opened with ?print=1), so every check prints with its fixes. */
export function usePrinting(): boolean {
  const [printing, setPrinting] = useState(() => new URLSearchParams(window.location.search).has("print"));
  useEffect(() => {
    const on = () => setPrinting(true);
    const off = () => setPrinting(new URLSearchParams(window.location.search).has("print"));
    window.addEventListener("beforeprint", on);
    window.addEventListener("afterprint", off);
    return () => { window.removeEventListener("beforeprint", on); window.removeEventListener("afterprint", off); };
  }, []);
  return printing;
}

export function ChecksList({ checks, onEvidence, activeId, onToggle, openAll = false }: {
  checks: Check[]; onEvidence?: (check: Check, ev: Json) => void; activeId?: string; onToggle?: (id: string | null) => void; openAll?: boolean;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const printing = usePrinting();
  const isOpen = (id: string) => openAll || printing || open === id || activeId === id;
  return (
    <ul className="checks">
      {checks.map((c) => (
        <li key={c.id} className="check-row">
          <button className="check-head" aria-expanded={isOpen(c.id)} onClick={() => {
            const next = open === c.id ? null : c.id;
            setOpen(next);
            onToggle?.(next);
          }}>
            <Mark status={c.status} />
            <span>
              <span className="check-title">{c.title}</span>
              <span className="check-summary" style={{ display: "block" }}>{c.summary}</span>
            </span>
            <span className="check-marks">
              {c.status === "na" ? <span className="muted">n/a</span> : <><b>{fmtMarks(c.score)}</b><span className="muted"> / {fmtMarks(c.max)}</span></>}
              <span style={{ marginLeft: ".4rem", verticalAlign: "middle" }} aria-hidden>{isOpen(c.id) ? <LuChevronDown /> : <LuChevronRight />}</span>
            </span>
          </button>
          {isOpen(c.id) && (
            <div className="check-body">
              {c.why && <p className="why">{c.why}</p>}
              {c.fixes?.length > 0 && (
                <ul className="fixes">{c.fixes.map((f, i) => <li key={i}>{f}</li>)}</ul>
              )}
              {c.evidence?.length > 0 && (
                <ul className="evidence">
                  {c.evidence.map((ev, i) => (
                    <li key={i}>
                      {ev.page && ev.bbox && onEvidence ? (
                        <button className="loc" onClick={() => onEvidence(c, ev)} title="Show on the page">p{ev.page}</button>
                      ) : ev.label ? <span className="tag">{ev.label}</span> : null}
                      <span>
                        {ev.text}
                        {ev.suggestion && ev.suggestion.length > 20 && <span className="suggest">{ev.suggestion}</span>}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

function fmtMarks(n: number) {
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

// ------------------------------------------------------------------ misc widgets
export function Modal({ title, onClose, children, footer }: { title: string; onClose: () => void; children: ReactNode; footer?: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("input, textarea, select, button")?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); prev?.focus(); };
  }, [onClose]);
  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} ref={ref}>
        <h2>{title}</h2>
        {children}
        {footer && <div className="foot">{footer}</div>}
      </div>
    </div>
  );
}

export function CopyBlock({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="copy-block">
      <button className="btn small secondary" onClick={async () => {
        await navigator.clipboard?.writeText(text).catch(() => null);
        setCopied(true);
        setTimeout(() => setCopied(false), 1600);
      }}><LuCopy /> {copied ? "Copied" : "Copy"}</button>
      <div style={{ paddingRight: "5.5rem" }}>{text}</div>
    </div>
  );
}

export function Segmented<T extends string | number>({ value, options, onChange, label }: {
  value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; label: string;
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={String(o.value)} type="button" aria-pressed={o.value === value} onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  );
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return <div className="empty"><h3>{title}</h3>{children && <p style={{ margin: "0 auto" }}>{children}</p>}{action}</div>;
}

// ------------------------------------------------------------------ charts (plain SVG)
export function LineChart({ points, height = 160, max = 100 }: { points: { x: string; y: number }[]; height?: number; max?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(600);
  useEffect(() => {
    const ro = new ResizeObserver((es) => setW(Math.max(260, es[0].contentRect.width)));
    if (ref.current) ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  if (points.length === 0) return null;
  const pad = { l: 34, r: 14, t: 12, b: 26 };
  const iw = w - pad.l - pad.r;
  const ih = height - pad.t - pad.b;
  const xs = (i: number) => pad.l + (points.length === 1 ? iw / 2 : (i * iw) / (points.length - 1));
  const ys = (v: number) => pad.t + ih - (v / max) * ih;
  const d = points.map((p, i) => `${i ? "L" : "M"}${xs(i).toFixed(1)},${ys(p.y).toFixed(1)}`).join(" ");
  const ticks = [0, 50, 75, 100];
  return (
    <div ref={ref}>
      <svg className="chart" width={w} height={height} role="img" aria-label={`Score history: ${points.map((p) => Math.round(p.y)).join(", ")}`}>
        <rect className="band" x={pad.l} y={ys(100)} width={iw} height={ys(75) - ys(100)} />
        <g className="grid">{ticks.map((t) => <line key={t} x1={pad.l} x2={w - pad.r} y1={ys(t)} y2={ys(t)} />)}</g>
        {ticks.map((t) => <text key={t} x={pad.l - 8} y={ys(t) + 4} textAnchor="end">{t}</text>)}
        <path className="line" d={d} />
        {points.map((p, i) => <circle key={i} className="dot" cx={xs(i)} cy={ys(p.y)} r={4}><title>{`${p.x}: ${Math.round(p.y)}`}</title></circle>)}
        {points.length > 1 && <>
          <text x={xs(0)} y={height - 6} textAnchor="start">{points[0].x}</text>
          <text x={xs(points.length - 1)} y={height - 6} textAnchor="end">{points[points.length - 1].x}</text>
        </>}
      </svg>
    </div>
  );
}

export function Histogram({ bins, height = 170 }: { bins: { label: string; count: number; hot?: boolean }[]; height?: number }) {
  const max = Math.max(1, ...bins.map((b) => b.count));
  const w = 36 * bins.length + 40;
  return (
    <svg className="chart" viewBox={`0 0 ${w} ${height}`} width="100%" role="img" aria-label="Distribution">
      {bins.map((b, i) => {
        const h = ((height - 40) * b.count) / max;
        return (
          <g key={b.label}>
            <rect className={`barrect ${b.hot ? "hot" : ""}`} x={30 + i * 36} y={height - 24 - h} width={26} height={Math.max(h, b.count ? 2 : 0)} rx={3}>
              <title>{`${b.label}: ${b.count}`}</title>
            </rect>
            {b.count > 0 && <text x={43 + i * 36} y={height - 28 - h} textAnchor="middle">{b.count}</text>}
            <text x={43 + i * 36} y={height - 8} textAnchor="middle">{b.label.split("–")[0]}</text>
          </g>
        );
      })}
    </svg>
  );
}
