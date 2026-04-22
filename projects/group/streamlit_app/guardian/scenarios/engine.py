"""Scenario playback engine — real-time timers under Streamlit's rerun model.

1:1 port of ``app/lib/scenarios/scenario_engine.dart`` with one twist: the
"Timer" loop becomes a ``poll()`` method the UI calls on every rerun
(driven by ``streamlit-autorefresh``). Events whose wall-clock offset has
elapsed are ingested into the Context agent; transactions are *not*
auto-ingested — they're surfaced as ``pending_user_transaction`` so the
demo operator drives the Bank → Transfer flow manually.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from guardian.paths import SCENARIOS_DIR
from guardian.scenarios.events import TransactionEvent, event_from_json

if TYPE_CHECKING:  # pragma: no cover
    from guardian.agents.context_agent import ContextAgent


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScheduledEvent:
    offset: timedelta
    payload: dict[str, Any]
    index: int


@dataclass(frozen=True)
class Scenario:
    id: str
    label: str
    category: str
    events: list[ScheduledEvent]
    expected: dict[str, Any]

    @classmethod
    def from_json(cls, j: dict[str, Any]) -> "Scenario":
        raw_events = list(j.get("events") or [])
        events = [
            ScheduledEvent(
                offset=timedelta(seconds=int(e["t_seconds"])),
                payload=e,
                index=i,
            )
            for i, e in enumerate(raw_events)
        ]
        return cls(
            id=str(j["id"]),
            label=str(j.get("label", j["id"])),
            category=str(j.get("category", "unknown")),
            events=events,
            expected=dict(j.get("expected") or {}),
        )


@dataclass
class ScenarioState:
    playing: Scenario | None = None
    progress: float = 0.0
    completed: list[str] = field(default_factory=list)
    pending_user_transaction: TransactionEvent | None = None


class ScenarioEngine:
    def __init__(
        self,
        *,
        context: "ContextAgent",
        scenarios_dir: Path = SCENARIOS_DIR,
    ) -> None:
        self._context = context
        self._dir = scenarios_dir
        self._cache: dict[str, Scenario] = {}
        self._loaded_index = False

        self._state = ScenarioState()
        # Playback bookkeeping.
        self._started_monotonic: float | None = None
        self._started_wall: datetime | None = None
        self._fired: set[int] = set()
        self._completed_at: float | None = None
        self._effective_offsets_seconds: dict[int, float] = {}

    # -- state accessors -----------------------------------------------------

    @property
    def state(self) -> ScenarioState:
        return self._state

    def is_playing(self) -> bool:
        return self._state.playing is not None

    def has_pending_user_transaction(self) -> bool:
        return self._state.pending_user_transaction is not None

    # -- catalog -------------------------------------------------------------

    def list_scenarios(self) -> list[Scenario]:
        self._ensure_index()
        return sorted(self._cache.values(), key=lambda s: s.id)

    def load(self, scenario_id: str) -> Scenario | None:
        self._ensure_index()
        return self._cache.get(scenario_id)

    def _ensure_index(self) -> None:
        if self._loaded_index:
            return
        self._loaded_index = True
        if not self._dir.exists():
            log.warning("scenarios dir missing: %s", self._dir)
            return
        for path in sorted(self._dir.glob("*.json")):
            try:
                raw = path.read_text(encoding="utf-8")
                scenario = Scenario.from_json(json.loads(raw))
                self._cache[scenario.id] = scenario
            except Exception as e:
                log.warning("failed to parse scenario %s: %s", path, e)

    # -- playback ------------------------------------------------------------

    def play(self, scenario_id: str) -> None:
        scenario = self.load(scenario_id)
        if scenario is None:
            log.warning("Scenario not found: %s", scenario_id)
            return
        self._state = ScenarioState(playing=scenario, progress=0.0, completed=self._state.completed)
        self._started_monotonic = time.monotonic()
        self._started_wall = datetime.now()
        self._fired = set()
        self._completed_at = None
        self._effective_offsets_seconds = _build_effective_offsets_seconds(scenario.events)
        log.info("[scenario] ▶ %s — %s", scenario.id, scenario.label)

    def poll(self) -> None:
        """Fire events whose offset has elapsed. Call on every rerun."""
        scenario = self._state.playing
        if scenario is None or self._started_monotonic is None or self._started_wall is None:
            return
        elapsed = time.monotonic() - self._started_monotonic
        effective_total_seconds = max(self._effective_offsets_seconds.values(), default=0.0)
        total_seconds = max(
            (e.offset.total_seconds() for e in scenario.events),
            default=0.0,
        )
        for scheduled in scenario.events:
            if scheduled.index in self._fired:
                continue
            effective_offset_seconds = self._effective_offsets_seconds.get(
                scheduled.index,
                scheduled.offset.total_seconds(),
            )
            if effective_offset_seconds > elapsed:
                continue
            self._fired.add(scheduled.index)
            ts = self._started_wall + scheduled.offset
            event_id = f"{scenario.id}_{scheduled.index}"
            event = event_from_json(scheduled.payload, ts, event_id)
            if isinstance(event, TransactionEvent):
                log.info(
                    "[scenario] @%ds ⏸ await user txn (HKD %.0f → %s)",
                    int(scheduled.offset.total_seconds()),
                    event.amount_hkd,
                    event.to_name,
                )
                self._state = ScenarioState(
                    playing=self._state.playing,
                    progress=self._state.progress,
                    completed=self._state.completed,
                    pending_user_transaction=event,
                )
            else:
                log.info(
                    "[scenario] @%ds → %s",
                    int(scheduled.offset.total_seconds()),
                    event.kind.value,
                )
                self._context.ingest(event)
            progress = (
                (effective_offset_seconds + 1) / (effective_total_seconds + 1)
                if effective_total_seconds
                else 1.0
            )
            self._state = ScenarioState(
                playing=self._state.playing,
                progress=max(self._state.progress, min(1.0, progress)),
                completed=self._state.completed,
                pending_user_transaction=self._state.pending_user_transaction,
            )
        if len(self._fired) == len(scenario.events):
            # Completed all scheduled events. Mark completion + auto-clear
            # after a short grace period if no transaction is pending.
            if self._completed_at is None:
                self._completed_at = time.monotonic()
                self._state = ScenarioState(
                    playing=self._state.playing,
                    progress=1.0,
                    completed=(
                        [*self._state.completed, scenario.id]
                        if scenario.id not in self._state.completed
                        else self._state.completed
                    ),
                    pending_user_transaction=self._state.pending_user_transaction,
                )
            elif (
                time.monotonic() - self._completed_at >= 2.0
                and self._state.pending_user_transaction is None
            ):
                self._state = ScenarioState(
                    playing=None,
                    progress=0.0,
                    completed=self._state.completed,
                )
                self._started_monotonic = None
                self._started_wall = None

    def resolve_pending_transaction(self) -> None:
        """Called after the user submits / cancels the Transfer form."""
        self._state = ScenarioState(
            playing=self._state.playing,
            progress=self._state.progress,
            completed=self._state.completed,
            pending_user_transaction=None,
        )
        if self._state.progress >= 1.0:
            self._state = ScenarioState(
                playing=None,
                progress=0.0,
                completed=self._state.completed,
            )
            self._started_monotonic = None
            self._started_wall = None
            self._effective_offsets_seconds = {}

    def stop(self) -> None:
        self._state = ScenarioState(completed=self._state.completed)
        self._started_monotonic = None
        self._started_wall = None
        self._fired = set()
        self._completed_at = None
        self._effective_offsets_seconds = {}


def _build_effective_offsets_seconds(events: list[ScheduledEvent]) -> dict[int, float]:
    max_idle_s = _scenario_max_idle_s()
    if max_idle_s is None:
        return {event.index: event.offset.total_seconds() for event in events}

    effective_offsets: dict[int, float] = {}
    previous_actual = 0.0
    previous_effective = 0.0
    for event in events:
        actual = event.offset.total_seconds()
        gap = max(0.0, actual - previous_actual)
        effective_gap = min(gap, max_idle_s)
        previous_effective += effective_gap
        effective_offsets[event.index] = previous_effective
        previous_actual = actual
    return effective_offsets


def _scenario_max_idle_s() -> float | None:
    raw = os.environ.get("GUARDIAN_SCENARIO_MAX_IDLE_S", "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None
