"""Expand the Hunspell en_US dictionary (SCOWL-derived, permissive licence) into a flat
word list used by the resume spell checker: app/data/words_en.txt.gz

Usage: python scripts/build_wordlist.py [/usr/share/hunspell/en_US.dic] [/usr/share/hunspell/en_US.aff]
"""
from __future__ import annotations

import gzip
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def parse_aff(path: Path):
    rules: dict[str, dict] = {}
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    i = 0
    while i < len(lines):
        parts = lines[i].split()
        if len(parts) == 4 and parts[0] in ("PFX", "SFX") and parts[2] in ("Y", "N"):
            kind, flag, cross, count = parts[0], parts[1], parts[2] == "Y", int(parts[3])
            entries = []
            for j in range(1, count + 1):
                p = lines[i + j].split()
                strip = "" if p[2] == "0" else p[2]
                add = p[3].split("/")[0]
                add = "" if add == "0" else add
                cond = p[4] if len(p) > 4 else "."
                regex = re.compile(("^" + cond) if kind == "PFX" else (cond + "$"))
                entries.append((strip, add, regex))
            rules[flag] = {"kind": kind, "cross": cross, "entries": entries}
            i += count + 1
            continue
        i += 1
    return rules


def expand(word: str, flags: str, rules: dict) -> set[str]:
    out = {word}
    suffixed: list[tuple[str, bool]] = []
    for flag in flags:
        rule = rules.get(flag)
        if not rule or rule["kind"] != "SFX":
            continue
        for strip, add, regex in rule["entries"]:
            if regex.search(word) and (not strip or word.endswith(strip)):
                new = (word[: len(word) - len(strip)] if strip else word) + add
                out.add(new)
                suffixed.append((new, rule["cross"]))
    for flag in flags:
        rule = rules.get(flag)
        if not rule or rule["kind"] != "PFX":
            continue
        for strip, add, regex in rule["entries"]:
            if regex.search(word):
                out.add(add + word[len(strip):])
                if rule["cross"]:
                    for new, cross in suffixed:
                        if cross:
                            out.add(add + new[len(strip):])
    return out


def main() -> None:
    dic = Path(sys.argv[1] if len(sys.argv) > 1 else "/usr/share/hunspell/en_US.dic")
    aff = Path(sys.argv[2] if len(sys.argv) > 2 else "/usr/share/hunspell/en_US.aff")
    rules = parse_aff(aff)
    words: set[str] = set()
    for line in dic.read_text(encoding="utf-8", errors="ignore").splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        word, _, flags = line.partition("/")
        if any(ch.isdigit() for ch in word):
            continue
        for w in expand(word, flags, rules):
            if w and "'" not in w or w.endswith("'s"):
                words.add(w)
    target = ROOT / "app" / "data" / "words_en.txt.gz"
    target.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(target, "wt", encoding="utf-8") as fh:
        fh.write("\n".join(sorted(words)))
    print(f"wrote {len(words)} words to {target}")


if __name__ == "__main__":
    main()
