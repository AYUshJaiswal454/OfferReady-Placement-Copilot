"""Shared structures for every review (resume, LinkedIn, GitHub, projects, coding)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Evidence:
    text: str
    page: int | None = None
    bbox: list[float] | None = None
    label: str = ""
    suggestion: str | None = None

    @classmethod
    def at(cls, text: str, ref: dict | None, label: str = "", suggestion: str | None = None) -> "Evidence":
        ref = ref or {}
        return cls(text=text, page=ref.get("page"), bbox=ref.get("bbox"), label=label, suggestion=suggestion)


@dataclass
class Check:
    id: str
    title: str
    group: str
    max: float
    score: float = 0.0
    status: str = "pass"          # pass | warn | fail | na
    summary: str = ""
    why: str = ""
    evidence: list[Evidence] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    effort: str = "quick"         # quick | medium | long  (used to rank actions)

    def finish(self, score: float | None = None, summary: str | None = None) -> "Check":
        if score is not None:
            self.score = score
        self.score = round(max(0.0, min(self.max, self.score)), 2)
        if summary is not None:
            self.summary = summary
        if self.status != "na":
            ratio = self.score / self.max if self.max else 1.0
            self.status = "pass" if ratio >= 0.9 else ("warn" if ratio >= 0.5 else "fail")
        return self

    def na(self, summary: str) -> "Check":
        self.status = "na"
        self.summary = summary
        self.score = 0.0
        return self

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["evidence"] = [asdict(e) for e in self.evidence][:25]
        return d


def total_score(checks: list[Check]) -> float:
    """Score out of 100, ignoring checks that do not apply."""
    applicable = [c for c in checks if c.status != "na"]
    possible = sum(c.max for c in applicable)
    if possible <= 0:
        return 0.0
    return round(100.0 * sum(c.score for c in applicable) / possible, 1)


def plural(n: int, word: str, plural_word: str | None = None) -> str:
    return f"{n} {word if n == 1 else (plural_word or word + 's')}"
