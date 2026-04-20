"""Append-only event log with per-event risk annotations.

1:1 port of ``app/lib/data/event_log.dart``. Lives in session state; not
thread-safe, but Streamlit reruns on the main thread so that's fine.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Iterable, Iterator

from guardian.scenarios.events import ScamEvent


@dataclass
class EventLogEntry:
    event: ScamEvent
    risk_score: float | None = None
    tags: list[str] = field(default_factory=list)


class EventLog:
    def __init__(self) -> None:
        self._entries: list[EventLogEntry] = []

    def __iter__(self) -> Iterator[EventLogEntry]:
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def entries(self) -> list[EventLogEntry]:
        return list(self._entries)

    def add(self, event: ScamEvent) -> None:
        self._entries.append(EventLogEntry(event=event))

    def annotate(
        self,
        event_id: str,
        *,
        risk: float | None = None,
        tags: list[str] | None = None,
    ) -> None:
        for i, entry in enumerate(self._entries):
            if entry.event.id == event_id:
                self._entries[i] = replace(
                    entry,
                    risk_score=risk if risk is not None else entry.risk_score,
                    tags=tags if tags is not None else entry.tags,
                )
                return

    def clear(self) -> None:
        self._entries.clear()

    def within(self, window: timedelta, now: datetime | None = None) -> Iterable[ScamEvent]:
        n = now or datetime.now()
        cutoff = n - window
        for entry in self._entries:
            if entry.event.timestamp > cutoff:
                yield entry.event
