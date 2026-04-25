"""Scenario engine smoke tests — JSON loader + poll loop."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta

import pytest

from guardian.agents.context_agent import ContextAgent
from guardian.agents.intervention_agent import InterventionAgent
from guardian.agents.risk_agent import RiskAgent
from guardian.data.event_log import EventLog
from guardian.data.scam_db import ScamDatabase
from guardian.llm.heuristic import HeuristicLlmRuntime
from guardian.paths import SCAM_DB_CSV, SCENARIOS_DIR
from guardian.scenarios.engine import Scenario, ScenarioEngine
from guardian.scenarios.events import TransactionEvent


@pytest.fixture
def engine():
    db = ScamDatabase.from_csv(SCAM_DB_CSV.read_text(encoding="utf-8"))
    event_log = EventLog()
    intervention = InterventionAgent()
    llm = HeuristicLlmRuntime()
    risk = RiskAgent(
        scam_db=db, llm=llm, intervention=intervention, event_log=event_log
    )
    context = ContextAgent(event_log=event_log, risk_agent=risk)
    return ScenarioEngine(context=context, scenarios_dir=SCENARIOS_DIR)


def test_list_scenarios_discovers_seven(engine):
    scenarios = engine.list_scenarios()
    ids = {s.id for s in scenarios}
    assert "01_sms_phishing" in ids
    assert "02_voice_police" in ids
    assert "03_romance_investment" in ids
    assert "04_urgent_transfer" in ids
    assert "06_multiple_manual_transfer" in ids
    assert "benign_01_family_transfer" in ids
    assert "benign_02_utility_bill" in ids


def test_scenario_from_json_parses_offsets(tmp_path):
    payload = {
        "id": "demo",
        "label": "Demo",
        "category": "test",
        "expected": {"intervention": "none", "min_risk": 0, "max_risk": 0.3},
        "events": [
            {"t_seconds": 0, "type": "sms", "from": "HKPOST", "body": "hi"},
            {"t_seconds": 30, "type": "sms", "from": "HKPOST", "body": "hi again"},
        ],
    }
    s = Scenario.from_json(payload)
    assert s.id == "demo"
    assert len(s.events) == 2
    assert s.events[1].offset == timedelta(seconds=30)


def test_poll_ingests_events_whose_offset_has_elapsed(engine):
    # Feed a tiny scenario inline by seeding the cache.
    payload = {
        "id": "inline",
        "label": "inline",
        "category": "test",
        "expected": {"intervention": "none"},
        "events": [
            {
                "t_seconds": 0,
                "type": "sms",
                "from": "Family",
                "body": "Benign message",
            },
        ],
    }
    scenario = Scenario.from_json(payload)
    engine._cache[scenario.id] = scenario
    engine._loaded_index = True
    engine.play(scenario.id)
    # Sleep a hair so the 0s offset is definitely elapsed.
    time.sleep(0.05)
    engine.poll()
    # The single event should have been ingested.
    assert not engine.state.pending_user_transaction
    assert engine.state.progress == 1.0


def test_transaction_event_becomes_pending_instead_of_ingested(engine):
    payload = {
        "id": "txn_demo",
        "label": "txn",
        "category": "test",
        "expected": {"intervention": "none"},
        "events": [
            {
                "t_seconds": 0,
                "type": "transaction_attempt",
                "amount_hkd": 5000,
                "to_name": "Alice",
                "to_account": "012-345678-001",
                "new_recipient": False,
            },
        ],
    }
    scenario = Scenario.from_json(payload)
    engine._cache[scenario.id] = scenario
    engine._loaded_index = True
    engine.play(scenario.id)
    time.sleep(0.05)
    engine.poll()
    pending = engine.state.pending_user_transaction
    assert pending is not None
    assert isinstance(pending, TransactionEvent)
    assert pending.amount_hkd == 5000


def test_max_idle_env_caps_scenario_gaps(engine, monkeypatch):
    monkeypatch.setenv("GUARDIAN_SCENARIO_MAX_IDLE_S", "1.5")
    payload = {
        "id": "accelerated_demo",
        "label": "accelerated",
        "category": "test",
        "expected": {"intervention": "none"},
        "events": [
            {"t_seconds": 0, "type": "sms", "from": "Family", "body": "First"},
            {"t_seconds": 10, "type": "sms", "from": "Family", "body": "Second"},
        ],
    }
    scenario = Scenario.from_json(payload)
    engine._cache[scenario.id] = scenario
    engine._loaded_index = True
    engine.play(scenario.id)

    time.sleep(0.1)
    engine.poll()
    assert engine.state.progress > 0.0

    time.sleep(1.6)
    engine.poll()
    assert engine.state.progress == 1.0


def test_max_idle_releases_events_one_by_one_after_previous_finishes(engine, monkeypatch):
    monkeypatch.setenv("GUARDIAN_SCENARIO_MAX_IDLE_S", "1.0")
    payload = {
        "id": "serial_accelerated_demo",
        "label": "serial accelerated",
        "category": "test",
        "expected": {"intervention": "none"},
        "events": [
            {"t_seconds": 0, "type": "sms", "from": "Family", "body": "First"},
            {"t_seconds": 10, "type": "sms", "from": "Family", "body": "Second"},
            {"t_seconds": 20, "type": "sms", "from": "Family", "body": "Third"},
        ],
    }
    scenario = Scenario.from_json(payload)
    engine._cache[scenario.id] = scenario
    engine._loaded_index = True
    engine.play(scenario.id)

    # Even if enough wall-clock time has passed to cover multiple capped gaps,
    # the engine should only release one event per poll cycle.
    time.sleep(2.2)
    engine.poll()
    assert engine._fired == {0}

    time.sleep(1.1)
    engine.poll()
    assert engine._fired == {0, 1}

    time.sleep(1.1)
    engine.poll()
    assert engine._fired == {0, 1, 2}
