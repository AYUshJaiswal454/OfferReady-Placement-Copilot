"""Boolean job-search queries: build them from a profile, parse them, evaluate them on job text.

Grammar:  expr := term (('AND' | 'OR' | implicit AND) term)* ; term := 'NOT' term | '(' expr ')' | "phrase" | word
Precedence: NOT > AND > OR (like LinkedIn / Naukri / Google boolean search).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..skills import ROLES, role_from_text, role_skill_weights, skill_category

TOKEN_RE = re.compile(r'\s*(\(|\)|"[^"]*"|\bAND\b|\bOR\b|\bNOT\b|[^\s()"]+)', re.I)


class QueryError(ValueError):
    pass


@dataclass
class Node:
    op: str                 # AND | OR | NOT | TERM
    children: list["Node"] | None = None
    term: str = ""


def tokenize(q: str) -> list[str]:
    tokens = []
    pos = 0
    q = q.strip()
    while pos < len(q):
        m = TOKEN_RE.match(q, pos)
        if not m:
            raise QueryError(f"Unexpected character at position {pos}")
        tok = m.group(1)
        pos = m.end()
        if tok:
            tokens.append(tok)
    return tokens


def parse(q: str) -> Node:
    tokens = tokenize(q)
    if not tokens:
        raise QueryError("Empty query")
    pos = 0

    def peek():
        return tokens[pos] if pos < len(tokens) else None

    def take():
        nonlocal pos
        tok = tokens[pos]
        pos += 1
        return tok

    def parse_or() -> Node:
        nodes = [parse_and()]
        while peek() and peek().upper() == "OR":
            take()
            nodes.append(parse_and())
        return nodes[0] if len(nodes) == 1 else Node("OR", nodes)

    def parse_and() -> Node:
        nodes = [parse_not()]
        while peek() and peek() != ")" and peek().upper() != "OR":
            if peek().upper() == "AND":
                take()
            nodes.append(parse_not())
        return nodes[0] if len(nodes) == 1 else Node("AND", nodes)

    def parse_not() -> Node:
        if peek() and peek().upper() == "NOT":
            take()
            return Node("NOT", [parse_not()])
        return parse_atom()

    def parse_atom() -> Node:
        tok = peek()
        if tok is None:
            raise QueryError("Query ends unexpectedly")
        if tok == "(":
            take()
            node = parse_or()
            if peek() != ")":
                raise QueryError("Missing closing parenthesis")
            take()
            return node
        if tok == ")":
            raise QueryError("Unexpected ')'")
        take()
        if tok.upper() in ("AND", "OR"):
            raise QueryError(f"'{tok}' needs a term on both sides")
        return Node("TERM", term=tok.strip('"').lower())

    node = parse_or()
    if pos != len(tokens):
        raise QueryError(f"Unexpected '{tokens[pos]}'")
    return node


def _term_matches(term: str, text: str) -> bool:
    if not term:
        return True
    pattern = r"(?<![a-z0-9+#])" + re.escape(term).replace(r"\ ", r"[\s\-]+") + r"(?![a-z0-9+#])"
    return re.search(pattern, text) is not None


def evaluate(node: Node, text: str) -> bool:
    if node.op == "TERM":
        return _term_matches(node.term, text)
    if node.op == "NOT":
        return not evaluate(node.children[0], text)
    if node.op == "AND":
        return all(evaluate(c, text) for c in node.children)
    return any(evaluate(c, text) for c in node.children)


def terms(node: Node, negated: bool = False) -> list[str]:
    if node.op == "TERM":
        return [] if negated else [node.term]
    if node.op == "NOT":
        return terms(node.children[0], True)
    out = []
    for c in node.children:
        out += terms(c, negated)
    return out


def quote(t: str) -> str:
    return f'"{t}"' if re.search(r"[\s.+#/-]", t) else t


CITY_ALIASES = {
    "bangalore": ["Bangalore", "Bengaluru"], "bengaluru": ["Bangalore", "Bengaluru"], "gurgaon": ["Gurgaon", "Gurugram"],
    "gurugram": ["Gurgaon", "Gurugram"], "mumbai": ["Mumbai", "Navi Mumbai"], "delhi": ["Delhi", "New Delhi", "NCR"],
    "noida": ["Noida", "NCR"], "hyderabad": ["Hyderabad"], "pune": ["Pune"], "chennai": ["Chennai"], "kolkata": ["Kolkata"],
    "ahmedabad": ["Ahmedabad"], "remote": ["remote", "work from home", "WFH"],
}


def build_query(skills: list[str], target_role: str | None, job_type: str | None, locations: list[str] | None) -> dict:
    """Default boolean query for a student + its parts (shown and editable in the UI)."""
    role_id = role_from_text(target_role)
    weights = role_skill_weights(role_id)
    bonus = {"language": 0.3, "backend": 0.5, "frontend": 0.5, "database": 0.2, "ml": 0.5, "data": 0.4, "mobile": 0.5,
             "devops": 0.4, "cloud": 0.2, "tools": -1, "cs_core": -1, "practices": -1, "testing": -0.2, "design": 0.2}
    ranked = sorted(dict.fromkeys(skills), key=lambda s: -(weights.get(s, 0) + bonus.get(skill_category(s), 0)))
    top_skills = [s for s in ranked if weights.get(s, 0) > 0][:4] or ranked[:4] or ROLES[role_id]["core"][:3]
    skills_part = "(" + " OR ".join(quote(s) for s in top_skills) + ")"
    if job_type == "fulltime":
        type_part = '("full time" OR fresher OR "entry level" OR graduate OR "new grad")'
    elif job_type == "both":
        type_part = '(intern OR internship OR fresher OR "entry level" OR graduate)'
    else:
        type_part = "(intern OR internship)"
    locs: list[str] = []
    for loc in locations or []:
        for alias in CITY_ALIASES.get(loc.strip().lower(), [loc.strip()]):
            if alias and alias not in locs:
                locs.append(alias)
    if "remote" not in [l.lower() for l in locs]:
        locs.append("remote")
    loc_part = "(" + " OR ".join(quote(l) for l in locs[:6]) + ")"
    role_terms = [s for s in ROLES[role_id]["synonyms"] if len(s) > 3][:3]
    role_part = "(" + " OR ".join(quote(s) for s in role_terms) + ")"
    query = f"{skills_part} AND {type_part} AND {loc_part}"
    return {"query": query, "parts": {"skills": skills_part, "type": type_part, "location": loc_part, "role": role_part},
            "skills": top_skills, "role_id": role_id, "keywords": " ".join(top_skills[:2] + role_terms[:1])}
