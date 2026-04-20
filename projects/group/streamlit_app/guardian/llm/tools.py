"""Agent tools for the Risk ReAct loop.

Port of ``app/lib/llm/tools.dart``. Each tool exposes a JSON-schema
description + a ``call(args)`` method; the model invokes them via
``<tool>{"name": ..., "args": ...}</tool>`` tags.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from guardian.data.scam_db import ScamDatabase
from guardian.scenarios.events import (
    CallEvent,
    ChatEvent,
    SmsEvent,
    TransactionEvent,
)

if TYPE_CHECKING:  # pragma: no cover
    from guardian.agents.context_agent import ContextSnapshot


@dataclass(frozen=True)
class ToolCallStep:
    """One observed step in the ReAct loop. Surfaced in the audit trail."""

    tool: str
    args: dict[str, Any]
    result: dict[str, Any]
    latency_ms: int

    def to_json(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "args": self.args,
            "result": self.result,
            "latency_ms": self.latency_ms,
        }


class AgentTool(ABC):
    """Contract for a tool the risk LLM can invoke during ReAct."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]: ...

    @abstractmethod
    def call(self, args: dict[str, Any]) -> dict[str, Any]: ...


class ToolRegistry:
    def __init__(self, tools: list[AgentTool]) -> None:
        self._tools = {t.name: t for t in tools}

    def find(self, name: str) -> AgentTool | None:
        return self._tools.get(name)

    @property
    def all(self) -> list[AgentTool]:
        return list(self._tools.values())

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            }
            for t in self._tools.values()
        ]


# -- concrete tools ---------------------------------------------------------


class LookupNumberTool(AgentTool):
    def __init__(self, db: ScamDatabase) -> None:
        self.db = db

    @property
    def name(self) -> str:
        return "lookup_number"

    @property
    def description(self) -> str:
        return (
            "Check whether a phone number (or a substring of one) is on a "
            "known scam blocklist. Returns {hit, tag, weight, note} if a "
            "match is found, else {hit: false}."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "number": {
                    "type": "string",
                    "description": "Phone number, prefix, or caller id, e.g. '+852 0000 0001'.",
                },
            },
            "required": ["number"],
        }

    def call(self, args: dict[str, Any]) -> dict[str, Any]:
        raw = str(args.get("number", "")).lower()
        for e in self.db.bad_numbers():
            if e.value in raw:
                return {
                    "hit": True,
                    "match": e.value,
                    "tag": e.tag,
                    "weight": e.weight,
                    "note": e.note,
                }
        return {"hit": False}


class CheckDomainTool(AgentTool):
    def __init__(self, db: ScamDatabase) -> None:
        self.db = db

    @property
    def name(self) -> str:
        return "check_domain"

    @property
    def description(self) -> str:
        return (
            "Scan text for URLs or domains that are known phishing / scam "
            "hosts. Returns {hit, matches: [{domain, tag, weight, note}]} "
            "or {hit: false}."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Any free-form text that may contain URLs.",
                },
            },
            "required": ["text"],
        }

    def call(self, args: dict[str, Any]) -> dict[str, Any]:
        text = str(args.get("text", "")).lower()
        matches: list[dict[str, Any]] = []
        for d in self.db.bad_domains():
            if d.value in text:
                matches.append(
                    {
                        "domain": d.value,
                        "tag": d.tag,
                        "weight": d.weight,
                        "note": d.note,
                    }
                )
        return {"hit": False} if not matches else {"hit": True, "matches": matches}


class SearchKeywordsTool(AgentTool):
    def __init__(self, db: ScamDatabase) -> None:
        self.db = db

    @property
    def name(self) -> str:
        return "search_keywords"

    @property
    def description(self) -> str:
        return (
            "Search text for phrases commonly used in scam scripts. Returns "
            "{count, total_weight, hits: [{keyword, tag, weight}]}."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Message or transcript text to scan.",
                },
            },
            "required": ["text"],
        }

    def call(self, args: dict[str, Any]) -> dict[str, Any]:
        text = str(args.get("text", "")).lower()
        hits: list[dict[str, Any]] = []
        total = 0.0
        for k in self.db.keywords():
            if k.value in text:
                hits.append({"keyword": k.value, "tag": k.tag, "weight": k.weight})
                total += k.weight
        return {
            "count": len(hits),
            "total_weight": round(total, 3),
            "hits": hits,
        }


class GetHistoryTool(AgentTool):
    def __init__(self, snapshot: "ContextSnapshot") -> None:
        self.snapshot = snapshot

    @property
    def name(self) -> str:
        return "get_history"

    @property
    def description(self) -> str:
        return (
            "Summarise recent events in this session (last 72h). Useful for "
            "temporal-correlation analysis. Returns channel counts, seconds "
            "since last call/sms, and any prior max risk score."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def call(self, args: dict[str, Any]) -> dict[str, Any]:
        calls = sms = chats = txns = 0
        for e in self.snapshot.recent_events:
            if isinstance(e, CallEvent):
                calls += 1
            elif isinstance(e, SmsEvent):
                sms += 1
            elif isinstance(e, ChatEvent):
                chats += 1
            elif isinstance(e, TransactionEvent):
                txns += 1
        return {
            "recent_event_count": self.snapshot.recent_event_count,
            "channels": {
                "call": calls,
                "sms": sms,
                "chat": chats,
                "transaction": txns,
            },
            "has_recent_call": self.snapshot.has_recent_call,
            "has_recent_sms": self.snapshot.has_recent_sms,
            "seconds_since_last_call": (
                self.snapshot.seconds_since_last_call
                if self.snapshot.has_recent_call
                else None
            ),
            "seconds_since_last_sms": (
                self.snapshot.seconds_since_last_sms
                if self.snapshot.has_recent_sms
                else None
            ),
            "prior_max_risk": round(self.snapshot.prior_max_risk, 3),
        }


def build_default_tool_registry(
    *,
    db: ScamDatabase,
    snapshot: "ContextSnapshot",
) -> ToolRegistry:
    return ToolRegistry(
        [
            LookupNumberTool(db),
            CheckDomainTool(db),
            SearchKeywordsTool(db),
            GetHistoryTool(snapshot),
        ]
    )


def timed_call(tool: AgentTool, args: dict[str, Any]) -> ToolCallStep:
    """Invoke ``tool.call(args)`` and capture the latency for the audit trail."""
    started = time.monotonic()
    try:
        result = tool.call(args)
    except Exception as e:  # pragma: no cover - defensive
        result = {"error": str(e)}
    elapsed_ms = int((time.monotonic() - started) * 1000)
    return ToolCallStep(
        tool=tool.name,
        args=args,
        result=result,
        latency_ms=elapsed_ms,
    )
