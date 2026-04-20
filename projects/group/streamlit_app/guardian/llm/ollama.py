"""Ollama ChatOpenAI runtime adapter.

Port of ``app/lib/llm/ollama_runtime.dart``. Uses ``langchain-openai``'s
``ChatOpenAI`` against Ollama's OpenAI-compatible API. Agent structure,
tools, and structured output live under ``guardian.agents``.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI

from guardian.llm.prompts import (
    RISK_SYSTEM_PROMPT,
    build_risk_prompt,
)
from guardian.llm.runtime import LlmRiskOutput, LlmRuntime
from guardian.llm.tools import ToolCallStep, ToolRegistry, TraceCallback

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
API_KEY = os.environ.get("OLLAMA_API_KEY", "ollama")


def _openai_base_url(endpoint: str) -> str:
    endpoint = endpoint.rstrip("/")
    if endpoint.endswith(("/v1", "/api/v1")):
        return endpoint
    return f"{endpoint}/v1"


class OllamaLlmRuntime(LlmRuntime):
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        endpoint: str = DEFAULT_ENDPOINT,
        chat_model: ChatOpenAI | None = None,
    ) -> None:
        self.model = model
        self.endpoint = endpoint.rstrip("/")
        self.base_url = _openai_base_url(endpoint)
        self._chat_model = chat_model
        self._warm = False

    @property
    def ready(self) -> bool:
        return self._warm

    @property
    def name(self) -> str:
        return f"ollama/{self.model}" if "/" in self.model else self.model

    def is_reachable(self, timeout: float = 2.0) -> bool:
        try:
            with urllib.request.urlopen(
                f"{self.base_url}/models",
                timeout=timeout,
            ) as response:
                body = json.loads(response.read().decode("utf-8"))
            models = [_model_name(m) for m in body.get("data", [])]
            prefix = self.model.split(":")[0]
            return any(m.startswith(prefix) for m in models)
        except (OSError, urllib.error.URLError, ValueError) as e:
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
        snapshot: ContextSnapshot,
        rule_score: float,
        rule_contributions: list[RuleScoreContribution],
        tools: ToolRegistry | None,
        trace_callback: TraceCallback | None = None,
    ) -> LlmRiskOutput:
        if tools is not None:
            from guardian.agents.risk_langchain_agent import (
                score_risk_with_langchain_agent,
            )

            return score_risk_with_langchain_agent(
                model=self.chat_model(timeout=DEFAULT_TIMEOUT),
                model_name=self.name,
                snapshot=snapshot,
                rule_score=rule_score,
                rule_contributions=rule_contributions,
                tools=tools,
                trace_callback=trace_callback,
            )
        return self._score_risk_single_shot(
            snapshot=snapshot,
            rule_score=rule_score,
            rule_contributions=rule_contributions,
            trace_callback=trace_callback,
        )

    def _score_risk_single_shot(
        self,
        *,
        snapshot: ContextSnapshot,
        rule_score: float,
        rule_contributions: list[RuleScoreContribution],
        trace_callback: TraceCallback | None = None,
    ) -> LlmRiskOutput:
        prompt = build_risk_prompt(
            snapshot=snapshot,
            rule_score=rule_score,
            rule_contributions=rule_contributions,
        )
        if trace_callback is not None:
            trace_callback("HUMAN", "Received risk prompt", prompt)
            trace_callback("THINKING", "Single-shot LLM risk scoring started", None)
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
        if trace_callback is not None:
            trace_callback("FINAL", "LLM returned structured risk JSON", content)
        return self._build_output(parsed, rule_score, trace=[])

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
        tactics = (
            [t for t in tactics_raw if isinstance(t, str)]
            if isinstance(tactics_raw, list)
            else []
        )
        reasons_raw = parsed.get("reasons", [])
        reasons = (
            [r for r in reasons_raw if isinstance(r, str)]
            if isinstance(reasons_raw, list)
            else []
        )
        conf = float(parsed.get("confidence", 0.5))
        conf = max(0.0, min(1.0, conf))
        source = self.name if not trace else f"{self.name}+agent"
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
        snapshot: ContextSnapshot,
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
        response = self._model(timeout=timeout, json_mode=json_mode).invoke(
            messages,
        )
        return _message_content_to_text(response)

    def chat_model(self, *, timeout: float = DEFAULT_TIMEOUT) -> ChatOpenAI:
        return self._model(timeout=timeout)

    def _model(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        json_mode: bool = False,
    ) -> ChatOpenAI:
        if self._chat_model is not None:
            return self._chat_model
        extra_body: dict[str, Any] = {
            "keep_alive": KEEP_ALIVE,
            "options": {"num_ctx": 2048},
        }
        if json_mode:
            extra_body["format"] = "json"
        return ChatOpenAI(
            model=self.model,
            base_url=self.base_url,
            api_key=API_KEY,
            timeout=timeout,
            temperature=0.1,
            extra_body=extra_body,
        )

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


def _model_name(model: Any) -> str:
    name = getattr(model, "id", None) or getattr(model, "name", None)
    if isinstance(name, str):
        return name
    if isinstance(model, dict):
        raw = model.get("id") or model.get("name") or model.get("key")
        return raw if isinstance(raw, str) else ""
    dump = getattr(model, "model_dump", None)
    if callable(dump):
        data = dump()
        raw = data.get("id") or data.get("name") or data.get("key")
        return raw if isinstance(raw, str) else ""
    return ""


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
