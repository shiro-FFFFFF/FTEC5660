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
from guardian.data.scam_signals import ScamDbProvider
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


def test_multiple_manual_transfers_cover_no_medium_and_high_risk(pipeline):
    context, risk, intervention, _ = pipeline
    now = datetime.now()

    context.ingest(
        TransactionEvent(
            id="clean_beneficiary_transfer",
            timestamp=now,
            amount_hkd=2_000,
            to_name="APEX SOLUTIONS LIMITED",
            to_account="123-456-789-001",
            new_recipient=False,
            channel="manual_transfer",
        )
    )
    low = risk.assessments[-1]
    assert low.final_risk < 0.3

    context.ingest(
        TransactionEvent(
            id="reported_beneficiary_transfer",
            timestamp=now + timedelta(seconds=45),
            amount_hkd=12_000,
            to_name="CHAN TAI MAN COMPANY LIMITED",
            to_account="987-654-321-002",
            new_recipient=False,
            channel="manual_transfer",
        )
    )
    medium = risk.assessments[-1]
    assert 0.3 <= medium.final_risk < 0.6

    context.ingest(
        TransactionEvent(
            id="high_risk_beneficiary_transfer",
            timestamp=now + timedelta(seconds=90),
            amount_hkd=8_000,
            to_name="HARBOUR VIEW TRADING LTD",
            to_account="555-666-777-003",
            new_recipient=True,
            channel="manual_transfer",
        )
    )
    high = risk.assessments[-1]
    assert high.final_risk >= 0.6
    assert intervention.state.pending is not None
    assert intervention.state.pending.level == InterventionLevel.FULL_SCREEN


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


def test_auto_update_scamdatabase_for_unknown_high_risk_sms(db: ScamDatabase, tmp_path: Path):
    runtime_csv = tmp_path / "scam_db_runtime.csv"
    provider = ScamDbProvider(db, runtime_csv=runtime_csv)
    event_log = EventLog()
    intervention = InterventionAgent()
    llm = HeuristicLlmRuntime()
    risk = RiskAgent(
        scam_signals=provider,
        llm=llm,
        intervention=intervention,
        event_log=event_log,
    )
    context = ContextAgent(event_log=event_log, risk_agent=risk)

    sender = "+852 6123 4567"
    context.ingest(
        SmsEvent(
            id="auto_update_1",
            timestamp=datetime.now(),
            from_=sender,
            body=(
                "Urgent final notice. Transfer your funds to secure holding account "
                "now and do not tell your family. "
                "http://hkpost-hk.parcel-fee.top/p"
            ),
        )
    )

    assert runtime_csv.exists()
    lines = [line for line in runtime_csv.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2
    assert sender.lower() in lines[1].lower()


def test_auto_update_scamdatabase_skips_duplicate_number(db: ScamDatabase, tmp_path: Path):
    runtime_csv = tmp_path / "scam_db_runtime.csv"
    provider = ScamDbProvider(db, runtime_csv=runtime_csv)
    event_log = EventLog()
    intervention = InterventionAgent()
    llm = HeuristicLlmRuntime()
    risk = RiskAgent(
        scam_signals=provider,
        llm=llm,
        intervention=intervention,
        event_log=event_log,
    )
    context = ContextAgent(event_log=event_log, risk_agent=risk)

    sender = "+852 6123 4568"
    context.ingest(
        SmsEvent(
            id="dup_update_1",
            timestamp=datetime.now(),
            from_=sender,
            body=(
                "Urgent final notice. Transfer your funds to secure holding account "
                "now and do not tell your family. "
                "http://hkpost-hk.parcel-fee.top/p"
            ),
        )
    )
    context.ingest(
        SmsEvent(
            id="dup_update_2",
            timestamp=datetime.now() + timedelta(seconds=5),
            from_=sender,
            body=(
                "Final notice. Customs fee overdue. Transfer your funds now. "
                "http://hkpost-hk.parcel-fee.top/p"
            ),
        )
    )

    lines = [line for line in runtime_csv.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2
