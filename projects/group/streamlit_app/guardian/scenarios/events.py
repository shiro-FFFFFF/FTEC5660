"""Scam-event model — 1:1 port of ``app/lib/scenarios/events.dart``.

Sealed hierarchy of events that flow through the Context / Risk /
Intervention pipeline. All events share ``id`` + ``timestamp`` and a
discriminator ``kind``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class EventKind(str, Enum):
    CALL = "call"
    SMS = "sms"
    CHAT = "chat"
    TRANSACTION = "transaction"


@dataclass(frozen=True)
class ScamEvent:
    id: str
    timestamp: datetime

    @property
    def kind(self) -> EventKind:  # pragma: no cover - abstract
        raise NotImplementedError

    def to_json(self) -> dict[str, Any]:  # pragma: no cover - abstract
        raise NotImplementedError


@dataclass(frozen=True)
class CallEvent(ScamEvent):
    from_: str
    transcript: str
    duration_seconds: int = 0
    direction: str = "incoming"

    @property
    def kind(self) -> EventKind:
        return EventKind.CALL

    def to_json(self) -> dict[str, Any]:
        return {
            "type": "call",
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "from": self.from_,
            "transcript": self.transcript,
            "duration_seconds": self.duration_seconds,
            "direction": self.direction,
        }


@dataclass(frozen=True)
class SmsEvent(ScamEvent):
    from_: str
    body: str

    @property
    def kind(self) -> EventKind:
        return EventKind.SMS

    def to_json(self) -> dict[str, Any]:
        return {
            "type": "sms",
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "from": self.from_,
            "body": self.body,
        }


@dataclass(frozen=True)
class ChatEvent(ScamEvent):
    contact: str
    body: str
    direction: str = "incoming"

    @property
    def kind(self) -> EventKind:
        return EventKind.CHAT

    def to_json(self) -> dict[str, Any]:
        return {
            "type": "chat",
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "contact": self.contact,
            "body": self.body,
            "direction": self.direction,
        }


@dataclass(frozen=True)
class TransactionEvent(ScamEvent):
    amount_hkd: float
    to_name: str
    to_account: str
    new_recipient: bool
    channel: str = "new_payee_transfer"

    @property
    def kind(self) -> EventKind:
        return EventKind.TRANSACTION

    def to_json(self) -> dict[str, Any]:
        return {
            "type": "transaction_attempt",
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "amount_hkd": self.amount_hkd,
            "to_name": self.to_name,
            "to_account": self.to_account,
            "new_recipient": self.new_recipient,
            "channel": self.channel,
        }


def event_from_json(payload: dict[str, Any], ts: datetime, event_id: str) -> ScamEvent:
    """Build a concrete event from the JSON payload used in scenario files."""
    type_ = payload["type"]
    if type_ == "call":
        return CallEvent(
            id=event_id,
            timestamp=ts,
            from_=payload.get("from", "Unknown"),
            transcript=payload.get("transcript", ""),
            duration_seconds=int(payload.get("duration_seconds", 0)),
            direction=payload.get("direction", "incoming"),
        )
    if type_ == "sms":
        return SmsEvent(
            id=event_id,
            timestamp=ts,
            from_=payload.get("from", "Unknown"),
            body=payload.get("body", ""),
        )
    if type_ == "chat":
        return ChatEvent(
            id=event_id,
            timestamp=ts,
            contact=payload.get("contact", "Unknown"),
            body=payload.get("body", ""),
            direction=payload.get("direction", "incoming"),
        )
    if type_ == "transaction_attempt":
        return TransactionEvent(
            id=event_id,
            timestamp=ts,
            amount_hkd=float(payload["amount_hkd"]),
            to_name=payload.get("to_name", "Unknown"),
            to_account=payload.get("to_account", ""),
            new_recipient=bool(payload.get("new_recipient", True)),
            channel=payload.get("channel", "new_payee_transfer"),
        )
    raise ValueError(f"Unknown event type: {type_}")
