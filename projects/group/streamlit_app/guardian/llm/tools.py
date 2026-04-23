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

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field, create_model

from guardian.data.scam_signals import ScamSignalProvider
from guardian.rag.tools import retrieve_scam_patterns, retrieve_transfer_guidance
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
    provider: ScamSignalProvider,
    snapshot: ContextSnapshot,
    trace_callback: TraceCallback | None = None,
) -> ToolRegistry:
    trace: list[ToolCallStep] = []
    return ToolRegistry(
        [
            _make_tool(
                name="lookup_number",
                description=(
                    "Check a phone number, caller ID, or number substring against "
                    "a known scam-number blocklist. Use this only for phone-number "
                    "checking, not for website domains, beneficiary account numbers, "
                    "or recipient-name review. Returns {hit, tag, weight, note} if "
                    "a match is found, else {hit: false}."
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
                call=lambda args: _lookup_number(provider, args),
            ),
            _make_tool(
                name="check_domain",
                description=(
                    "Check website domains or URLs mentioned in message / SMS / chat "
                    "text against known phishing or scam hosts. Use this only for "
                    "website-domain checking, not for phone numbers, beneficiary "
                    "names, account numbers, or general web reputation. Returns "
                    "{hit, matches: [{domain, tag, weight, note}]} or {hit: false}."
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
                call=lambda args: _check_domain(provider, args),
            ),
            _make_tool(
                name="search_keywords",
                description=(
                    "Search message, SMS, chat, or call-transcript text for scam "
                    "script phrases. Use this only for free-form text analysis, not "
                    "for website-domain checks, phone-number checks, or bank "
                    "beneficiary validation. Returns {count, total_weight, hits: "
                    "[{keyword, tag, weight}]}."
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
                call=lambda args: _search_keywords(provider, args),
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
            _make_tool(
                name="check_beneficiary_for_bank_transfer",
                description=(
                    "Check a bank transfer beneficiary using the entered recipient "
                    "name and beneficiary account number. Use this only for bank "
                    "transfer review when you need to compare recipient name versus "
                    "account-number registry data and check prior beneficiary risk "
                    "reports. Do not use it for website domains, phone numbers, or "
                    "general identity checks. Returns {name_account_check, "
                    "reported_risk_status}."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "recipient_name": {
                            "type": "string",
                            "description": (
                                "Recipient name entered on the bank transfer form."
                            ),
                        },
                        "account_number": {
                            "type": "string",
                            "description": (
                                "Beneficiary account number entered for the bank transfer."
                            ),
                        },
                    },
                    "required": ["recipient_name", "account_number"],
                },
                trace=trace,
                trace_callback=trace_callback,
                call=lambda args: _check_beneficiary_for_bank_transfer(provider, args),
            ),
            _make_tool(
                name="update_scamdatabase_number",
                description=(
                    "Append a newly-detected scam phone number into runtime scam DB. "
                    "Use only when risk is high and the number is likely a real phone "
                    "number not already blocklisted. Returns {status}."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "number": {
                            "type": "string",
                            "description": "Phone number to append to scam DB.",
                        },
                        "risk": {
                            "type": "number",
                            "description": "Final risk score in [0,1].",
                        },
                        "reason": {
                            "type": "string",
                            "description": "Short reason for this update.",
                        },
                        "event_id": {
                            "type": "string",
                            "description": "Related event id.",
                        },
                        "source_model": {
                            "type": "string",
                            "description": "Model/source that made the decision.",
                        },
                        "weight": {
                            "type": "number",
                            "description": "Weight for the appended blocklist row.",
                        },
                        "tag": {
                            "type": "string",
                            "description": "Tag for the appended blocklist row.",
                        },
                    },
                    "required": [
                        "number",
                        "risk",
                        "reason",
                        "event_id",
                        "source_model",
                    ],
                },
                trace=trace,
                trace_callback=trace_callback,
                call=lambda args: _update_scamdatabase_number(provider, args),
            ),
            _instrument_langchain_tool(
                tool=retrieve_scam_patterns,
                description=(
                    "Retrieve anti-scam knowledge-base matches for SMS, call, chat, or "
                    "general scam-pattern analysis. Accepted params: query (required "
                    "string), top_k (optional small integer), category_filter "
                    "(optional one of scam_patterns, benign_patterns, tactics, "
                    "scenario_notes). Use this to retrieve scam narratives, tactics, "
                    "or benign look-alikes from local RAG. Do not use it for bank "
                    "beneficiary account/name checks."
                ),
                trace=trace,
                trace_callback=trace_callback,
            ),
            _instrument_langchain_tool(
                tool=retrieve_transfer_guidance,
                description=(
                    "Retrieve local RAG guidance for bank transfer review. Accepted "
                    "params: query (required string describing the transfer context), "
                    "top_k (optional small integer), category_filter (optional, "
                    "usually omitted). Use this for transfer-risk context such as "
                    "new recipient, urgency, recent suspicious call/SMS, beneficiary "
                    "mismatch, or prior beneficiary risk. Do not use it for domain "
                    "checks or phone-number checks."
                ),
                trace=trace,
                trace_callback=trace_callback,
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
        _emit(
            trace_callback,
            "THINKING",
            "Reviewing the tool result and deciding the next step",
            None,
        )
        return json.dumps(step.result)

    return StructuredTool.from_function(
        func=call_tool,
        name=name,
        description=description,
        args_schema=args_schema,
    )


def _instrument_langchain_tool(
    *,
    tool: BaseTool,
    description: str,
    trace: list[ToolCallStep],
    trace_callback: TraceCallback | None,
) -> StructuredTool:
    def call_tool(**kwargs: Any) -> str:
        _emit(
            trace_callback,
            "ACTION",
            f"Calling {tool.name}",
            json.dumps(kwargs, indent=2),
        )
        step = _timed_call(
            name=tool.name,
            args=dict(kwargs),
            call=lambda args: tool.invoke(args),
        )
        trace.append(step)
        _emit(
            trace_callback,
            "OBSERVATION",
            f"{tool.name} returned in {step.latency_ms} ms",
            json.dumps(step.result, indent=2),
        )
        _emit(
            trace_callback,
            "THINKING",
            "Reviewing the tool result and deciding the next step",
            None,
        )
        return json.dumps(step.result)

    return StructuredTool.from_function(
        func=call_tool,
        name=tool.name,
        description=description,
        args_schema=tool.args_schema,
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


def _lookup_number(
    provider: ScamSignalProvider,
    args: dict[str, Any],
) -> dict[str, Any]:
    number = str(args.get("number", ""))
    return provider.lookup_number(number)


def _check_domain(
    provider: ScamSignalProvider,
    args: dict[str, Any],
) -> dict[str, Any]:
    text = str(args.get("text", ""))
    return provider.check_domain(text)


def _search_keywords(
    provider: ScamSignalProvider,
    args: dict[str, Any],
) -> dict[str, Any]:
    text = str(args.get("text", ""))
    return provider.search_keywords(text)


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


def _check_beneficiary_for_bank_transfer(
    provider: ScamSignalProvider,
    args: dict[str, Any],
) -> dict[str, Any]:
    recipient_name = str(args.get("recipient_name", ""))
    account_number = str(args.get("account_number", ""))
    return provider.check_beneficiary_for_bank_transfer(
        recipient_name,
        account_number,
    )


def _update_scamdatabase_number(
    provider: ScamSignalProvider,
    args: dict[str, Any],
) -> dict[str, Any]:
    number = str(args.get("number", ""))
    reason = str(args.get("reason", "")).strip() or "high_risk_auto_detected"
    event_id = str(args.get("event_id", "")).strip() or "unknown_event"
    source_model = str(args.get("source_model", "")).strip() or "unknown_source"
    try:
        risk = float(args.get("risk", 0.0))
    except (TypeError, ValueError):
        risk = 0.0
    try:
        weight = float(args.get("weight", 0.6))
    except (TypeError, ValueError):
        weight = 0.6
    tag = str(args.get("tag", "auto_detected")).strip() or "auto_detected"
    return provider.update_scamdatabase_number(
        number=number,
        risk=max(0.0, min(1.0, risk)),
        reason=reason,
        event_id=event_id,
        source_model=source_model,
        weight=max(0.0, min(1.0, weight)),
        tag=tag,
    )


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
