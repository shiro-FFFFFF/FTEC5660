"""Deterministic keyword-based fallback runtime.

Port of ``app/lib/llm/heuristic_runtime.dart``. Always available; used
either as the Smart runtime's fallback or as the reviewer second-opinion.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from guardian.llm.runtime import LlmRiskOutput, LlmRuntime
from guardian.scenarios.events import (
    CallEvent,
    ChatEvent,
    SmsEvent,
    TransactionEvent,
)

if TYPE_CHECKING:  # pragma: no cover
    from guardian.agents.context_agent import ContextSnapshot
    from guardian.agents.risk_agent import RuleScoreContribution
    from guardian.llm.tools import ToolRegistry, TraceCallback


class HeuristicLlmRuntime(LlmRuntime):
    @property
    def ready(self) -> bool:
        return True

    @property
    def name(self) -> str:
        return "heuristic"

    def warmup(self) -> None:
        return None

    def score_risk(
        self,
        *,
        snapshot: ContextSnapshot,
        rule_score: float,
        rule_contributions: list[RuleScoreContribution],
        tools: ToolRegistry | None,
        trace_callback: TraceCallback | None = None,
    ) -> LlmRiskOutput:
        if trace_callback is not None:
            trace_callback("THINKING", "Heuristic fallback is scoring risk", None)
        event = snapshot.triggering_event
        tactics: set[str] = set()
        reasons: list[str] = []
        text: str | None = None
        if isinstance(event, CallEvent):
            text = event.transcript
        elif isinstance(event, SmsEvent) or isinstance(event, ChatEvent):
            text = event.body
        elif isinstance(event, TransactionEvent):
            text = None

        lift = 0.0
        if text is not None:
            lower = text.lower()
            if "police" in lower or "arrest" in lower or "cybercrime" in lower:
                tactics.add("authority_impersonation")
                reasons.append("Caller claims to be an authority.")
                lift += 0.2
            if "holding account" in lower or "transfer your funds" in lower:
                tactics.add("payment_redirect")
                reasons.append('Asks you to move money to a "safe" account.')
                lift += 0.3
            if (
                "don't tell" in lower
                or "do not tell" in lower
                or "confidential" in lower
            ):
                tactics.add("isolation")
                reasons.append("Tells you to keep this secret.")
                lift += 0.2
            if "guaranteed" in lower or "vip tip" in lower:
                tactics.add("investment_scam")
                reasons.append('Offers "guaranteed" or insider returns.')
                lift += 0.2
            if "customs" in lower or "parcel" in lower:
                tactics.add("courier_scam")
                reasons.append("Uses a courier / customs pretext.")
                lift += 0.15
            if (
                "urgent" in lower
                or "immediately" in lower
                or "final notice" in lower
                or "hurry" in lower
            ):
                tactics.add("urgency")
                reasons.append("Creates strong time pressure.")
                lift += 0.1

        if isinstance(event, TransactionEvent):
            if snapshot.has_recent_call and snapshot.seconds_since_last_call < 600:
                tactics.add("temporal_correlation")
                reasons.append("Transfer attempted right after a suspicious call.")
                lift += 0.2
            if event.new_recipient and event.amount_hkd >= 30_000:
                tactics.add("atypical_payee")
                reasons.append("Large transfer to a first-time payee.")
                lift += 0.15

        risk = max(0.0, min(1.0, rule_score * 0.6 + lift))
        if trace_callback is not None:
            trace_callback(
                "FINAL",
                f"Heuristic risk {risk:.2f}",
                "; ".join(reasons or ["Nothing obvious, erring low."]),
            )
        return LlmRiskOutput(
            risk=risk,
            tactics=sorted(tactics),
            reasons=reasons or ["Nothing obvious, erring low."],
            confidence=0.4,
            source="heuristic",
        )

    def explain(
        self,
        *,
        snapshot: ContextSnapshot,
        final_risk: float,
    ) -> str:
        if final_risk >= 0.85:
            return (
                "This looks like a classic scam pattern. Please pause and verify "
                "with someone you trust before continuing."
            )
        if final_risk >= 0.6:
            return (
                "Several signs here match common scam scripts. Take a moment "
                "before acting on this request."
            )
        if final_risk >= 0.3:
            return (
                "Something looks slightly off — worth a second look, but no "
                "immediate danger."
            )
        return "No suspicious signals detected."
