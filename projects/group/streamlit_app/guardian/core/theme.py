"""Risk palette — colours and human labels mirroring the Flutter version.

The Flutter app uses a green / amber / red spectrum keyed on the final risk
score. We replicate the exact thresholds so the audit trail colours match.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskBucket:
    color: str  # hex, e.g. "#1E8E3E"
    label: str
    emoji: str


_SAFE = RiskBucket(color="#1E8E3E", label="All clear", emoji="🟢")
_WATCH = RiskBucket(color="#E37400", label="Worth a second look", emoji="🟠")
_ALERT = RiskBucket(color="#D93025", label="Likely scam", emoji="🔴")


def for_risk(risk: float) -> RiskBucket:
    if risk >= 0.6:
        return _ALERT
    if risk >= 0.3:
        return _WATCH
    return _SAFE


def label_for(risk: float) -> str:
    return for_risk(risk).label


def color_for(risk: float) -> str:
    return for_risk(risk).color


def emoji_for(risk: float) -> str:
    return for_risk(risk).emoji
