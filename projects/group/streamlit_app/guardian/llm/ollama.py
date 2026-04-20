"""Ollama HTTP client with optional ReAct tool-calling loop.

Port of ``app/lib/llm/ollama_runtime.dart``. Uses the ``/api/chat`` JSON
endpoint with ``format: json`` when single-shot, and parses the
``<tool>…</tool>`` / ``<final>…</final>`` grammar when tools are provided.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import requests

from guardian.llm.prompts import (
    RISK_SYSTEM_PROMPT,
    build_react_system_prompt,
    build_risk_prompt,
)
from guardian.llm.runtime import LlmRiskOutput, LlmRuntime
from guardian.llm.tools import ToolCallStep, ToolRegistry, timed_call

if TYPE_CHECKING:  # pragma: no cover
    from guardian.agents.context_agent import ContextSnapshot
    from guardian.agents.risk_agent import RuleScoreContribution


log = logging.getLogger(__name__)


DEFAULT_ENDPOINT = os.environ.get("OLLAMA_ENDPOINT", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# Single inference timeout. 120s covers llama3.2:3b on a moderately loaded
# CPU (p95 ~90s under concurrent demo load; p50 ~20s on an idle box).
# Override with ``OLLAMA_TIMEOUT`` — bump to 300+ on slow laptops,
# drop to 30 with a GPU.
DEFAULT_TIMEOUT = _env_float("OLLAMA_TIMEOUT", 120.0)
WARMUP_TIMEOUT = _env_float("OLLAMA_WARMUP_TIMEOUT", 60.0)

# Keep the model resident between calls so we don't pay cold-load on every
# scenario event. Ollama default is 5 minutes.
KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "15m")


@dataclass
class _ToolCall:
    name: str
    args: dict[str, Any]


@dataclass
class _FinalAnswer:
    json_obj: dict[str, Any]


class OllamaLlmRuntime(LlmRuntime):
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        endpoint: str = DEFAULT_ENDPOINT,
        session: requests.Session | None = None,
    ) -> None:
        self.model = model
        self.endpoint = endpoint.rstrip("/")
        self._session = session or requests.Session()
        self._warm = False

    @property
    def ready(self) -> bool:
        return self._warm

    @property
    def name(self) -> str:
        return f"ollama/{self.model}"

    def is_reachable(self, timeout: float = 2.0) -> bool:
        try:
            r = self._session.get(f"{self.endpoint}/api/tags", timeout=timeout)
            if r.status_code != 200:
                return False
            body = r.json()
            models = [m.get("name", "") for m in body.get("models", [])]
            prefix = self.model.split(":")[0]
            return any(m.startswith(prefix) for m in models)
        except Exception as e:
            log.info("ollama not reachable: %s", e)
            return False

    def warmup(self) -> None:
        if self._warm:
            return
        try:
            self._chat(
                messages=[
                    {"role": "system", "content": "You are a JSON-only assistant."},
                    {"role": "user", "content": 'Reply with {"ok": true}'},
                ],
                timeout=WARMUP_TIMEOUT,
            )
            self._warm = True
            log.info("ollama warmed up: %s", self.model)
        except Exception as e:
            log.warning("ollama warmup failed: %s", e)

    # -- scoring -------------------------------------------------------------

    def score_risk(
        self,
        *,
        snapshot: "ContextSnapshot",
        rule_score: float,
        rule_contributions: list["RuleScoreContribution"],
        tools: "ToolRegistry | None",
    ) -> LlmRiskOutput:
        if tools is not None:
            return self._score_risk_react(
                snapshot=snapshot,
                rule_score=rule_score,
                rule_contributions=rule_contributions,
                tools=tools,
            )
        return self._score_risk_single_shot(
            snapshot=snapshot,
            rule_score=rule_score,
            rule_contributions=rule_contributions,
        )

    def _score_risk_single_shot(
        self,
        *,
        snapshot: "ContextSnapshot",
        rule_score: float,
        rule_contributions: list["RuleScoreContribution"],
    ) -> LlmRiskOutput:
        prompt = build_risk_prompt(
            snapshot=snapshot,
            rule_score=rule_score,
            rule_contributions=rule_contributions,
        )
        # Single attempt: on timeout the server may still be mid-inference,
        # so a local retry stacks another request on a busy worker and makes
        # things worse. SmartLlmRuntime handles retries across calls via its
        # cooldown state machine.
        content = self._chat(
            messages=[
                {"role": "system", "content": RISK_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            json_mode=True,
            timeout=DEFAULT_TIMEOUT,
        )
        parsed = self._extract_json(content)
        if parsed is None:
            raise RuntimeError("Ollama returned invalid JSON")
        return self._build_output(parsed, rule_score, trace=[])

    def _score_risk_react(
        self,
        *,
        snapshot: "ContextSnapshot",
        rule_score: float,
        rule_contributions: list["RuleScoreContribution"],
        tools: ToolRegistry,
        max_steps: int = 4,
    ) -> LlmRiskOutput:
        system = build_react_system_prompt(tools)
        user_prompt = build_risk_prompt(
            snapshot=snapshot,
            rule_score=rule_score,
            rule_contributions=rule_contributions,
        )
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ]

        trace: list[ToolCallStep] = []
        final_json: dict[str, Any] | None = None
        last_content: str | None = None

        for step in range(max_steps + 1):
            if final_json is not None:
                break
            if step == max_steps:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "You have reached the tool-call budget. "
                            "Emit <final>{...}</final> now with your best verdict."
                        ),
                    }
                )
            try:
                content = self._chat(messages=messages, timeout=DEFAULT_TIMEOUT)
            except Exception as e:
                log.warning("ollama ReAct step %d chat failed: %s", step, e)
                break
            last_content = content
            parsed = self._parse_react_turn(content)

            if isinstance(parsed, _FinalAnswer):
                final_json = parsed.json_obj
                break

            if isinstance(parsed, _ToolCall):
                tool = tools.find(parsed.name)
                if tool is None:
                    log.info("[react] step %d: unknown tool '%s'", step, parsed.name)
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                '<observation>{"error": "unknown tool: '
                                f'{parsed.name}"}}</observation>'
                            ),
                        }
                    )
                    continue
                step_record = timed_call(tool, parsed.args)
                trace.append(step_record)
                log.info(
                    "[react] step %d → %s(%s) → %s (%dms)",
                    step,
                    parsed.name,
                    json.dumps(parsed.args),
                    json.dumps(step_record.result),
                    step_record.latency_ms,
                )
                messages.append({"role": "assistant", "content": content})
                messages.append(
                    {
                        "role": "user",
                        "content": f"<observation>{json.dumps(step_record.result)}</observation>",
                    }
                )
                continue

            # Neither tag — try to salvage a JSON verdict, else nudge.
            salvage = self._extract_json(content)
            if salvage is not None:
                final_json = salvage
                break
            messages.append({"role": "assistant", "content": content})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Invalid format. Respond ONLY with <tool>...</tool> or "
                        "<final>...</final>."
                    ),
                }
            )

        if final_json is None and last_content is not None:
            final_json = self._extract_json(last_content)
        if final_json is None:
            raise RuntimeError("Ollama ReAct loop did not converge on a final answer")
        return self._build_output(final_json, rule_score, trace=trace)

    def _build_output(
        self,
        parsed: dict[str, Any],
        rule_score: float,
        *,
        trace: list[ToolCallStep],
    ) -> LlmRiskOutput:
        risk = float(parsed.get("risk", rule_score))
        risk = max(0.0, min(1.0, risk))
        tactics_raw = parsed.get("tactics", [])
        tactics = [t for t in tactics_raw if isinstance(t, str)] if isinstance(tactics_raw, list) else []
        reasons_raw = parsed.get("reasons", [])
        reasons = [r for r in reasons_raw if isinstance(r, str)] if isinstance(reasons_raw, list) else []
        conf = float(parsed.get("confidence", 0.5))
        conf = max(0.0, min(1.0, conf))
        source = self.name if not trace else f"{self.name}+react"
        return LlmRiskOutput(
            risk=risk,
            tactics=tactics,
            reasons=reasons,
            confidence=conf,
            source=source,
            trace=trace,
        )

    def explain(
        self,
        *,
        snapshot: "ContextSnapshot",
        final_risk: float,
    ) -> str:
        user = (
            "Summarise in one short plain-language sentence (max 18 words) why "
            f"the following situation has a risk of {int(final_risk * 100)}%. "
            "Be gentle and elderly-friendly. Do not use technical jargon.\n\n"
            + build_risk_prompt(
                snapshot=snapshot,
                rule_score=final_risk,
                rule_contributions=[],
            )
        )
        content = self._chat(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You write one short, kind, plain-language sentence for an "
                        "elderly banking user. No preface, no markdown."
                    ),
                },
                {"role": "user", "content": user},
            ],
            timeout=DEFAULT_TIMEOUT,
        )
        return content.strip()

    # -- HTTP wire + parsers -------------------------------------------------

    def _chat(
        self,
        *,
        messages: list[dict[str, str]],
        json_mode: bool = False,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> str:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "keep_alive": KEEP_ALIVE,
            "options": {"temperature": 0.1, "num_ctx": 2048},
        }
        if json_mode:
            body["format"] = "json"
        r = self._session.post(
            f"{self.endpoint}/api/chat",
            json=body,
            timeout=timeout,
        )
        if r.status_code != 200:
            raise RuntimeError(f"ollama http {r.status_code}: {r.text}")
        decoded = r.json()
        msg = decoded.get("message") or {}
        return msg.get("content", "") or ""

    @staticmethod
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

    _TOOL_RE = re.compile(r"<tool>\s*(\{[\s\S]*?\})\s*</tool>")
    _FINAL_RE = re.compile(r"<final>\s*(\{[\s\S]*?\})\s*</final>")

    @classmethod
    def _parse_react_turn(cls, raw: str) -> _ToolCall | _FinalAnswer | None:
        m = cls._TOOL_RE.search(raw)
        if m:
            try:
                obj = json.loads(m.group(1))
            except Exception:
                return None
            name = obj.get("name")
            if not isinstance(name, str) or not name:
                return None
            args = obj.get("args") or {}
            if not isinstance(args, dict):
                args = {}
            return _ToolCall(name=name, args=args)
        m = cls._FINAL_RE.search(raw)
        if m:
            try:
                obj = json.loads(m.group(1))
            except Exception:
                return None
            if isinstance(obj, dict):
                return _FinalAnswer(json_obj=obj)
        return None
