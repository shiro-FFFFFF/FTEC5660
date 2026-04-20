"""Small shared UI helpers used across screens."""

from __future__ import annotations

import streamlit as st

from guardian.core import theme


def fmt_hkd(amount: float) -> str:
    """Format an HKD amount as ``HK$ 50,000``."""
    return f"HK$ {amount:,.0f}"


def risk_chip(risk: float) -> str:
    """Return a Markdown-coloured pill for the given risk score."""
    bucket = theme.for_risk(risk)
    pct = int(round(risk * 100))
    return (
        f":{_streamlit_color(bucket.color)}[**{bucket.emoji} {pct}% · "
        f"{bucket.label}**]"
    )


def kv_row(label: str, value: str) -> None:
    cols = st.columns([1, 2])
    cols[0].markdown(f"**{label}**")
    cols[1].markdown(value)


def relative_time(ts) -> str:
    """Human-ish relative time, e.g. ``just now``, ``5 min ago``."""
    from datetime import datetime

    delta = datetime.now() - ts
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86_400:
        return f"{seconds // 3600} h ago"
    days = seconds // 86_400
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    return ts.strftime("%d %b")


# -- internal ---------------------------------------------------------------


def _streamlit_color(hex_color: str) -> str:
    """Map our theme hex to the nearest Streamlit named colour.

    Streamlit's ``:colour[text]`` syntax only accepts a fixed palette.
    """
    mapping = {
        "#1E8E3E": "green",
        "#E37400": "orange",
        "#D93025": "red",
    }
    return mapping.get(hex_color, "blue")
