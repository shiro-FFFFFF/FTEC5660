"""Risk Agent — rule scorer + LLM orchestration + reviewer + fuser.

1:1 port of ``app/lib/agents/risk_agent.dart``. Each assessment records:
- the fast rule score and its contributions,
- the LLM score + tactics + reasons (if called),
- a reviewer (heuristic) second-opinion when the LLM and rule diverge,
- a consensus label, latency, and full orchestration trace.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from guardian.data.event_log import EventLog
from guardian.data.scam_db import ScamDatabase
from guardian.llm.heuristic import HeuristicLlmRuntime
from guardian.llm.runtime import LlmRuntime
from guardian.llm.tools import ToolCallStep, build_default_tool_registry
from guardian.scenarios.events import (
    CallEvent,
    ChatEvent,
    ScamEvent,
    SmsEvent,
    TransactionEvent,
)

if TYPE_CHECKING:  # pragma: no cover
    from guardian.agents.context_agent import ContextSnapshot
    from guardian.agents.intervention_agent import InterventionAgent
    from guardian.llm.tools import TraceCallback


log = logging.getLogger(__name__)


def _react_enabled() -> bool:
    """Gate LangChain agent tool use behind an opt-in env var."""
    return os.environ.get("GUARDIAN_REACT", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


@dataclass(frozen=True)
class RuleScoreContribution:
    feature: str
    value: float
    detail: str


@dataclass(frozen=True)
class RiskAssessment:
    event_id: str
    fast_risk: float
    llm_risk: float | None
    final_risk: float
    contributions: list[RuleScoreContribution]
    tactics: list[str]
    reasons: list[str]
    latency_ms: int
    source: str
    llm_confidence: float | None = None
    reviewer_risk: float | None = None
    consensus: str = "rule_only"
    tool_trace: list[ToolCallStep] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "fast_risk": self.fast_risk,
            "llm_risk": self.llm_risk,
            "llm_confidence": self.llm_confidence,
            "reviewer_risk": self.reviewer_risk,
            "final_risk": self.final_risk,
            "contributions": [
                {"feature": c.feature, "value": c.value, "detail": c.detail}
                for c in self.contributions
            ],
            "tactics": list(self.tactics),
            "reasons": list(self.reasons),
            "latency_ms": self.latency_ms,
            "source": self.source,
            "consensus": self.consensus,
            "tool_trace": [t.to_json() for t in self.tool_trace],
        }


@dataclass
class _RuleResult:
    score: float
    contributions: list[RuleScoreContribution]
    reasons: list[str]


class RiskAgent:
    def __init__(
        self,
        *,
        scam_db: ScamDatabase,
        llm: LlmRuntime,
        intervention: InterventionAgent,
        event_log: EventLog,
    ) -> None:
        self._db = scam_db
        self._llm = llm
        self._intervention = intervention
        self._log = event_log
        self._assessments: list[RiskAssessment] = []

    @property
    def assessments(self) -> list[RiskAssessment]:
        return list(self._assessments)

    def reset(self) -> None:
        self._assessments = []

    def assess(
        self,
        snapshot: ContextSnapshot,
        trace_callback: TraceCallback | None = None,
    ) -> RiskAssessment:
        started = time.monotonic()
        fast = self._rule_score(snapshot)
        event = snapshot.triggering_event
        llm_requested = self._should_call_llm(event, fast.score)
        if trace_callback is not None:
            trace_callback(
                "SYSTEM",
                "Risk assessment started",
                f"{event.kind.value} event {event.id}",
            )

        trace: list[ToolCallStep] = [
            _meta_trace(
                tool="orchestrator_plan",
                args={
                    "event_kind": event.kind.value,
                    "fast_risk": _round(fast.score),
                },
                result={
                    "llm_requested": llm_requested,
                    "priority": self._priority_for(event, fast.score),
                },
            )
        ]

        final_risk = fast.score
        llm_risk: float | None = None
        llm_confidence: float | None = None
        reviewer_risk: float | None = None
        llm_tactics: list[str] = []
        llm_reasons: list[str] = []
        llm_trace: list[ToolCallStep] = []
        consensus = "rule_only"
        source = "rule"

        if llm_requested:
            try:
                tools = (
                    build_default_tool_registry(
                        db=self._db,
                        snapshot=snapshot,
                        trace_callback=trace_callback,
                    )
                    if _react_enabled()
                    else None
                )
                out = self._llm.score_risk(
                    snapshot=snapshot,
                    rule_score=fast.score,
                    rule_contributions=fast.contributions,
                    tools=tools,
                    trace_callback=trace_callback,
                )
                llm_risk = out.risk
                llm_confidence = out.confidence
                llm_tactics = list(out.tactics)
                llm_reasons = list(out.reasons)
                llm_trace = list(out.trace)
                final_risk = _fuse(fast.score, out.risk)
                consensus = "single_agent"
                source = out.source

                if self._should_run_second_opinion(
                    event=event,
                    fast_risk=fast.score,
                    llm_risk=out.risk,
                    llm_confidence=out.confidence,
                ):
                    review_started = time.monotonic()
                    reviewer = HeuristicLlmRuntime()
                    review = reviewer.score_risk(
                        snapshot=snapshot,
                        rule_score=fast.score,
                        rule_contributions=fast.contributions,
                        tools=None,
                    )
                    review_ms = int((time.monotonic() - review_started) * 1000)
                    reviewer_risk = review.risk
                    consensus = _consensus_label(out.risk, review.risk)
                    final_risk = _fuse_with_review(
                        fast=fast.score,
                        llm=out.risk,
                        reviewer=review.risk,
                        consensus=consensus,
                    )
                    if consensus == "conflict":
                        llm_reasons = [
                            *llm_reasons,
                            "AI agents disagree. Verify with a trusted contact before acting.",
                        ]
                    trace.append(
                        _meta_trace(
                            tool="orchestrator_second_opinion",
                            args={
                                "llm_risk": _round(out.risk),
                                "llm_confidence": _round(out.confidence),
                            },
                            result={
                                "reviewer": reviewer.name,
                                "reviewer_risk": _round(review.risk),
                                "consensus": consensus,
                            },
                            latency_ms=review_ms,
                        )
                    )
                    source = f"{source}+review"
            except Exception as e:
                log.warning("[risk] LLM scoring failed: %s", e)
                if trace_callback is not None:
                    trace_callback("ERROR", "LLM scoring failed", str(e))

        trace.append(
            _meta_trace(
                tool="orchestrator_decision",
                args={
                    "fast_risk": _round(fast.score),
                    "llm_risk": _round(llm_risk) if llm_risk is not None else None,
                    "reviewer_risk": (
                        _round(reviewer_risk) if reviewer_risk is not None else None
                    ),
                },
                result={
                    "final_risk": _round(final_risk),
                    "consensus": consensus,
                    "source": source,
                },
            )
        )

        elapsed_ms = int((time.monotonic() - started) * 1000)
        assessment = RiskAssessment(
            event_id=event.id,
            fast_risk=fast.score,
            llm_risk=llm_risk,
            llm_confidence=llm_confidence,
            reviewer_risk=reviewer_risk,
            final_risk=max(0.0, min(1.0, final_risk)),
            contributions=list(fast.contributions),
            tactics=(
                llm_tactics
                if llm_tactics
                else [c.feature for c in fast.contributions]
            ),
            reasons=llm_reasons if llm_reasons else fast.reasons,
            latency_ms=elapsed_ms,
            source=source,
            consensus=consensus,
            tool_trace=[*trace, *llm_trace],
        )
        self._assessments.append(assessment)
        self._log.annotate(
            event.id,
            risk=assessment.final_risk,
            tags=list(assessment.tactics),
        )
        log.info(
            "[risk] %s/%s fast=%.2f llm=%s review=%s final=%.2f [%s] (%dms, %s)",
            event.kind.value,
            event.id,
            fast.score,
            f"{llm_risk:.2f}" if llm_risk is not None else "-",
            f"{reviewer_risk:.2f}" if reviewer_risk is not None else "-",
            assessment.final_risk,
            consensus,
            elapsed_ms,
            source,
        )
        self._intervention.decide(assessment, snapshot)
        if trace_callback is not None:
            trace_callback(
                "FINAL",
                f"Final risk {assessment.final_risk:.2f}",
                f"source={assessment.source}, consensus={assessment.consensus}",
            )
        return assessment

    # -- gating --------------------------------------------------------------

    @staticmethod
    def _should_call_llm(event: ScamEvent, fast_risk: float) -> bool:
        if isinstance(event, TransactionEvent):
            return True
        if isinstance(event, (CallEvent, ChatEvent)):
            return fast_risk >= 0.25
        if isinstance(event, SmsEvent):
            return fast_risk >= 0.3
        return False

    @staticmethod
    def _should_run_second_opinion(
        *,
        event: ScamEvent,
        fast_risk: float,
        llm_risk: float,
        llm_confidence: float,
    ) -> bool:
        if isinstance(event, TransactionEvent):
            return True
        if abs(llm_risk - fast_risk) >= 0.35:
            return True
        if llm_confidence < 0.55:
            return True
        return 0.35 <= llm_risk <= 0.8

    @staticmethod
    def _priority_for(event: ScamEvent, fast_risk: float) -> str:
        if isinstance(event, TransactionEvent):
            return "critical"
        if fast_risk >= 0.75:
            return "high"
        if fast_risk >= 0.3:
            return "medium"
        return "low"

    # -- rule scoring --------------------------------------------------------

    def _rule_score(self, s: ContextSnapshot) -> _RuleResult:
        contribs: list[RuleScoreContribution] = []
        reasons: list[str] = []
        event = s.triggering_event
        score = 0.0

        from_: str | None
        text: str | None
        if isinstance(event, CallEvent):
            from_, text = event.from_, event.transcript
        elif isinstance(event, SmsEvent):
            from_, text = event.from_, event.body
        elif isinstance(event, ChatEvent):
            from_, text = event.contact, event.body
        else:
            from_, text = None, None

        db = self._db
        if from_ is not None:
            lower_from = from_.lower()
            for bad in db.bad_numbers():
                if bad.value in lower_from:
                    score += bad.weight
                    contribs.append(
                        RuleScoreContribution(
                            feature="bad_number",
                            value=bad.weight,
                            detail=f"Sender {from_} on blocklist ({bad.tag})",
                        )
                    )
                    reasons.append("Sender number is on a scam blocklist.")

        if text is not None:
            lower = text.lower()
            for d in db.bad_domains():
                if d.value in lower:
                    score += d.weight
                    contribs.append(
                        RuleScoreContribution(
                            feature="bad_domain",
                            value=d.weight,
                            detail=f"Message contains phishing domain {d.value}",
                        )
                    )
                    reasons.append("Message contains a known phishing link.")
            kw_sum = 0.0
            hits: list[str] = []
            for k in db.keywords():
                if k.value in lower:
                    kw_sum += k.weight
                    hits.append(f'"{k.value}" ({k.tag})')
            if hits:
                bounded = max(0.0, min(0.9, kw_sum * 0.5))
                score += bounded
                suffix = ", ..." if len(hits) > 4 else ""
                contribs.append(
                    RuleScoreContribution(
                        feature="scam_keywords",
                        value=bounded,
                        detail=(
                            f"Matched {len(hits)} keyword(s): "
                            f"{', '.join(hits[:4])}{suffix}"
                        ),
                    )
                )
                reasons.append("Language matches common scam scripts.")

        if s.prior_max_risk >= 0.5 and not isinstance(event, TransactionEvent):
            bump = max(0.0, min(0.25, (s.prior_max_risk - 0.3) * 0.5))
            score += bump
            contribs.append(
                RuleScoreContribution(
                    feature="scam_thread",
                    value=bump,
                    detail=(
                        "Earlier events in this window scored "
                        f"{int(s.prior_max_risk * 100)}%"
                    ),
                )
            )
            reasons.append("This is part of an ongoing suspicious conversation.")

        if isinstance(event, TransactionEvent):
            txn = 0.0
            if event.new_recipient:
                txn += 0.35
                contribs.append(
                    RuleScoreContribution(
                        feature="new_recipient",
                        value=0.35,
                        detail="First-time payee",
                    )
                )
            if event.amount_hkd >= 30_000:
                txn += 0.25
                contribs.append(
                    RuleScoreContribution(
                        feature="large_amount",
                        value=0.25,
                        detail=f"{event.amount_hkd:.0f} HKD above daily pattern",
                    )
                )
            elif event.amount_hkd >= 10_000:
                txn += 0.1
                contribs.append(
                    RuleScoreContribution(
                        feature="elevated_amount",
                        value=0.1,
                        detail=f"{event.amount_hkd:.0f} HKD above typical",
                    )
                )
            if s.has_recent_call and s.seconds_since_last_call < 300:
                txn += 0.25
                contribs.append(
                    RuleScoreContribution(
                        feature="temporal_call",
                        value=0.25,
                        detail=f"Call {s.seconds_since_last_call}s ago",
                    )
                )
                reasons.append("Large transfer initiated right after a phone call.")
            if s.has_recent_sms and s.seconds_since_last_sms < 600:
                txn += 0.15
                contribs.append(
                    RuleScoreContribution(
                        feature="temporal_sms",
                        value=0.15,
                        detail=f"SMS {s.seconds_since_last_sms}s ago",
                    )
                )
            score += txn
            if event.new_recipient and event.amount_hkd >= 10_000:
                reasons.append("Large transfer to a new recipient.")

        clamped = max(0.0, min(1.0, score))
        if not reasons:
            reasons.append("No rule triggered.")
        return _RuleResult(score=clamped, contributions=contribs, reasons=reasons)


# -- pure helpers -----------------------------------------------------------


def _round(v: float) -> float:
    return float(f"{v:.3f}")


def _fuse(fast: float, llm: float) -> float:
    return max(fast, 0.6 * llm + 0.4 * fast)


def _fuse_with_review(
    *,
    fast: float,
    llm: float,
    reviewer: float,
    consensus: str,
) -> float:
    base = _fuse(fast, llm)
    blended = 0.5 * llm + 0.3 * reviewer + 0.2 * fast
    if consensus == "conflict":
        conservative = 0.25 * llm + 0.55 * reviewer + 0.2 * fast
        return max(fast, reviewer, conservative)
    return max(base, blended)


def _consensus_label(llm_risk: float, reviewer_risk: float) -> str:
    gap = abs(llm_risk - reviewer_risk)
    if gap <= 0.15:
        return "aligned"
    if gap <= 0.35:
        return "mixed"
    return "conflict"


def _meta_trace(
    *,
    tool: str,
    args: dict[str, Any],
    result: dict[str, Any],
    latency_ms: int = 0,
) -> ToolCallStep:
    return ToolCallStep(tool=tool, args=args, result=result, latency_ms=latency_ms)
