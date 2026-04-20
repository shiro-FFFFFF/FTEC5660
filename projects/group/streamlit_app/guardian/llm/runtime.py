"""LLM runtime protocol + ``SmartLlmRuntime`` delegator.

Port of ``app/lib/llm/llm_runtime.dart``. Concrete runtimes live in
``heuristic.py`` and ``ollama.py``. :class:`SmartLlmRuntime` prefers the
configured primary (Ollama) and falls back to the heuristic on any
failure so the UI never deadlocks on a missing local model.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from guardian.agents.context_agent import ContextSnapshot
    from guardian.agents.risk_agent import RuleScoreContribution
    from guardian.llm.tools import ToolCallStep, ToolRegistry, TraceCallback


log = logging.getLogger(__name__)


class PrimaryHealth(StrEnum):
    UNKNOWN = "unknown"       # never probed
    HEALTHY = "healthy"       # last call succeeded
    COOLDOWN = "cooldown"     # recent failure; retry after cooldown expires
    UNREACHABLE = "unreachable"  # reachability probe never succeeded


# Exponential-backoff schedule (seconds). Index = consecutive failures.
_COOLDOWN_STEPS = (30.0, 60.0, 120.0, 300.0)


@dataclass(frozen=True)
class LlmRiskOutput:
    risk: float
    tactics: list[str]
    reasons: list[str]
    confidence: float
    source: str
    trace: list[ToolCallStep] = field(default_factory=list)


class LlmRuntime(ABC):
    @abstractmethod
    def score_risk(
        self,
        *,
        snapshot: ContextSnapshot,
        rule_score: float,
        rule_contributions: list[RuleScoreContribution],
        tools: ToolRegistry | None,
        trace_callback: TraceCallback | None = None,
    ) -> LlmRiskOutput: ...

    @abstractmethod
    def explain(
        self,
        *,
        snapshot: ContextSnapshot,
        final_risk: float,
    ) -> str: ...

    @abstractmethod
    def warmup(self) -> None: ...

    @property
    @abstractmethod
    def ready(self) -> bool: ...

    @property
    @abstractmethod
    def name(self) -> str: ...


class SmartLlmRuntime(LlmRuntime):
    """Prefer the primary runtime; fall back to heuristic on failure.

    A single timeout used to permanently demote the session to heuristic.
    Now the primary enters a short cooldown after a failure and is
    retried on the next scoring call; so transient Ollama hiccups
    degrade gracefully without sticking the UI on "LLM: heuristic".
    """

    def __init__(
        self,
        primary: LlmRuntime | None = None,
        fallback: LlmRuntime | None = None,
    ) -> None:
        # Imported here to break cycles.
        from guardian.llm.heuristic import HeuristicLlmRuntime
        from guardian.llm.ollama import OllamaLlmRuntime

        self._primary: LlmRuntime = primary or OllamaLlmRuntime()
        self._fallback: LlmRuntime = fallback or HeuristicLlmRuntime()

        # Health state
        self._health: PrimaryHealth = PrimaryHealth.UNKNOWN
        self._consecutive_failures: int = 0
        self._cooldown_until: float = 0.0  # monotonic
        self._last_error: str | None = None

    # -- public surface ------------------------------------------------------

    @property
    def ready(self) -> bool:
        return self._health is not PrimaryHealth.UNKNOWN

    @property
    def name(self) -> str:
        if self._health is PrimaryHealth.HEALTHY:
            return self._primary.name
        if self._health is PrimaryHealth.COOLDOWN:
            return f"{self._fallback.name} (primary cooling down)"
        if self._health is PrimaryHealth.UNREACHABLE:
            return self._fallback.name
        return "detecting…"

    @property
    def health(self) -> PrimaryHealth:
        return self._health

    @property
    def primary_name(self) -> str:
        return self._primary.name

    @property
    def fallback_name(self) -> str:
        return self._fallback.name

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def cooldown_remaining(self) -> float:
        if self._health is not PrimaryHealth.COOLDOWN:
            return 0.0
        return max(0.0, self._cooldown_until - time.monotonic())

    @property
    def active(self) -> LlmRuntime:
        return (
            self._primary
            if self._health is PrimaryHealth.HEALTHY
            else self._fallback
        )

    def warmup(self) -> None:
        self._probe_and_warmup()

    def probe(self) -> None:
        """Check primary reachability without forcing a model generation."""
        primary = self._primary
        reach = getattr(primary, "is_reachable", None)
        if not callable(reach):
            self._record_success()
            return
        try:
            if bool(reach()):
                self._record_success()
            else:
                log.info("[llm] primary not reachable; using %s", self._fallback.name)
                self._health = PrimaryHealth.UNREACHABLE
        except Exception as e:
            log.warning("[llm] reachability check failed: %s", e)
            self._health = PrimaryHealth.UNREACHABLE
            self._last_error = str(e)

    def force_retry(self) -> None:
        """Clear any cooldown so the next call tries primary again."""
        if self._health is PrimaryHealth.COOLDOWN:
            self._health = PrimaryHealth.UNKNOWN
            self._cooldown_until = 0.0
            self._consecutive_failures = 0

    # -- orchestration -------------------------------------------------------

    def score_risk(
        self,
        *,
        snapshot: ContextSnapshot,
        rule_score: float,
        rule_contributions: list[RuleScoreContribution],
        tools: ToolRegistry | None,
        trace_callback: TraceCallback | None = None,
    ) -> LlmRiskOutput:
        if self._use_primary():
            try:
                out = self._primary.score_risk(
                    snapshot=snapshot,
                    rule_score=rule_score,
                    rule_contributions=rule_contributions,
                    tools=tools,
                    trace_callback=trace_callback,
                )
                self._record_success()
                return out
            except Exception as e:
                self._record_failure(f"score_risk: {e}")
                if trace_callback is not None:
                    trace_callback("ERROR", "Primary LLM failed", str(e))
        return self._fallback.score_risk(
            snapshot=snapshot,
            rule_score=rule_score,
            rule_contributions=rule_contributions,
            tools=tools,
            trace_callback=trace_callback,
        )

    def explain(
        self,
        *,
        snapshot: ContextSnapshot,
        final_risk: float,
    ) -> str:
        if self._use_primary():
            try:
                out = self._primary.explain(snapshot=snapshot, final_risk=final_risk)
                self._record_success()
                return out
            except Exception as e:
                self._record_failure(f"explain: {e}")
        return self._fallback.explain(snapshot=snapshot, final_risk=final_risk)

    # -- internal state machine ---------------------------------------------

    def _use_primary(self) -> bool:
        """Decide whether to try primary for this call."""
        if self._health is PrimaryHealth.UNREACHABLE:
            return False
        if self._health is PrimaryHealth.UNKNOWN:
            return self._probe_and_warmup()
        if self._health is PrimaryHealth.HEALTHY:
            return True
        # COOLDOWN — retry once cooldown window expires.
        if time.monotonic() >= self._cooldown_until:
            log.info("[llm] cooldown elapsed — retrying primary")
            self._health = PrimaryHealth.UNKNOWN
            return True
        return False

    def _probe_and_warmup(self) -> bool:
        primary = self._primary
        reach = getattr(primary, "is_reachable", None)
        if callable(reach):
            try:
                if not bool(reach()):
                    log.info("[llm] primary not reachable; using %s", self._fallback.name)
                    self._health = PrimaryHealth.UNREACHABLE
                    return False
            except Exception as e:
                log.warning("[llm] reachability check failed: %s", e)
                self._health = PrimaryHealth.UNREACHABLE
                self._last_error = str(e)
                return False
        try:
            primary.warmup()
        except Exception as e:
            log.warning("[llm] warmup failed: %s", e)
            self._record_failure(f"warmup: {e}")
            return False
        self._record_success()
        log.info("[llm] primary healthy: %s", primary.name)
        return True

    def _record_success(self) -> None:
        self._health = PrimaryHealth.HEALTHY
        self._consecutive_failures = 0
        self._cooldown_until = 0.0
        self._last_error = None

    def _record_failure(self, detail: str) -> None:
        self._last_error = detail
        self._consecutive_failures += 1
        step = _COOLDOWN_STEPS[
            min(self._consecutive_failures - 1, len(_COOLDOWN_STEPS) - 1)
        ]
        self._cooldown_until = time.monotonic() + step
        self._health = PrimaryHealth.COOLDOWN
        log.warning(
            "[llm] primary failed (%s); cooldown %.0fs (failure #%d)",
            detail,
            step,
            self._consecutive_failures,
        )
