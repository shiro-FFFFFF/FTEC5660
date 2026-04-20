"""LangChain tools for the risk agent.

The registry returned by :func:`build_default_tool_registry` contains
LangChain ``StructuredTool`` instances directly. Each tool records its own
``ToolCallStep`` when invoked so UI/audit traces do not need an adapter layer.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model

from guardian.data.scam_db import ScamDatabase
from guardian.scenarios.events import (
    CallEvent,
    ChatEvent,
    SmsEvent,
    TransactionEvent,
)

if TYPE_CHECKING:  # pragma: no cover
    from guardian.agents.context_agent import ContextSnapshot

TraceCallback = Callable[[str, str, str | None], None]


@dataclass(frozen=True)
class ToolCallStep:
    """One observed tool call. Surfaced in the audit trail."""

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


class ToolRegistry:
    def __init__(
        self,
        tools: list[StructuredTool],
        trace: list[ToolCallStep] | None = None,
    ) -> None:
        self._tools = {t.name: t for t in tools}
        self._trace = trace if trace is not None else []

    def find(self, name: str) -> StructuredTool | None:
        return self._tools.get(name)

    @property
    def all(self) -> list[StructuredTool]:
        return list(self._tools.values())

    @property
    def langchain_tools(self) -> list[StructuredTool]:
        return self.all

    @property
    def trace(self) -> list[ToolCallStep]:
        return list(self._trace)

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": _schema_for(tool),
            }
            for tool in self._tools.values()
        ]


def build_default_tool_registry(
    *,
    db: ScamDatabase,
    snapshot: ContextSnapshot,
    trace_callback: TraceCallback | None = None,
) -> ToolRegistry:
    trace: list[ToolCallStep] = []
    return ToolRegistry(
        [
            _make_tool(
                name="lookup_number",
                description=(
                    "Check whether a phone number (or a substring of one) is on a "
                    "known scam blocklist. Returns {hit, tag, weight, note} if a "
                    "match is found, else {hit: false}."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "number": {
                            "type": "string",
                            "description": (
                                "Phone number, prefix, or caller id, e.g. "
                                "'+852 0000 0001'."
                            ),
                        },
                    },
                    "required": ["number"],
                },
                trace=trace,
                trace_callback=trace_callback,
                call=lambda args: _lookup_number(db, args),
            ),
            _make_tool(
                name="check_domain",
                description=(
                    "Scan text for URLs or domains that are known phishing / scam "
                    "hosts. Returns {hit, matches: [{domain, tag, weight, note}]} "
                    "or {hit: false}."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Any free-form text that may contain URLs.",
                        },
                    },
                    "required": ["text"],
                },
                trace=trace,
                trace_callback=trace_callback,
                call=lambda args: _check_domain(db, args),
            ),
            _make_tool(
                name="search_keywords",
                description=(
                    "Search text for phrases commonly used in scam scripts. Returns "
                    "{count, total_weight, hits: [{keyword, tag, weight}]}."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Message or transcript text to scan.",
                        },
                    },
                    "required": ["text"],
                },
                trace=trace,
                trace_callback=trace_callback,
                call=lambda args: _search_keywords(db, args),
            ),
            _make_tool(
                name="get_history",
                description=(
                    "Summarise recent events in this session (last 72h). Useful for "
                    "temporal-correlation analysis. Returns channel counts, seconds "
                    "since last call/sms, and any prior max risk score."
                ),
                parameters={"type": "object", "properties": {}},
                trace=trace,
                trace_callback=trace_callback,
                call=lambda args: _get_history(snapshot),
            ),
        ],
        trace=trace,
    )


def _make_tool(
    *,
    name: str,
    description: str,
    parameters: dict[str, Any],
    trace: list[ToolCallStep],
    trace_callback: TraceCallback | None,
    call: Callable[[dict[str, Any]], dict[str, Any]],
) -> StructuredTool:
    args_schema = _args_schema_for_tool(name, parameters)

    def call_tool(**kwargs: Any) -> str:
        _emit(
            trace_callback,
            "ACTION",
            f"Calling {name}",
            json.dumps(kwargs, indent=2),
        )
        step = _timed_call(name=name, args=dict(kwargs), call=call)
        trace.append(step)
        _emit(
            trace_callback,
            "OBSERVATION",
            f"{name} returned in {step.latency_ms} ms",
            json.dumps(step.result, indent=2),
        )
        return json.dumps(step.result)

    return StructuredTool.from_function(
        func=call_tool,
        name=name,
        description=description,
        args_schema=args_schema,
    )


def _emit(
    trace_callback: TraceCallback | None,
    tag: str,
    message: str,
    detail: str | None = None,
) -> None:
    if trace_callback is None:
        return
    trace_callback(tag, message, detail)


def _timed_call(
    *,
    name: str,
    args: dict[str, Any],
    call: Callable[[dict[str, Any]], dict[str, Any]],
) -> ToolCallStep:
    started = time.monotonic()
    try:
        result = call(args)
    except Exception as e:  # pragma: no cover - defensive
        result = {"error": str(e)}
    elapsed_ms = int((time.monotonic() - started) * 1000)
    return ToolCallStep(
        tool=name,
        args=args,
        result=result,
        latency_ms=elapsed_ms,
    )


def _lookup_number(db: ScamDatabase, args: dict[str, Any]) -> dict[str, Any]:
    raw = str(args.get("number", "")).lower()
    for entry in db.bad_numbers():
        if entry.value in raw:
            return {
                "hit": True,
                "match": entry.value,
                "tag": entry.tag,
                "weight": entry.weight,
                "note": entry.note,
            }
    return {"hit": False}


def _check_domain(db: ScamDatabase, args: dict[str, Any]) -> dict[str, Any]:
    text = str(args.get("text", "")).lower()
    matches: list[dict[str, Any]] = []
    for domain in db.bad_domains():
        if domain.value in text:
            matches.append(
                {
                    "domain": domain.value,
                    "tag": domain.tag,
                    "weight": domain.weight,
                    "note": domain.note,
                }
            )
    return {"hit": False} if not matches else {"hit": True, "matches": matches}


def _search_keywords(db: ScamDatabase, args: dict[str, Any]) -> dict[str, Any]:
    text = str(args.get("text", "")).lower()
    hits: list[dict[str, Any]] = []
    total = 0.0
    for keyword in db.keywords():
        if keyword.value in text:
            hits.append(
                {
                    "keyword": keyword.value,
                    "tag": keyword.tag,
                    "weight": keyword.weight,
                }
            )
            total += keyword.weight
    return {
        "count": len(hits),
        "total_weight": round(total, 3),
        "hits": hits,
    }


def _get_history(snapshot: ContextSnapshot) -> dict[str, Any]:
    calls = sms = chats = txns = 0
    for event in snapshot.recent_events:
        if isinstance(event, CallEvent):
            calls += 1
        elif isinstance(event, SmsEvent):
            sms += 1
        elif isinstance(event, ChatEvent):
            chats += 1
        elif isinstance(event, TransactionEvent):
            txns += 1
    return {
        "recent_event_count": snapshot.recent_event_count,
        "channels": {
            "call": calls,
            "sms": sms,
            "chat": chats,
            "transaction": txns,
        },
        "has_recent_call": snapshot.has_recent_call,
        "has_recent_sms": snapshot.has_recent_sms,
        "seconds_since_last_call": (
            snapshot.seconds_since_last_call if snapshot.has_recent_call else None
        ),
        "seconds_since_last_sms": (
            snapshot.seconds_since_last_sms if snapshot.has_recent_sms else None
        ),
        "prior_max_risk": round(snapshot.prior_max_risk, 3),
    }


def _args_schema_for_tool(name: str, parameters: dict[str, Any]) -> type[BaseModel]:
    fields: dict[str, Any] = {}
    properties = parameters.get("properties", {})
    required = set(parameters.get("required", []))
    if not isinstance(properties, dict):
        properties = {}
    for field_name, spec in properties.items():
        if not isinstance(spec, dict):
            spec = {}
        py_type = _json_schema_type(spec.get("type"))
        default = ... if field_name in required else None
        fields[field_name] = (
            py_type if default is ... else py_type | None,
            Field(default, description=str(spec.get("description", ""))),
        )
    model_name = "".join(part.title() for part in name.split("_")) + "Args"
    return create_model(model_name, **fields)


def _json_schema_type(type_name: Any) -> type:
    if type_name == "string":
        return str
    if type_name == "integer":
        return int
    if type_name == "number":
        return float
    if type_name == "boolean":
        return bool
    if type_name == "array":
        return list
    if type_name == "object":
        return dict
    return Any


def _schema_for(tool: StructuredTool) -> dict[str, Any]:
    schema = tool.args_schema.model_json_schema() if tool.args_schema else {}
    return {
        "type": "object",
        "properties": schema.get("properties", {}),
        "required": schema.get("required", []),
    }
