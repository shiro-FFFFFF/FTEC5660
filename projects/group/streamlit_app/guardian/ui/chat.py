"""Chat — contact selector + thread view for chat events."""

from __future__ import annotations

import streamlit as st

from guardian.data.event_log import EventLog, EventLogEntry
from guardian.scenarios.events import ChatEvent
from guardian.ui.widgets import risk_chip


def render() -> None:
    st.title("💬 Chat")
    event_log: EventLog = st.session_state["event_log"]
    by_contact: dict[str, list[EventLogEntry]] = {}
    for entry in event_log.entries:
        if isinstance(entry.event, ChatEvent):
            by_contact.setdefault(entry.event.contact, []).append(entry)

    if not by_contact:
        st.info("No chats yet. Play a scenario to see an incoming thread.")
        return

    contact = st.selectbox("Conversation", options=sorted(by_contact.keys()))
    entries = by_contact[contact]
    max_risk = max((e.risk_score or 0.0 for e in entries), default=0.0)
    if max_risk >= 0.3:
        st.markdown(f"**Thread risk** · {risk_chip(max_risk)}")

    st.divider()
    for entry in entries:
        chat: ChatEvent = entry.event  # type: ignore[assignment]
        is_incoming = chat.direction == "incoming"
        with st.chat_message("user" if is_incoming else "assistant"):
            st.write(chat.body)
            st.caption(chat.timestamp.strftime("%d %b · %H:%M"))
            if entry.risk_score is not None and is_incoming:
                st.caption(risk_chip(entry.risk_score))
