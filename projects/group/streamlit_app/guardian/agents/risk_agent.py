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
from guardian.data.scam_signals import ScamDbProvider, ScamSignalProvider
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
        scam_db: ScamDatabase | None = None,
        scam_signals: ScamSignalProvider | None = None,
        llm: LlmRuntime,
        intervention: InterventionAgent,
        event_log: EventLog,
    ) -> None:
        if scam_signals is None:
            if scam_db is None:
                raise TypeError("RiskAgent requires scam_db or scam_signals")
            scam_signals = ScamDbProvider(scam_db)

        self._signals = scam_signals
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
        if trace_callback is not None:
            event = snapshot.triggering_event
            trace_callback(
                "SYSTEM",
                "Risk assessment started",
                f"{event.kind.value} event {event.id}",
            )
            trace_callback(
                "THINKING",
                "Computing fast-rule score from known scam signals",
                None,
            )
        fast = self._rule_score(snapshot)
        event = snapshot.triggering_event
        llm_requested = self._should_call_llm(event, fast.score)
        if trace_callback is not None:
            trace_callback(
                "OBSERVATION",
                f"Fast-rule score computed: {fast.score:.2f}",
                "; ".join(reason for reason in fast.reasons[:3]) or "No rule triggered.",
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
                        provider=self._signals,
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
                    if trace_callback is not None:
                        trace_callback(
                            "THINKING",
                            "Running reviewer second opinion on the current assessment",
                            None,
                        )
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
                    if trace_callback is not None:
                        trace_callback(
                            "OBSERVATION",
                            f"Reviewer returned risk {review.risk:.2f}",
                            f"consensus={consensus}",
                        )
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
        self._maybe_update_scamdatabase_number(
            event=event,
            assessment=assessment,
            trace_callback=trace_callback,
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

    def _maybe_update_scamdatabase_number(
        self,
        *,
        event: ScamEvent,
        assessment: RiskAssessment,
        trace_callback: TraceCallback | None,
    ) -> None:
        """Auto-append unknown high-risk phone senders into runtime scam DB."""
        if not isinstance(event, (CallEvent, SmsEvent)):
            return
        if assessment.final_risk < 0.9:
            return
        if assessment.consensus == "conflict":
            return

        sender = event.from_.strip()
        normalized_sender = _normalize_phone_like(sender)
        if not normalized_sender:
            return

        try:
            lookup = self._signals.lookup_number(sender)
        except Exception as e:
            log.warning("[risk] lookup before runtime update failed: %s", e)
            return
        if bool(lookup.get("hit")):
            return

        reason = (
            assessment.reasons[0]
            if assessment.reasons
            else "high_risk_auto_detected"
        )
        try:
            out = self._signals.update_scamdatabase_number(
                number=sender,
                risk=assessment.final_risk,
                reason=reason[:240],
                event_id=assessment.event_id,
                source_model=assessment.source,
                weight=max(0.6, min(0.95, assessment.final_risk)),
                tag="auto_detected",
            )
            status = str(out.get("status", "unknown"))
            log.info(
                "[risk] runtime scam-db update %s for sender=%s event=%s",
                status,
                sender,
                assessment.event_id,
            )
            if trace_callback is not None:
                trace_callback(
                    "SYSTEM",
                    "Runtime scam DB update attempted",
                    f"sender={sender} status={status}",
                )
        except Exception as e:
            log.warning("[risk] runtime scam-db update failed: %s", e)
            if trace_callback is not None:
                trace_callback(
                    "ERROR",
                    "Runtime scam DB update failed",
                    str(e),
                )

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

        provider = self._signals
        if from_ is not None:
            lookup = provider.lookup_number(from_)
            if bool(lookup.get("hit")):
                try:
                    weight = float(lookup.get("weight", 0.5))
                except (TypeError, ValueError):
                    weight = 0.5
                tag = str(lookup.get("tag", "unknown"))
                score += weight
                contribs.append(
                    RuleScoreContribution(
                        feature="bad_number",
                        value=weight,
                        detail=f"Sender {from_} on blocklist ({tag})",
                    )
                )
                reasons.append("Sender number is on a scam blocklist.")

        if text is not None:
            domain_out = provider.check_domain(text)
            matches = domain_out.get("matches")
            if bool(domain_out.get("hit")) and isinstance(matches, list):
                any_domain = False
                for m in matches:
                    if not isinstance(m, dict):
                        continue
                    domain = str(m.get("domain", "")).strip()
                    if not domain:
                        continue
                    try:
                        weight = float(m.get("weight", 0.5))
                    except (TypeError, ValueError):
                        weight = 0.5
                    score += weight
                    any_domain = True
                    contribs.append(
                        RuleScoreContribution(
                            feature="bad_domain",
                            value=weight,
                            detail=f"Message contains phishing domain {domain}",
                        )
                    )
                if any_domain:
                    reasons.append("Message contains a known phishing link.")

            kw_out = provider.search_keywords(text)
            hits_raw = kw_out.get("hits")
            kw_sum = 0.0
            hits: list[str] = []
            if isinstance(hits_raw, list):
                for h in hits_raw:
                    if not isinstance(h, dict):
                        continue
                    keyword = str(h.get("keyword", "")).strip()
                    if not keyword:
                        continue
                    tag = str(h.get("tag", "unknown"))
                    try:
                        w = float(h.get("weight", 0.0))
                    except (TypeError, ValueError):
                        w = 0.0
                    kw_sum += w
                    hits.append(f'"{keyword}" ({tag})')

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
            beneficiary_out = provider.check_beneficiary_for_bank_transfer(
                event.to_name,
                event.to_account,
            )
            name_check = str(
                beneficiary_out.get("name_account_check", "unknown")
            ).strip()
            risk_status = str(
                beneficiary_out.get("reported_risk_status", "unknown")
            ).strip()

            if name_check == "mismatch":
                txn += 0.35
                contribs.append(
                    RuleScoreContribution(
                        feature="beneficiary_name_mismatch",
                        value=0.35,
                        detail="Bank transfer beneficiary name mismatches registry",
                    )
                )
                reasons.append("Recipient name does not match the beneficiary account.")
            elif name_check == "close_match":
                txn += 0.12
                contribs.append(
                    RuleScoreContribution(
                        feature="beneficiary_name_close_match",
                        value=0.12,
                        detail="Bank transfer beneficiary name is only a close match",
                    )
                )
                reasons.append("Recipient name only partially matches the beneficiary account.")

            if risk_status == "reported":
                txn += 0.25
                contribs.append(
                    RuleScoreContribution(
                        feature="beneficiary_prior_report",
                        value=0.25,
                        detail="Beneficiary account has prior active bank-transfer risk reports",
                    )
                )
                reasons.append("Beneficiary account has prior risk reports.")
            elif risk_status == "high_risk":
                txn += 0.45
                contribs.append(
                    RuleScoreContribution(
                        feature="beneficiary_high_risk",
                        value=0.45,
                        detail="Beneficiary account is marked high risk for bank transfers",
                    )
                )
                reasons.append("Beneficiary account is already marked high risk.")
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


def _normalize_phone_like(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    normalized = "".join(ch for ch in value if ch.isdigit() or ch == "+")
    digit_count = sum(ch.isdigit() for ch in normalized)
    if digit_count < 7:
        return ""
    if any(ch.isalpha() for ch in value):
        return ""
    return normalized
