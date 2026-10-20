"""Compare the resume review with your own reviewers on real resumes.

1. Make a labelling sheet (the engine's verdicts, for reviewers to correct):
       python scripts/eval_resumes.py resumes/ --template labels.csv
   Open labels.csv, and for every resume set each check column to pass or fail as a human reviewer would.
2. Measure agreement:
       python scripts/eval_resumes.py resumes/ labels.csv
   Prints precision, recall and agreement per check and overall, and lists every disagreement.

Check ids and their benchmarks are described in docs/BENCHMARKS.md.
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def review(path: Path, role: str) -> dict[str, str]:
    from app.intake.resume_parser import parse_resume_pdf
    from app.review.resume_checks import review_resume

    result = review_resume(parse_resume_pdf(path.read_bytes(), ocr=True), path.name, role)
    return {c["id"]: ("fail" if c["status"] in ("fail", "warn") else "pass") for c in result["checks"] if c["status"] != "na"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("labels", type=Path, nargs="?")
    ap.add_argument("--template", type=Path, help="write a labelling sheet prefilled with the engine's verdicts")
    ap.add_argument("--role", default="Software Engineer")
    a = ap.parse_args()
    files = sorted(a.folder.glob("*.pdf"))
    if not files:
        sys.exit(f"No PDFs in {a.folder}")
    engine = {f.name: review(f, a.role) for f in files}
    checks = sorted({c for v in engine.values() for c in v}, key=lambda s: [float(x) if x.replace('.', '').isdigit() else 0
                                                                            for x in s[1:].split(".")])
    if a.template:
        with a.template.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["file", *checks])
            for name, v in engine.items():
                w.writerow([name, *[v.get(c, "") for c in checks]])
        print(f"Wrote {a.template} with {len(files)} resumes. Correct it, then run again with it as the labels file.")
        return
    if not a.labels:
        sys.exit("Give a labels CSV, or --template to create one.")
    human = {row["file"]: row for row in csv.DictReader(a.labels.open(encoding="utf-8-sig"))}
    per = defaultdict(Counter)
    disagreements = []
    for name, verdicts in engine.items():
        if name not in human:
            continue
        for c, got in verdicts.items():
            want = (human[name].get(c) or "").strip().lower()
            if want not in ("pass", "fail"):
                continue
            key = ("t" if got == want else "f") + ("p" if got == "fail" else "n")
            per[c][key] += 1
            if got != want:
                disagreements.append((name, c, want, got))
    tot = Counter()
    print(f"{'check':6s} {'agree':>7s} {'precision':>10s} {'recall':>8s}")
    for c in checks:
        v = per[c]
        tot.update(v)
        n = sum(v.values()) or 1
        prec = v["tp"] / ((v["tp"] + v["fp"]) or 1)
        rec = v["tp"] / ((v["tp"] + v["fn"]) or 1)
        print(f"{c:6s} {(v['tp'] + v['tn']) / n:7.1%} {prec:10.1%} {rec:8.1%}")
    n = sum(tot.values()) or 1
    print(f"\nOverall agreement {(tot['tp'] + tot['tn']) / n:.1%}, precision {tot['tp'] / ((tot['tp'] + tot['fp']) or 1):.1%}, "
          f"recall {tot['tp'] / ((tot['tp'] + tot['fn']) or 1):.1%} over {n} decisions.")
    if disagreements:
        print("\nDisagreements (file, check, human, engine):")
        for d in disagreements:
            print("  ", *d)


if __name__ == "__main__":
    main()
