"""SMS inbox — messages-only view of the event log."""

from __future__ import annotations

import streamlit as st

from guardian.data.event_log import EventLog
from guardian.scenarios.events import SmsEvent
from guardian.ui.widgets import risk_chip


def render() -> None:
    st.title("📨 Messages")
    event_log: EventLog = st.session_state["event_log"]
    entries = [e for e in event_log.entries if isinstance(e.event, SmsEvent)][::-1]

    if not entries:
        st.info("No messages yet. Play a scenario to see Guardian in action.")
        return

    for entry in entries:
        sms: SmsEvent = entry.event  # type: ignore[assignment]
        risk = entry.risk_score or 0.0
        with st.container(border=True):
            header = st.columns([4, 2])
            with header[0]:
                st.markdown(f"**{sms.from_}**")
                st.caption(sms.timestamp.strftime("%d %b · %H:%M"))
            with header[1]:
                if entry.risk_score is not None:
                    st.markdown(risk_chip(risk))
            with st.expander("Full message", expanded=risk >= 0.3):
                st.write(sms.body)
                if entry.tags:
                    st.caption("Tactics: " + ", ".join(f"`{t}`" for t in entry.tags))
