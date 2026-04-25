"""System / user prompts. Ported verbatim from ``app/lib/llm/prompts.dart``."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from guardian.scenarios.events import (
    CallEvent,
    ChatEvent,
    ScamEvent,
    SmsEvent,
    TransactionEvent,
)

if TYPE_CHECKING:  # pragma: no cover
    from guardian.agents.context_agent import ContextSnapshot
    from guardian.agents.risk_agent import RuleScoreContribution
    from guardian.llm.tools import ToolRegistry


RISK_SYSTEM_PROMPT = """You are Guardian, an anti-scam decision support agent for elderly banking users.
You will receive a TRIGGER event and a short CONTEXT history.
Output a STRICT JSON object matching this schema, with no prose:

{"risk": <number 0-1>, "tactics": [<string>...], "reasons": [<short sentence>...], "confidence": <number 0-1>}

Guidelines:
- risk closer to 1 means higher probability the user is being scammed.
- tactics come from this allowed set (pick any that apply):
  authority_impersonation, urgency, isolation, payment_redirect,
  investment_scam, romance_scam, courier_scam, credential_theft,
  temporal_correlation, atypical_payee, unverified_link
- reasons must be plain-language, max 12 words each, elderly-friendly.
- Never invent facts not present in the input.
"""


def build_risk_prompt(
    *,
    snapshot: "ContextSnapshot",
    rule_score: float,
    rule_contributions: list["RuleScoreContribution"],
) -> str:
    trig = _describe_event(snapshot.triggering_event)
    ctx = [
        _describe_event(e)
        for e in snapshot.recent_events
        if e.id != snapshot.triggering_event.id
    ]
    summary = "\n".join(
        f"- {c.feature} (+{c.value:.2f}): {c.detail}" for c in rule_contributions
    )
    lines: list[str] = []
    lines.append("TRIGGER:")
    lines.append(trig)
    lines.append("")
    lines.append("CONTEXT (most recent first, up to 5):")
    for line in list(reversed(ctx))[:5]:
        lines.append(f"- {line}")
    lines.append("")
    lines.append(f"RULE SCORE: {rule_score:.2f}")
    lines.append("RULE CONTRIBUTIONS:")
    lines.append(summary if summary else "(none)")
    lines.append("")
    lines.append("Respond with ONLY the JSON object.")
    return "\n".join(lines)


def build_react_system_prompt(tools: "ToolRegistry") -> str:
    """System prompt that turns the model into a ReAct tool-user."""
    schemas = json.dumps(tools.schemas(), indent=2)
    return f"""You are Guardian, an anti-scam decision agent for elderly banking users.
You evaluate a TRIGGER event plus CONTEXT and decide a risk score.

You can CALL TOOLS to gather evidence before deciding. The available tools are:

{schemas}

RESPONSE GRAMMAR — every reply MUST be exactly one of:

  <tool>{{"name": "<tool_name>", "args": {{...}}}}</tool>
  <final>{{"risk": <0-1>, "tactics": [...], "reasons": [...], "confidence": <0-1>}}</final>

Rules:
- Emit exactly ONE tag per reply. No prose outside the tag.
- After each <tool> call, the next user message will contain an <observation>
  tag with JSON results. Use it to decide your next action.
- Prefer to run 1–3 tools when the trigger is ambiguous; skip tools when the
  signal is already obvious.
- For bank transfers, you should  ALWAYS check the beneficiary's name and account number against the user's transaction history.
- Maximum 5 tool calls per decision — after that you MUST emit <final>.
- The "tactics" field in <final> must come from this set:
  authority_impersonation, urgency, isolation, payment_redirect,
  investment_scam, romance_scam, courier_scam, credential_theft,
  temporal_correlation, atypical_payee, unverified_link.
- "reasons" are short plain-language sentences (≤ 12 words, elderly-friendly).
- Never invent facts not present in input or tool observations.
"""


def _describe_event(e: ScamEvent) -> str:
    if isinstance(e, CallEvent):
        return f'Call from "{e.from_}" — transcript: "{_trim(e.transcript)}"'
    if isinstance(e, SmsEvent):
        return f'SMS from "{e.from_}" — body: "{_trim(e.body)}"'
    if isinstance(e, ChatEvent):
        return f'Chat from "{e.contact}" — body: "{_trim(e.body)}"'
    if isinstance(e, TransactionEvent):
        new_tag = ", NEW recipient" if e.new_recipient else ""
        return (
            f"Transfer attempt: HKD {e.amount_hkd:.0f} → "
            f'"{e.to_name}" ({e.to_account}){new_tag}'
        )
    return f"<unknown event {e.id}>"


def _trim(s: str, max_len: int = 220) -> str:
    clean = s.replace("\n", " ").strip()
    return clean if len(clean) <= max_len else clean[:max_len] + "…"
