"""Thread-safe store and Home renderer for active agent traces."""

from __future__ import annotations

from datetime import datetime
from threading import Lock
from typing import Any

import streamlit as st

_MAX_ROWS = 20
_MAX_MESSAGE = 120
_MAX_DETAIL = 700


class LiveTraceStore:
    """Collect trace rows without touching Streamlit from agent callbacks."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._traces: dict[str, dict[str, Any]] = {}

    def make_callback(self, event_id: str):
        def callback(tag: str, message: str, detail: str | None = None) -> None:
            self.append(event_id=event_id, tag=tag, message=message, detail=detail)

        return callback

    def append(
        self,
        *,
        event_id: str,
        tag: str,
        message: str,
        detail: str | None = None,
    ) -> None:
        with self._lock:
            trace = dict(
                self._traces.get(
                    event_id,
                    {
                        "event_id": event_id,
                        "status": "running",
                        "started_at": datetime.now().strftime("%H:%M:%S"),
                        "rows": [],
                    },
                )
            )
            rows = list(trace.get("rows", []))
            rows.append(
                {
                    "tag": tag.upper(),
                    "message": _trim(message, _MAX_MESSAGE),
                    "detail": _trim(detail, _MAX_DETAIL) if detail else None,
                    "time": datetime.now().strftime("%H:%M:%S"),
                }
            )
            trace["rows"] = rows[-_MAX_ROWS:]
            if tag.upper() == "FINAL":
                trace["status"] = "complete"
            self._traces[event_id] = trace

    def running(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {
                event_id: dict(trace)
                for event_id, trace in self._traces.items()
                if trace.get("status") == "running"
            }

    def has_running(self) -> bool:
        with self._lock:
            return any(trace.get("status") == "running" for trace in self._traces.values())

    def prune_completed(self) -> None:
        with self._lock:
            self._traces = {
                event_id: trace
                for event_id, trace in self._traces.items()
                if trace.get("status") == "running"
            }


def render(store: LiveTraceStore) -> None:
    running = store.running()
    if not running:
        store.prune_completed()
        return

    st.subheader("Running agent traces")
    for event_id, trace in running.items():
        rows = list(trace.get("rows", []))
        label = f"{event_id} · {len(rows)} step(s)"
        with st.expander(label, expanded=True):
            for row in rows:
                _render_row(row)
    store.prune_completed()


def _render_row(row: dict[str, Any]) -> None:
    tag = str(row.get("tag", "INFO"))
    message = str(row.get("message", ""))
    time = str(row.get("time", ""))
    st.markdown(f"`[{tag}]` **{message}**")
    if time:
        st.caption(time)
    detail = row.get("detail")
    if detail:
        st.code(str(detail), language="text")


def _trim(value: str | None, limit: int) -> str:
    if value is None:
        return ""
    clean = " ".join(str(value).split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"
