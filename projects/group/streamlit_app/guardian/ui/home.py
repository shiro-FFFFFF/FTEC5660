"""Home screen — greeting, scenario picker, pending-txn card, activity feed."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from guardian.scenarios.engine import ScenarioEngine
from guardian.ui import activity, live_trace
from guardian.ui.widgets import fmt_hkd, risk_chip


def render() -> None:
    engine: ScenarioEngine = st.session_state["engine"]
    risk = st.session_state["risk"]
    event_log = st.session_state["event_log"]
    live_trace_store = st.session_state["live_trace_store"]
    user_settings = st.session_state["user_settings"].state

    _render_header(holder=user_settings.account_holder, risk_agent=risk)

    st.markdown("")

    pending_txn = engine.state.pending_user_transaction
    if pending_txn is not None:
        _render_pending_txn_card(pending_txn)

    live_trace.render(live_trace_store)

    _render_quick_links()

    st.divider()
    _render_scenario_panel(engine)

    st.divider()
    st.subheader("Recent activity")
    activity.render(
        event_log.entries,
        limit=6,
        live_trace_store=live_trace_store,
    )


def _render_header(*, holder: str, risk_agent) -> None:
    hour = datetime.now().hour
    period = (
        "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
    )
    assessments = risk_agent.assessments
    top_risk = max((a.final_risk for a in assessments), default=0.0)

    cols = st.columns([3, 2])
    with cols[0]:
        st.title(f"{period}, {holder}")
        st.markdown(f"🛡️ Guardian is on · {risk_chip(top_risk)}")
    with cols[1]:
        st.metric(
            "Session assessments",
            len(assessments),
            delta=(
                f"top {int(round(top_risk * 100))}%"
                if top_risk > 0
                else "no flags yet"
            ),
        )


def _render_pending_txn_card(txn) -> None:
    with st.container(border=True):
        st.markdown("##### 🟠 Next step — the caller is pressuring you")
        st.markdown(
            f"Transfer **{fmt_hkd(txn.amount_hkd)}** to **{txn.to_name}**"
        )
        st.caption(
            "Open the Bank → Transfer form to see what Guardian does. "
            "The form is pre-filled from the scripted request."
        )
        if st.button(
            "Open Transfer screen",
            type="primary",
            use_container_width=True,
        ):
            st.switch_page("pages/2_🏦_Bank.py")


def _render_quick_links() -> None:
    st.markdown("### Quick access")
    cols = st.columns(4)
    if cols[0].button("🏦 Bank", use_container_width=True):
        st.switch_page("pages/2_🏦_Bank.py")
    if cols[1].button("📨 Messages", use_container_width=True):
        st.switch_page("pages/3_📨_Messages.py")
    if cols[2].button("💬 Chat", use_container_width=True):
        st.switch_page("pages/4_💬_Chat.py")
    if cols[3].button("🛡️ Audit", use_container_width=True):
        st.switch_page("pages/5_🛡️_Audit.py")


def _render_scenario_panel(engine: ScenarioEngine) -> None:
    st.subheader("Demo scenarios")
    st.caption(
        "Play a scripted scam or benign scenario. Events flow through the "
        "Guardian agents in real time."
    )
    scenarios = engine.list_scenarios()

    playing = engine.state.playing
    if playing is not None:
        st.progress(min(1.0, engine.state.progress), text=f"Playing: {playing.label}")
        if st.button("⏹ Stop scenario"):
            engine.stop()
            st.rerun()
        return

    cols = st.columns(2)
    for i, scenario in enumerate(scenarios):
        col = cols[i % 2]
        with col:
            label = scenario.id.replace("_", " ").title()
            if col.button(
                f"▶ {label}",
                key=f"play_{scenario.id}",
                use_container_width=True,
                help=scenario.label,
            ):
                engine.play(scenario.id)
                st.rerun()
