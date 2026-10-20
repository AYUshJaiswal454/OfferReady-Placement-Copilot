"""Spell checking tuned for student resumes.

Precision matters more than recall: a false "spelling mistake" on a project name destroys
trust in the whole review. So a word is only reported when it is not in the English/tech
dictionary *and* a confident correction exists. Proper nouns (capitalised mid-sentence),
acronyms, CamelCase product names and anything with digits are never reported.
British spellings are accepted (common in Indian English) and handled by the style check.
"""
from __future__ import annotations

import re
from functools import lru_cache

from .lexicon import english_words, suggestion_vocab

WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’\-]*[A-Za-z]|[A-Za-z]")
LETTERS = "abcdefghijklmnopqrstuvwxyz"

UK_TO_US = [
    (r"isation$", "ization"), (r"isations$", "izations"), (r"ise$", "ize"), (r"ised$", "ized"), (r"ising$", "izing"),
    (r"iser$", "izer"), (r"isers$", "izers"), (r"ises$", "izes"), (r"yse$", "yze"), (r"ysed$", "yzed"),
    (r"ysing$", "yzing"), (r"(?<=..[a-z]{2})our$", "or"), (r"(?<=..[a-z]{2})ours$", "ors"), (r"oured$", "ored"),
    (r"ouring$", "oring"), (r"(?<=[a-z]{3})tre$", "ter"), (r"(?<=[a-z]{3})tres$", "ters"), (r"elled$", "eled"),
    (r"elling$", "eling"), (r"eller$", "eler"), (r"ogue$", "og"), (r"ogues$", "ogs"), (r"(?<=[a-z]{3})ence$", "ense"),
    (r"(?<=gra)mme$", "m"), (r"(?<=gra)mmes$", "ms"),
]
NOT_BRITISH = {"devour", "detour", "contour", "parlour", "filled", "pulled", "precise", "promise", "premise", "expertise",
               "exercise", "enterprise", "surprise", "compromise", "concise", "otherwise", "likewise", "advertise",
               "comprise", "franchise", "merchandise", "supervise", "televise", "improvise", "revise", "devise",
               "advise", "excise", "chastise", "despise", "disguise", "paradise", "raise", "praise", "noise", "poise"}


def is_british_variant(word: str) -> str | None:
    if word in NOT_BRITISH:
        return None
    words = english_words()
    for pattern, repl in UK_TO_US:
        if re.search(pattern, word):
            us = re.sub(pattern, repl, word)
            if us in words:
                return us
    return None


def known(word: str) -> bool:
    w = word.lower().replace("’", "'")
    words = english_words()
    if w in words:
        return True
    if w.endswith("'s") and w[:-2] in words:
        return True
    if w.endswith("s") and w[:-1] in words:  # plurals of tech nouns ("dashboards", "APIs")
        return True
    if is_british_variant(w):
        return True
    return False


def _edits1(word: str) -> set[str]:
    splits = [(word[:i], word[i:]) for i in range(len(word) + 1)]
    deletes = [a + b[1:] for a, b in splits if b]
    transposes = [a + b[1] + b[0] + b[2:] for a, b in splits if len(b) > 1]
    replaces = [a + c + b[1:] for a, b in splits if b for c in LETTERS]
    inserts = [a + c + b for a, b in splits for c in LETTERS]
    return set(deletes + transposes + replaces + inserts)


def _damerau(a: str, b: str, limit: int = 3) -> int:
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[len(a)][len(b)]


@lru_cache(maxsize=4096)
def suggest(word: str) -> str | None:
    """Best correction for a misspelt word, or None when we are not confident."""
    w = word.lower()
    if len(w) < 4:
        return None
    words = english_words()
    vocab = suggestion_vocab()
    candidates = [c for c in _edits1(w) if c in words]
    preferred = [c for c in candidates if c in vocab]
    pool = preferred or candidates
    if not pool:
        near = [v for v in vocab if abs(len(v) - len(w)) <= 2 and v[0] == w[0] and _damerau(w, v, 2) <= 2]
        if not near:
            return None
        pool = near

    def rank(c: str) -> tuple:
        return (
            0 if c in vocab else 1,
            0 if c[0] == w[0] else 1,
            0 if c.endswith("ed") else 1,           # resume bullets are mostly past-tense verbs
            0 if c[-1] == w[-1] else 1,
            0 if sorted(c) == sorted(w) else 1,     # transposition / missing letter keeps letters
            abs(len(c) - len(w)),
            0 if c.endswith(w[-2:]) else 1,
            c,
        )

    best = sorted(pool, key=rank)[0]
    # Short, common edits only: reject corrections that change the first letter of short words.
    if best[0] != w[0] and len(w) < 6:
        return None
    return best


def _match_case(original: str, suggestion: str) -> str:
    if original.isupper():
        return suggestion.upper()
    if original[:1].isupper():
        return suggestion[:1].upper() + suggestion[1:]
    return suggestion


def find_misspellings(text: str, sentence_start: bool = True) -> list[dict]:
    """Return [{word, suggestion, index}] for one line/bullet of text."""
    out = []
    tokens = list(WORD_RE.finditer(text))
    for i, m in enumerate(tokens):
        word = m.group(0).strip("'’-")
        start = m.start()
        at_start = (i == 0 and sentence_start) or bool(re.search(r"[.!?:;•|]\s*$", text[:start]))
        if len(word) < 3 or any(ch.isdigit() for ch in word):
            continue
        if "/" in text[max(0, start - 1):start] or text[m.end():m.end() + 1] in ("/", ".", "@") and not text[m.end():m.end() + 2].endswith(" "):
            continue  # part of a URL, path or file name
        if word.isupper():
            continue  # acronym
        if re.search(r"[a-z][A-Z]", word):
            continue  # CamelCase product / project name
        if word[0].isupper() and not at_start:
            continue  # proper noun mid-sentence
        parts = [p for p in re.split(r"[-’']", word) if p]
        if all(known(p) for p in parts) or known(word):
            continue
        bad = next((p for p in parts if not known(p)), word)
        if len(bad) < 3:
            continue
        sug = suggest(bad)
        if not sug or sug.lower() == bad.lower():
            continue
        out.append({"word": bad, "suggestion": _match_case(bad, sug), "index": start})
    return out
