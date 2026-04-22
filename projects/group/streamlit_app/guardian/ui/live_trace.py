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
            rows = _append_row(
                list(trace.get("rows", [])),
                tag=tag,
                message=message,
                detail=detail,
            )
            trace["rows"] = rows[-_MAX_ROWS:]
            trace["updated_at_ts"] = datetime.now().timestamp()
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

    def get(self, event_id: str) -> dict[str, Any] | None:
        with self._lock:
            trace = self._traces.get(event_id)
            return dict(trace) if trace is not None else None

    def recent_completed(self, *, limit: int = 3) -> list[dict[str, Any]]:
        with self._lock:
            completed = [
                dict(trace)
                for trace in self._traces.values()
                if trace.get("status") == "complete"
            ]
        completed.sort(key=lambda trace: float(trace.get("updated_at_ts", 0.0)), reverse=True)
        return completed[:limit]


def render(store: LiveTraceStore) -> None:
    running = store.running()
    completed = store.recent_completed()
    if not running and not completed:
        return

    if running:
        st.subheader("Running agent traces")
        for event_id, trace in running.items():
            rows = list(trace.get("rows", []))
            label = f"{event_id} · {len(rows)} step(s)"
            with st.expander(label, expanded=True):
                for row in rows:
                    _render_row(row)

    if completed:
        st.subheader("Recent assessment traces")
        for trace in completed:
            event_id = str(trace.get("event_id", "unknown"))
            rows = list(trace.get("rows", []))
            label = f"{event_id} · {len(rows)} step(s) · complete"
            with st.expander(label, expanded=False):
                for row in rows:
                    _render_row(row)


def render_event(store: LiveTraceStore, event_id: str) -> None:
    trace = store.get(event_id)
    if trace is None:
        return

    rows = list(trace.get("rows", []))
    if not rows:
        return

    status = str(trace.get("status", "running"))
    label = f"{event_id} · {len(rows)} step(s) · {status}"
    st.subheader("Transfer review trace")
    with st.expander(label, expanded=True):
        for row in rows:
            _render_row(row)


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


def _append_row(
    rows: list[dict[str, Any]],
    *,
    tag: str,
    message: str,
    detail: str | None,
) -> list[dict[str, Any]]:
    normalized_tag = tag.upper()
    next_rows = list(rows)

    # Keep THINKING as a transient placeholder so it disappears when the
    # next concrete step (ACTION / OBSERVATION / FINAL / ERROR) arrives.
    if next_rows and next_rows[-1].get("transient"):
        next_rows.pop()

    next_rows.append(
        {
            "tag": normalized_tag,
            "message": _trim(message, _MAX_MESSAGE),
            "detail": _trim(detail, _MAX_DETAIL) if detail else None,
            "time": datetime.now().strftime("%H:%M:%S"),
            "transient": normalized_tag == "THINKING",
        }
    )
    return next_rows


def _trim(value: str | None, limit: int) -> str:
    if value is None:
        return ""
    clean = " ".join(str(value).split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"
