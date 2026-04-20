"""Context Agent — 72-hour rolling snapshot of call/SMS/chat/txn events.

1:1 port of ``app/lib/agents/context_agent.dart``. Each ingest builds a
snapshot (recent event count, seconds since last call/SMS, prior max
risk score) and forwards to the risk agent for scoring.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from guardian.data.event_log import EventLog
from guardian.scenarios.events import (
    CallEvent,
    ChatEvent,
    ScamEvent,
    SmsEvent,
    TransactionEvent,
)

if TYPE_CHECKING:  # pragma: no cover - break import cycle
    from guardian.agents.risk_agent import RiskAgent
    from guardian.llm.tools import TraceCallback


_WINDOW = timedelta(hours=72)
_SENTINEL_SECONDS = 1 << 30


@dataclass(frozen=True)
class ContextSnapshot:
    triggering_event: ScamEvent
    recent_events: list[ScamEvent]
    now: datetime
    has_recent_call: bool
    has_recent_sms: bool
    has_recent_chat: bool
    seconds_since_last_call: int
    seconds_since_last_sms: int
    prior_max_risk: float

    @property
    def recent_event_count(self) -> int:
        return len(self.recent_events)


class ContextAgent:
    def __init__(self, event_log: EventLog, risk_agent: RiskAgent) -> None:
        self._log = event_log
        self._risk = risk_agent
        self.last_snapshot: ContextSnapshot | None = None
        self.trace_callback: TraceCallback | None = None
        self.trace_callback_factory: Callable[[ScamEvent], TraceCallback] | None = None

    def ingest(
        self,
        event: ScamEvent,
        trace_callback: TraceCallback | None = None,
    ) -> ContextSnapshot:
        self._log.add(event)
        recent = list(self._log.within(_WINDOW, now=event.timestamp))
        prior_max_risk = max(
            (
                entry.risk_score or 0.0
                for entry in self._log.entries
                if entry.event.id != event.id and entry.risk_score is not None
            ),
            default=0.0,
        )
        snapshot = self._build_snapshot(event, recent, prior_max_risk)
        self.last_snapshot = snapshot
        callback = trace_callback or self.trace_callback
        if callback is None and self.trace_callback_factory is not None:
            callback = self.trace_callback_factory(event)
        self._risk.assess(snapshot, trace_callback=callback)
        return snapshot

    @staticmethod
    def _build_snapshot(
        trigger: ScamEvent,
        recent: list[ScamEvent],
        prior_max_risk: float,
    ) -> ContextSnapshot:
        last_call: CallEvent | None = None
        last_sms: SmsEvent | None = None
        has_chat = False
        for e in recent:
            if isinstance(e, CallEvent):
                if last_call is None or e.timestamp > last_call.timestamp:
                    last_call = e
            elif isinstance(e, SmsEvent):
                if last_sms is None or e.timestamp > last_sms.timestamp:
                    last_sms = e
            elif isinstance(e, ChatEvent):
                has_chat = True
            elif isinstance(e, TransactionEvent):
                pass
        now = trigger.timestamp
        return ContextSnapshot(
            triggering_event=trigger,
            recent_events=list(recent),
            now=now,
            has_recent_call=last_call is not None,
            has_recent_sms=last_sms is not None,
            has_recent_chat=has_chat,
            seconds_since_last_call=(
                _SENTINEL_SECONDS
                if last_call is None
                else int((now - last_call.timestamp).total_seconds())
            ),
            seconds_since_last_sms=(
                _SENTINEL_SECONDS
                if last_sms is None
                else int((now - last_sms.timestamp).total_seconds())
            ),
            prior_max_risk=prior_max_risk,
        )
