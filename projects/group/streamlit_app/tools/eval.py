"""Headless scenario evaluator — mirrors ``app/tool/eval.dart``.

Runs every scenario in ``scenarios/`` through a fresh Guardian pipeline,
compares the max risk and top intervention level to the scenario's
``expected`` block, and prints a pass/fail table + JSON report.

Usage::

    python -m streamlit_app.tools.eval            # heuristic-only (default)
    python -m streamlit_app.tools.eval --ollama   # use SmartLlmRuntime (Ollama + fallback)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Make ``guardian`` importable when run as ``python tools/eval.py``
_SELF = Path(__file__).resolve()
sys.path.insert(0, str(_SELF.parents[1]))  # streamlit_app/

from guardian.agents.context_agent import ContextAgent  # noqa: E402
from guardian.agents.intervention_agent import (  # noqa: E402
    InterventionAgent,
    InterventionLevel,
)
from guardian.agents.risk_agent import RiskAgent  # noqa: E402
from guardian.data.event_log import EventLog  # noqa: E402
from guardian.data.scam_db import ScamDatabase  # noqa: E402
from guardian.llm.heuristic import HeuristicLlmRuntime  # noqa: E402
from guardian.llm.runtime import LlmRuntime, SmartLlmRuntime  # noqa: E402
from guardian.paths import REPO_ROOT, REPORTS_DIR, SCAM_DB_CSV, SCENARIOS_DIR  # noqa: E402
from guardian.scenarios.events import event_from_json  # noqa: E402

from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402


log = logging.getLogger("eval")


@dataclass
class EvalRow:
    id: str
    category: str
    max_risk: float
    expected_min: float
    expected_max: float
    actual_intervention: str
    expected_intervention: str
    pass_: bool
    assessments: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "max_risk": self.max_risk,
            "expected_min": self.expected_min,
            "expected_max": self.expected_max,
            "actual_intervention": self.actual_intervention,
            "expected_intervention": self.expected_intervention,
            "pass": self.pass_,
            "assessments": self.assessments,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Guardian scenario evaluator")
    parser.add_argument(
        "--ollama",
        action="store_true",
        help="Use the Smart runtime (Ollama + heuristic fallback). Default is heuristic-only.",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        help="Run only the given scenario id(s). Default: all.",
    )
    args = parser.parse_args(argv)

    db = ScamDatabase.from_csv(SCAM_DB_CSV.read_text(encoding="utf-8"))

    files = sorted(SCENARIOS_DIR.glob("*.json"))
    if args.scenario:
        wanted = set(args.scenario)
        files = [
            f
            for f in files
            if json.loads(f.read_text(encoding="utf-8"))["id"] in wanted
        ]
        if not files:
            print(f"No scenarios match: {args.scenario}", file=sys.stderr)
            return 2

    rows: list[EvalRow] = []
    for f in files:
        raw = json.loads(f.read_text(encoding="utf-8"))
        rows.append(_run_scenario(raw, db, use_ollama=args.ollama))

    _print_table(rows)
    _write_json(rows, used_ollama=args.ollama)
    passed = sum(1 for r in rows if r.pass_)
    return 0 if passed == len(rows) else 1


def _run_scenario(
    scenario: dict[str, Any],
    db: ScamDatabase,
    *,
    use_ollama: bool,
) -> EvalRow:
    # Fresh pipeline per scenario so state never leaks.
    event_log = EventLog()
    intervention = InterventionAgent()
    llm: LlmRuntime = SmartLlmRuntime() if use_ollama else HeuristicLlmRuntime()
    risk = RiskAgent(
        scam_db=db, llm=llm, intervention=intervention, event_log=event_log
    )
    context = ContextAgent(event_log=event_log, risk_agent=risk)

    base = datetime.now()
    for i, raw_event in enumerate(scenario["events"]):
        ts = base + timedelta(seconds=int(raw_event["t_seconds"]))
        event = event_from_json(raw_event, ts, f"{scenario['id']}_{i}")
        context.ingest(event)

    assessments = risk.assessments
    max_risk = max((a.final_risk for a in assessments), default=0.0)
    actions = intervention.state.history
    top_level = (
        max(actions, key=lambda a: list(InterventionLevel).index(a.level)).level
        if actions
        else InterventionLevel.NONE
    )

    expected = scenario.get("expected") or {}
    exp_min = float(expected.get("min_risk", 0.0))
    exp_max = float(expected.get("max_risk", 1.0))
    exp_intervention = str(expected.get("intervention", "none"))
    pass_ = (
        (exp_min - 0.05) <= max_risk <= (exp_max + 0.05)
        and _compat(top_level, exp_intervention)
    )
    return EvalRow(
        id=str(scenario["id"]),
        category=str(scenario.get("category", "unknown")),
        max_risk=max_risk,
        expected_min=exp_min,
        expected_max=exp_max,
        actual_intervention=top_level.value,
        expected_intervention=exp_intervention,
        pass_=pass_,
        assessments=[a.to_json() for a in assessments],
    )


def _compat(actual: InterventionLevel, expected: str) -> bool:
    if expected == "none":
        return actual is InterventionLevel.NONE
    if expected == "banner":
        return actual is InterventionLevel.BANNER
    if expected == "manual_review":
        return actual is InterventionLevel.MANUAL_REVIEW
    if expected == "full_screen":
        return actual in (InterventionLevel.FULL_SCREEN, InterventionLevel.DELAY)
    if expected == "full_screen_delay":
        return actual is InterventionLevel.DELAY
    return True


def _print_table(rows: list[EvalRow]) -> None:
    console = Console()
    table = Table(title="Guardian scenario evaluation", show_lines=False)
    table.add_column("scenario", style="bold")
    table.add_column("category")
    table.add_column("risk", justify="right")
    table.add_column("expected")
    table.add_column("action")
    table.add_column("exp action")
    table.add_column("pass", justify="center")

    for r in rows:
        table.add_row(
            r.id,
            r.category,
            f"{r.max_risk:.2f}",
            f"[{r.expected_min:.2f}, {r.expected_max:.2f}]",
            r.actual_intervention,
            r.expected_intervention,
            "[green]✓[/green]" if r.pass_ else "[red]✗[/red]",
        )
    console.print(table)
    passed = sum(1 for r in rows if r.pass_)
    console.print(f"\nPassed: [bold]{passed}[/bold] / {len(rows)}")


def _write_json(rows: list[EvalRow], *, used_ollama: bool) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().isoformat().replace(":", "-")
    out = REPORTS_DIR / f"eval-{ts}.json"
    out.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().isoformat(),
                "runtime": "smart" if used_ollama else "heuristic",
                "rows": [r.to_json() for r in rows],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {out.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    raise SystemExit(main())
