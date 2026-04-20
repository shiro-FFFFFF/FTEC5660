"""LangChain-backed risk agent.

This module owns the agent structure for risk scoring: Guardian tools,
structured output, trace capture, and the ``create_agent`` graph. Model
adapters such as ``guardian.llm.ollama`` only provide a chat model.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import BaseMessage
from pydantic import BaseModel, Field

from guardian.llm.prompts import RISK_SYSTEM_PROMPT, build_risk_prompt
from guardian.llm.runtime import LlmRiskOutput
from guardian.llm.tools import ToolRegistry, TraceCallback

if TYPE_CHECKING:  # pragma: no cover
    from guardian.agents.context_agent import ContextSnapshot
    from guardian.agents.risk_agent import RuleScoreContribution

log = logging.getLogger(__name__)


class RiskAgentOutput(BaseModel):
    """Structured final output from the LangChain risk agent."""

    risk: float = Field(ge=0.0, le=1.0, description="Scam risk from 0 to 1.")
    tactics: list[str] = Field(
        default_factory=list,
        description="Detected scam tactics from the allowed Guardian tactic set.",
    )
    reasons: list[str] = Field(
        default_factory=list,
        description="Short elderly-friendly reasons, max 12 words each.",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Model confidence from 0 to 1.",
    )


def score_risk_with_langchain_agent(
    *,
    model: Any,
    model_name: str,
    snapshot: ContextSnapshot,
    rule_score: float,
    rule_contributions: list[RuleScoreContribution],
    tools: ToolRegistry,
    trace_callback: TraceCallback | None = None,
    max_steps: int = 4,
) -> LlmRiskOutput:
    prompt = build_risk_prompt(
        snapshot=snapshot,
        rule_score=rule_score,
        rule_contributions=rule_contributions,
    )
    _emit(trace_callback, "HUMAN", "Received risk prompt", prompt)
    agent = create_agent(
        model,
        tools=tools.langchain_tools,
        system_prompt=_agent_system_prompt(max_steps=max_steps),
        response_format=ToolStrategy(
            schema=RiskAgentOutput,
            tool_message_content="Risk assessment captured.",
        ),
    )
    _emit(trace_callback, "THINKING", "LangChain agent loop started", None)
    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ]
        },
        config={"recursion_limit": max_steps * 2 + 5},
    )
    structured = result.get("structured_response") if isinstance(result, dict) else None
    if isinstance(structured, RiskAgentOutput):
        log.info("LangChain agent returned structured output.")
        parsed = structured
    else:
        parsed = _parse_fallback_response(result)
    _emit(
        trace_callback,
        "FINAL",
        f"Agent produced risk {parsed.risk:.2f}",
        parsed.model_dump_json(indent=2),
    )
    return LlmRiskOutput(
        risk=parsed.risk,
        tactics=list(parsed.tactics),
        reasons=list(parsed.reasons),
        confidence=parsed.confidence,
        source=f"{model_name}+agent",
        trace=tools.trace,
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


def _agent_system_prompt(max_steps: int) -> str:
    return f"""{RISK_SYSTEM_PROMPT}

You may call tools to gather evidence before producing the final risk JSON.
Use at most {max_steps} tool calls. When you have enough evidence, produce
exactly one structured risk response.
Never invent facts not present in the input or tool results.
"""


def _parse_fallback_response(result: Any) -> RiskAgentOutput:
    raw = _last_message_text(result)
    parsed = _extract_json(raw)
    if parsed is None:
        raise RuntimeError("LangChain agent did not return a structured risk response")
    return RiskAgentOutput.model_validate(parsed)


def _extract_json(raw: str) -> dict[str, Any] | None:
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if 0 <= start < end:
        try:
            obj = json.loads(raw[start : end + 1])
            return obj if isinstance(obj, dict) else None
        except Exception:
            pass
    return None


def _last_message_text(result: Any) -> str:
    if isinstance(result, dict):
        messages = result.get("messages")
        if isinstance(messages, list) and messages:
            return _message_content_to_text(messages[-1])
    return _message_content_to_text(result)


def _message_content_to_text(message: Any) -> str:
    content = message.content if isinstance(message, BaseMessage) else None
    if content is None:
        content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return str(content or "")
