"""Recent-activity list renderer shared by Home and other screens."""

from __future__ import annotations

from typing import Iterable

import streamlit as st

from guardian.data.event_log import EventLogEntry
from guardian.scenarios.events import (
    CallEvent,
    ChatEvent,
    SmsEvent,
    TransactionEvent,
)
from guardian.ui.live_trace import LiveTraceStore
from guardian.ui.widgets import fmt_hkd, relative_time, risk_chip


def render(
    entries: Iterable[EventLogEntry],
    *,
    limit: int = 6,
    live_trace_store: LiveTraceStore | None = None,
) -> None:
    rows = list(entries)[-limit:][::-1]
    if not rows:
        st.info("No activity yet. Play a scenario from the sidebar or Home page.")
        return

    for entry in rows:
        event = entry.event
        if isinstance(event, CallEvent):
            icon = "📞"
            title = f"Call from {event.from_}"
            subtitle = event.transcript
        elif isinstance(event, SmsEvent):
            icon = "📨"
            title = f"SMS from {event.from_}"
            subtitle = event.body
        elif isinstance(event, ChatEvent):
            icon = "💬"
            title = f"Chat · {event.contact}"
            subtitle = event.body
        elif isinstance(event, TransactionEvent):
            icon = "💸"
            title = f"Transfer {fmt_hkd(event.amount_hkd)} → {event.to_name}"
            subtitle = "New payee transfer" if event.new_recipient else "Transfer"
        else:  # pragma: no cover - defensive
            icon = "•"
            title = event.id
            subtitle = ""

        with st.container(border=True):
            cols = st.columns([1, 6, 2])
            cols[0].markdown(f"### {icon}")
            with cols[1]:
                st.markdown(f"**{title}**")
                if subtitle:
                    st.caption(subtitle[:140] + ("…" if len(subtitle) > 140 else ""))
                st.caption(relative_time(event.timestamp))
            with cols[2]:
                if entry.risk_score is not None:
                    st.markdown(risk_chip(entry.risk_score))
                if entry.tags:
                    tag_pills = " ".join(f"`{t}`" for t in entry.tags[:3])
                    st.caption(tag_pills)
            _render_trace(entry.event.id, live_trace_store)


def _render_trace(event_id: str, live_trace_store: LiveTraceStore | None) -> None:
    if live_trace_store is None:
        return
    trace = live_trace_store.get(event_id)
    if trace is None:
        return

    rows = list(trace.get("rows", []))
    if not rows:
        return

    status = str(trace.get("status", "running"))
    label = f"Assessment trace · {len(rows)} step(s) · {status}"
    with st.expander(label, expanded=False):
        for row in rows:
            tag = str(row.get("tag", "INFO"))
            message = str(row.get("message", ""))
            time = str(row.get("time", ""))
            st.markdown(f"`[{tag}]` **{message}**")
            if time:
                st.caption(time)
            detail = row.get("detail")
            if detail:
                st.code(str(detail), language="text")
