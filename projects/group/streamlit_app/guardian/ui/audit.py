"""Audit trail — per-event risk assessment cards with tool-trace drill-down."""

from __future__ import annotations

import json

import streamlit as st

from guardian.agents.intervention_agent import InterventionAction, InterventionAgent
from guardian.agents.risk_agent import RiskAgent, RiskAssessment, RuleScoreContribution
from guardian.data.event_log import EventLog, EventLogEntry
from guardian.llm.tools import ToolCallStep
from guardian.scenarios.events import (
    CallEvent,
    ChatEvent,
    SmsEvent,
    TransactionEvent,
)
from guardian.ui.widgets import fmt_hkd, risk_chip


def render() -> None:
    st.title("🛡️ Audit trail")
    st.caption("Every decision is explainable — rules, LLM reasoning, tool calls.")

    risk_agent: RiskAgent = st.session_state["risk"]
    event_log: EventLog = st.session_state["event_log"]
    intervention: InterventionAgent = st.session_state["intervention"]

    assessments = list(reversed(risk_agent.assessments))
    events_by_id = {entry.event.id: entry for entry in event_log.entries}
    interventions_by_event = {i.event_id: i for i in intervention.state.history}

    if not assessments:
        st.info("No assessments yet. Play a scenario from Home to see Guardian reason.")
        return

    for assessment in assessments:
        _render_assessment(
            assessment,
            events_by_id.get(assessment.event_id),
            interventions_by_event.get(assessment.event_id),
        )
        st.markdown("")


def _render_assessment(
    assessment: RiskAssessment,
    entry: EventLogEntry | None,
    intervention: InterventionAction | None,
) -> None:
    with st.container(border=True):
        header = st.columns([4, 2])
        with header[0]:
            st.markdown(f"### {_subject_for(entry)}")
            if entry is not None:
                st.caption(entry.event.timestamp.strftime("%b %d · %H:%M:%S"))
        with header[1]:
            st.markdown(risk_chip(assessment.final_risk))

        st.divider()

        metric_cols = st.columns(4)
        metric_cols[0].metric("Fast rule", f"{assessment.fast_risk:.2f}")
        metric_cols[1].metric(
            "LLM",
            (
                f"{assessment.llm_risk:.2f}"
                if assessment.llm_risk is not None
                else "—"
            ),
            (
                f"conf {assessment.llm_confidence:.2f}"
                if assessment.llm_confidence is not None
                else None
            ),
        )
        metric_cols[2].metric(
            "Reviewer",
            (
                f"{assessment.reviewer_risk:.2f}"
                if assessment.reviewer_risk is not None
                else "—"
            ),
        )
        metric_cols[3].metric("Final", f"{assessment.final_risk:.2f}")

        info_cols = st.columns(3)
        info_cols[0].markdown(f"**Consensus:** `{assessment.consensus}`")
        info_cols[1].markdown(f"**Source:** `{assessment.source}`")
        info_cols[2].markdown(f"**Latency:** `{assessment.latency_ms} ms`")

        if assessment.contributions:
            with st.expander("Rule contributions", expanded=True):
                _render_contributions(assessment.contributions)

        if assessment.reasons:
            with st.expander("Reasons", expanded=True):
                for reason in assessment.reasons:
                    st.markdown(f"- {reason}")

        if assessment.tactics:
            st.markdown(
                "**Tactics:** "
                + " ".join(f"`{t.replace('_', ' ')}`" for t in assessment.tactics)
            )

        if assessment.tool_trace:
            with st.expander(
                f"Agent reasoning — {len(assessment.tool_trace)} step(s)",
                expanded=False,
            ):
                _render_trace(assessment.tool_trace)

        if intervention is not None:
            badge = f"`{intervention.level.value}`"
            flags: list[str] = []
            if intervention.overridden:
                flags.append("user overrode")
            if intervention.dismissed:
                flags.append("user dismissed")
            suffix = f" · {', '.join(flags)}" if flags else ""
            st.info(f"**Intervention:** {badge}{suffix}", icon="🛡️")


def _subject_for(entry: EventLogEntry | None) -> str:
    if entry is None:
        return "Event"
    event = entry.event
    if isinstance(event, CallEvent):
        return f"📞 Call from {event.from_}"
    if isinstance(event, SmsEvent):
        return f"📨 SMS from {event.from_}"
    if isinstance(event, ChatEvent):
        return f"💬 Chat with {event.contact}"
    if isinstance(event, TransactionEvent):
        return (
            f"💸 Transfer {fmt_hkd(event.amount_hkd)} → {event.to_name}"
        )
    return f"Event {event.id}"


def _render_contributions(contribs: list[RuleScoreContribution]) -> None:
    for c in contribs:
        cols = st.columns([2, 5, 1])
        cols[0].markdown(f"`{c.feature}`")
        cols[1].progress(min(1.0, max(0.0, c.value)))
        cols[2].markdown(f"**+{c.value:.2f}**")
        st.caption(c.detail)


def _render_trace(trace: list[ToolCallStep]) -> None:
    for i, step in enumerate(trace, start=1):
        args = json.dumps(step.args) if step.args else ""
        summary = _summarise_result(step.result)
        with st.container(border=True):
            st.markdown(f"**{i}. `{step.tool}({args})`** · {step.latency_ms} ms")
            st.caption(summary)
            with st.expander("Raw JSON", expanded=False):
                st.code(json.dumps(step.result, indent=2), language="json")


def _summarise_result(result: dict) -> str:
    if result.get("hit") is True:
        tag = (
            result.get("tag")
            or (result.get("matches") or [{}])[0].get("tag")
            or "?"
        )
        weight = result.get("weight") or (result.get("matches") or [{}])[0].get("weight")
        return f"hit (tag={tag}" + (f", w={weight})" if weight is not None else ")")
    if result.get("hit") is False:
        return "no hit"
    if "count" in result:
        return (
            f"{result.get('count')} keyword hit(s), "
            f"total_weight={result.get('total_weight')}"
        )
    if "recent_event_count" in result:
        ch = result.get("channels") or {}
        return (
            f"{result.get('recent_event_count')} events | "
            f"call={ch.get('call')} sms={ch.get('sms')} "
            f"chat={ch.get('chat')} txn={ch.get('transaction')}"
        )
    preview = json.dumps(result)
    return preview if len(preview) <= 160 else preview[:157] + "..."
