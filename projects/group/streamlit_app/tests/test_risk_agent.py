"""Agent-level smoke tests.

Ports the pure-logic subset of ``app/test/`` to pytest. UI / widget
tests are out of scope — the eval harness + manual demo cover those.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from guardian.agents.context_agent import ContextAgent
from guardian.agents.intervention_agent import InterventionAgent, InterventionLevel
from guardian.agents.risk_agent import RiskAgent
from guardian.data.event_log import EventLog
from guardian.data.scam_db import ScamDatabase
from guardian.llm.heuristic import HeuristicLlmRuntime
from guardian.paths import SCAM_DB_CSV
from guardian.scenarios.events import (
    CallEvent,
    SmsEvent,
    TransactionEvent,
)


@pytest.fixture
def db() -> ScamDatabase:
    return ScamDatabase.from_csv(SCAM_DB_CSV.read_text(encoding="utf-8"))


@pytest.fixture
def pipeline(db):
    """Build a fresh Context → Risk → Intervention pipeline."""
    event_log = EventLog()
    intervention = InterventionAgent()
    llm = HeuristicLlmRuntime()
    risk = RiskAgent(
        scam_db=db, llm=llm, intervention=intervention, event_log=event_log
    )
    context = ContextAgent(event_log=event_log, risk_agent=risk)
    return context, risk, intervention, event_log


def test_benign_sms_is_silent(pipeline):
    context, risk, intervention, _ = pipeline
    context.ingest(
        SmsEvent(
            id="benign_sms",
            timestamp=datetime.now(),
            from_="+852 6000 0001",
            body="Dad, I'll be home at 7. Love you.",
        )
    )
    assert len(risk.assessments) == 1
    assert risk.assessments[0].final_risk < 0.3
    assert intervention.state.pending is None
    assert intervention.state.ambient is None


def test_phishing_sms_triggers_full_screen(pipeline):
    context, risk, intervention, _ = pipeline
    context.ingest(
        SmsEvent(
            id="phishing_sms",
            timestamp=datetime.now(),
            from_="HKPOST-Alert",
            body=(
                "Your parcel has unpaid customs fee HKD 48. Settle within 24h: "
                "http://hkpost-hk.parcel-fee.top/p"
            ),
        )
    )
    a = risk.assessments[-1]
    assert a.final_risk >= 0.7
    assert intervention.state.pending is not None
    assert intervention.state.pending.level == InterventionLevel.FULL_SCREEN


def test_police_call_followed_by_transfer_escalates_to_delay(pipeline):
    context, risk, intervention, _ = pipeline
    now = datetime.now()
    context.ingest(
        CallEvent(
            id="police_call",
            timestamp=now,
            from_="+852 0000 0001",
            transcript=(
                "This is the Hong Kong Police Cybercrime Unit. You must "
                "transfer your funds to a secure holding account immediately. "
                "Do not tell anyone."
            ),
        )
    )
    context.ingest(
        TransactionEvent(
            id="big_txn",
            timestamp=now + timedelta(seconds=120),
            amount_hkd=50_000,
            to_name="Unknown Ltd",
            to_account="012-345678-999",
            new_recipient=True,
        )
    )
    a = risk.assessments[-1]
    assert a.final_risk >= 0.85
    assert intervention.state.pending is not None
    assert intervention.state.pending.level == InterventionLevel.DELAY


def test_event_log_annotation_persists(pipeline):
    context, risk, intervention, event_log = pipeline
    context.ingest(
        SmsEvent(
            id="annotated",
            timestamp=datetime.now(),
            from_="HKPOST-Alert",
            body="URGENT parcel unpaid customs http://hkpost-hk.parcel-fee.top/p",
        )
    )
    entry = next(e for e in event_log.entries if e.event.id == "annotated")
    assert entry.risk_score is not None
    assert entry.risk_score >= 0.7
    assert entry.tags  # at least one tactic recorded


def test_intervention_override_clears_pending(pipeline):
    context, risk, intervention, _ = pipeline
    context.ingest(
        SmsEvent(
            id="phish",
            timestamp=datetime.now(),
            from_="HKPOST-Alert",
            body="URGENT unpaid customs http://hkpost-hk.parcel-fee.top/p",
        )
    )
    assert intervention.state.pending is not None
    intervention.override_pending()
    assert intervention.state.pending is None
    assert intervention.state.history[-1].overridden is True
