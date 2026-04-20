"""Intervention Agent — picks a level (none / banner / fullScreen / delay)
and materialises an :class:`InterventionAction` with headline + body.

1:1 port of ``app/lib/agents/intervention_agent.dart``. The UI reads
``state.ambient`` for the sticky banner and ``state.pending`` for the
modal takeover.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from guardian.scenarios.events import (
    CallEvent,
    ChatEvent,
    ScamEvent,
    SmsEvent,
    TransactionEvent,
)

if TYPE_CHECKING:  # pragma: no cover
    from guardian.agents.context_agent import ContextSnapshot
    from guardian.agents.risk_agent import RiskAssessment


class InterventionLevel(str, Enum):
    NONE = "none"
    BANNER = "banner"
    FULL_SCREEN = "fullScreen"
    DELAY = "delay"


@dataclass(frozen=True)
class InterventionAction:
    id: str
    level: InterventionLevel
    risk: float
    headline: str
    body: str
    event_id: str
    created_at: datetime
    cooldown_seconds: int = 0
    dismissed: bool = False
    overridden: bool = False


@dataclass
class InterventionState:
    pending: InterventionAction | None = None
    ambient: InterventionAction | None = None
    history: list[InterventionAction] = field(default_factory=list)


class InterventionAgent:
    def __init__(self) -> None:
        self._state = InterventionState()
        self._counter = 0

    @property
    def state(self) -> InterventionState:
        return self._state

    def decide(self, assessment: "RiskAssessment", context: "ContextSnapshot") -> None:
        event = context.triggering_event
        level = self._level_for(assessment.final_risk, event)
        if level is InterventionLevel.NONE:
            return
        self._counter += 1
        action = InterventionAction(
            id=f"i{self._counter}",
            level=level,
            risk=assessment.final_risk,
            headline=self._headline_for(level, event),
            body=self._body_for(assessment, context),
            event_id=event.id,
            created_at=datetime.now(),
            cooldown_seconds={
                InterventionLevel.FULL_SCREEN: 60,
                InterventionLevel.DELAY: 60 * 60 * 24,
            }.get(level, 0),
        )
        history = [*self._state.history, action]
        if level is InterventionLevel.BANNER:
            self._state = InterventionState(
                pending=self._state.pending,
                ambient=action,
                history=history,
            )
        else:
            self._state = InterventionState(
                pending=action,
                ambient=self._state.ambient,
                history=history,
            )

    def dismiss_ambient(self) -> None:
        cur = self._state.ambient
        if cur is None:
            return
        new_history = [
            replace(h, dismissed=True) if h.id == cur.id else h
            for h in self._state.history
        ]
        self._state = InterventionState(
            pending=self._state.pending,
            ambient=None,
            history=new_history,
        )

    def override_pending(self) -> None:
        cur = self._state.pending
        if cur is None:
            return
        new_history = [
            replace(h, overridden=True) if h.id == cur.id else h
            for h in self._state.history
        ]
        self._state = InterventionState(
            pending=None,
            ambient=self._state.ambient,
            history=new_history,
        )

    def resolve_pending(self) -> None:
        self._state = InterventionState(
            pending=None,
            ambient=self._state.ambient,
            history=self._state.history,
        )

    def reset(self) -> None:
        self._state = InterventionState()
        self._counter = 0

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _level_for(risk: float, event: ScamEvent) -> InterventionLevel:
        is_txn = isinstance(event, TransactionEvent)
        if is_txn and risk >= 0.85:
            return InterventionLevel.DELAY
        if is_txn and risk >= 0.6:
            return InterventionLevel.FULL_SCREEN
        if risk >= 0.75:
            return InterventionLevel.FULL_SCREEN
        if risk >= 0.3:
            return InterventionLevel.BANNER
        return InterventionLevel.NONE

    @staticmethod
    def _headline_for(level: InterventionLevel, event: ScamEvent) -> str:
        if isinstance(event, CallEvent):
            subject = "this call"
        elif isinstance(event, SmsEvent):
            subject = "this message"
        elif isinstance(event, ChatEvent):
            subject = "this chat"
        elif isinstance(event, TransactionEvent):
            subject = "this transfer"
        else:
            subject = "this event"
        if level is InterventionLevel.BANNER:
            return f"Something looks off about {subject}"
        if level is InterventionLevel.FULL_SCREEN:
            return f"Pause — {subject} looks like a scam"
        if level is InterventionLevel.DELAY:
            return f"24-hour hold suggested on {subject}"
        return ""

    @staticmethod
    def _body_for(a: "RiskAssessment", c: "ContextSnapshot") -> str:
        bullets: list[str] = [f"• {reason}" for reason in a.reasons[:3]]
        if c.has_recent_call and c.seconds_since_last_call < 600:
            minutes = max(1, (c.seconds_since_last_call + 59) // 60)
            bullets.append(
                f"• You got a phone call {minutes} minute(s) ago — scammers "
                "often follow up with pressure."
            )
        if c.has_recent_sms and c.seconds_since_last_sms < 600:
            bullets.append("• A suspicious message arrived recently.")
        return "\n".join(bullets)
