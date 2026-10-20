// The student's own resume page with every problem marked in highlighter and noted in the margin.
import { useMemo, useState } from "react";
import { fileUrl, Json } from "../api";
import { Check } from "../ui";

type Note = { n: number; check: Check; ev: Json };

export default function ResumeViewer({ review, focusCheck, onPick }: { review: Json; focusCheck?: string | null; onPick?: (checkId: string) => void }) {
  const [active, setActive] = useState<number | null>(null);
  const pages: number[] = review.data?.page_files || [];
  const [pw, ph] = review.data?.page_size || [595, 842];
  const notes: Note[] = useMemo(() => {
    const out: Note[] = [];
    let n = 1;
    for (const c of review.checks as Check[]) {
      if (c.status === "pass" || c.status === "na") continue;
      if (focusCheck && c.id !== focusCheck) continue;
      for (const ev of c.evidence || []) {
        if (ev.page && ev.bbox && ev.page <= pages.length) out.push({ n: n++, check: c, ev });
      }
    }
    return out.slice(0, 40);
  }, [review, focusCheck, pages.length]);

  if (!pages.length) return null;
  return (
    <div className="viewer">
      <div>
        {pages.map((fid, i) => (
          <div className="page-img" key={fid} style={{ aspectRatio: `${pw} / ${ph}` }}>
            <img src={fileUrl(fid)} alt={`Resume page ${i + 1}`} style={{ width: "100%", height: "100%" }} />
            {notes.filter((x) => x.ev.page === i + 1).map((x) => {
              const [x0, y0, x1, y1] = x.ev.bbox;
              const pad = 2;
              return (
                <button key={x.n} className={`box ${x.check.status === "fail" ? "fail" : ""} ${active === x.n ? "active" : ""}`}
                  aria-label={`Issue ${x.n}: ${x.check.title}`}
                  onClick={() => { setActive(x.n); onPick?.(x.check.id); document.getElementById(`note-${x.n}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }}
                  style={{ left: `${((x0 - pad) / pw) * 100}%`, top: `${((y0 - pad) / ph) * 100}%`,
                    width: `${((x1 - x0 + pad * 2) / pw) * 100}%`, height: `${((y1 - y0 + pad * 2) / ph) * 100}%`, border: 0, padding: 0 }}>
                  <span className="box-tag" style={{ left: 0, top: 0 }}>{x.n}</span>
                </button>
              );
            })}
          </div>
        ))}
      </div>
      <div>
        <p className="small muted" style={{ marginBottom: ".6rem" }}>
          {notes.length ? `${notes.length} marked ${notes.length === 1 ? "spot" : "spots"} on your page${focusCheck ? " for this check" : ""}. Select one to see the fix.` : "Nothing to mark on the page for this check."}
        </p>
        <ol className="margin-notes" aria-label="Margin notes">
          {notes.map((x) => (
            <li key={x.n} id={`note-${x.n}`} className={active === x.n ? "active" : ""} onClick={() => setActive(x.n)}>
              <span className="n">{x.n}</span><b>{x.check.title}</b>
              <div>{x.ev.text}</div>
              {x.ev.suggestion && <div className="suggest small">{x.ev.suggestion}</div>}
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
