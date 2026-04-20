"""Scam signals database — 1:1 port of ``app/lib/data/scam_db.dart``.

Loads a CSV of (type, value, weight, tag, note) rows and exposes filtered
iterators for blocklisted numbers, phishing domains, and scam keywords.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class ScamEntryType(str, Enum):
    NUMBER = "number"
    DOMAIN = "domain"
    KEYWORD = "keyword"


@dataclass(frozen=True)
class ScamEntry:
    type: ScamEntryType
    value: str
    weight: float
    tag: str
    note: str


class ScamDatabase:
    def __init__(self, entries: list[ScamEntry]) -> None:
        self.entries = entries

    @classmethod
    def from_csv(cls, raw: str) -> "ScamDatabase":
        """Parse the CSV. First row is the header; empty rows skipped."""
        lines = [line for line in raw.splitlines() if line.strip()]
        out: list[ScamEntry] = []
        # Skip header.
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) < 4:
                continue
            raw_type = parts[0].strip()
            try:
                entry_type = ScamEntryType(raw_type)
            except ValueError:
                continue
            try:
                weight = float(parts[2].strip())
            except ValueError:
                weight = 0.5
            out.append(
                ScamEntry(
                    type=entry_type,
                    value=parts[1].strip().lower(),
                    weight=weight,
                    tag=parts[3].strip(),
                    note=",".join(parts[4:]).strip() if len(parts) > 4 else "",
                )
            )
        return cls(out)

    def bad_numbers(self) -> Iterable[ScamEntry]:
        return (e for e in self.entries if e.type is ScamEntryType.NUMBER)

    def bad_domains(self) -> Iterable[ScamEntry]:
        return (e for e in self.entries if e.type is ScamEntryType.DOMAIN)

    def keywords(self) -> Iterable[ScamEntry]:
        return (e for e in self.entries if e.type is ScamEntryType.KEYWORD)
