"""Scam-signal provider abstraction.

This module decouples *where* scam signals come from (local CSV / external service)
from *how* the agent consumes them (rules + LangChain tools).

The provider returns small JSON-serialisable dicts so they can be passed straight
into the existing tool/audit tracing.
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bank_mcp.db import BankReviewRepository
from guardian.data.scam_db import ScamDatabase, ScamEntry, ScamEntryType
from guardian.paths import SCAM_DB_RUNTIME_CSV

log = logging.getLogger(__name__)


class ScamSignalProvider(ABC):
    @abstractmethod
    def lookup_number(self, number: str) -> dict[str, Any]: ...

    @abstractmethod
    def check_domain(self, text: str) -> dict[str, Any]: ...

    @abstractmethod
    def search_keywords(self, text: str) -> dict[str, Any]: ...

    @abstractmethod
    def check_beneficiary_for_bank_transfer(
        self,
        recipient_name: str,
        account_number: str,
    ) -> dict[str, Any]: ...

    @abstractmethod
    def report_beneficiary_risk_for_bank_transfer(
        self,
        *,
        account_number: str,
        reason_code: str,
        recipient_name: str | None = None,
        case_id: str | None = None,
    ) -> dict[str, Any]: ...

    @abstractmethod
    def update_scamdatabase_number(
        self,
        *,
        number: str,
        risk: float,
        reason: str,
        event_id: str,
        source_model: str,
        weight: float = 0.6,
        tag: str = "auto_detected",
    ) -> dict[str, Any]: ...


class ScamDbProvider(ScamSignalProvider):
    """Local provider backed by the in-memory :class:`ScamDatabase`."""

    def __init__(self, db: ScamDatabase, runtime_csv: Path = SCAM_DB_RUNTIME_CSV) -> None:
        self._db = db
        self._runtime_csv = Path(runtime_csv)
        self._bank_review = BankReviewRepository()
        try:
            self._bank_review.initialize()
        except RuntimeError as exc:
            log.warning("bank review fallback unavailable: %s", exc)

    def lookup_number(self, number: str) -> dict[str, Any]:
        raw = (number or "").lower()
        for entry in self._db.bad_numbers():
            if entry.value in raw:
                return {
                    "hit": True,
                    "match": entry.value,
                    "tag": entry.tag,
                    "weight": entry.weight,
                    "note": entry.note,
                    "source": "local",
                }
        return {"hit": False, "source": "local"}

    def check_domain(self, text: str) -> dict[str, Any]:
        lower = (text or "").lower()
        matches: list[dict[str, Any]] = []
        for domain in self._db.bad_domains():
            if domain.value in lower:
                matches.append(
                    {
                        "domain": domain.value,
                        "tag": domain.tag,
                        "weight": domain.weight,
                        "note": domain.note,
                    }
                )
        return {"hit": bool(matches), "matches": matches, "source": "local"}

    def search_keywords(self, text: str) -> dict[str, Any]:
        lower = (text or "").lower()
        hits: list[dict[str, Any]] = []
        total = 0.0
        for keyword in self._db.keywords():
            if keyword.value in lower:
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
            "source": "local",
        }

    def check_beneficiary_for_bank_transfer(
        self,
        recipient_name: str,
        account_number: str,
    ) -> dict[str, Any]:
        result = self._bank_review.check_beneficiary(
            recipient_name=recipient_name,
            account_number=account_number,
        )
        out = result.to_dict()
        out["source"] = "local_bank_review"
        return out

    def report_beneficiary_risk_for_bank_transfer(
        self,
        *,
        account_number: str,
        reason_code: str,
        recipient_name: str | None = None,
        case_id: str | None = None,
    ) -> dict[str, Any]:
        result = self._bank_review.report_beneficiary_risk(
            account_number=account_number,
            recipient_name=recipient_name,
            reason_code=reason_code,
            case_id=case_id,
            source_type="local_fallback",
            created_by="scam_signals_local",
        )
        out = result.to_dict()
        out["source"] = "local_bank_review"
        return out

    def update_scamdatabase_number(
        self,
        *,
        number: str,
        risk: float,
        reason: str,
        event_id: str,
        source_model: str,
        weight: float = 0.6,
        tag: str = "auto_detected",
    ) -> dict[str, Any]:
        raw_number = (number or "").strip().lower()
        normalized = _normalize_number_key(raw_number)
        if not normalized:
            return {"status": "rejected", "source": "local", "reason": "invalid_number"}

        for entry in self._db.bad_numbers():
            if _normalize_number_key(entry.value) == normalized:
                return {
                    "status": "duplicate",
                    "source": "local",
                    "number": entry.value,
                }

        self._runtime_csv.parent.mkdir(parents=True, exist_ok=True)
        if not self._runtime_csv.exists():
            self._runtime_csv.write_text("type,value,weight,tag,note\n", encoding="utf-8")

        note = (
            f"auto-added {datetime.now(UTC).isoformat()} "
            f"event={event_id} model={source_model} risk={risk:.3f} reason={reason}"
        )
        with self._runtime_csv.open("a", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "number",
                    raw_number,
                    f"{max(0.0, min(1.0, float(weight))):.3f}",
                    tag.strip() or "auto_detected",
                    note,
                ]
            )

        self._db.entries.append(
            ScamEntry(
                type=ScamEntryType.NUMBER,
                value=raw_number,
                weight=max(0.0, min(1.0, float(weight))),
                tag=tag.strip() or "auto_detected",
                note=note,
            )
        )
        return {
            "status": "accepted",
            "source": "local",
            "number": raw_number,
            "stored_in": str(self._runtime_csv),
        }


class McpScamClient(ScamSignalProvider):
    """MCP client for the scam-signal server over streamable HTTP."""

    def __init__(self, endpoint: str, *, timeout_s: float = 3.0) -> None:
        self.endpoint = _normalize_streamable_http_endpoint(endpoint)
        self.timeout_s = timeout_s

    def lookup_number(self, number: str) -> dict[str, Any]:
        return self._call_tool("lookup_number", {"number": number})

    def check_domain(self, text: str) -> dict[str, Any]:
        return self._call_tool("check_domain", {"text": text})

    def search_keywords(self, text: str) -> dict[str, Any]:
        return self._call_tool("search_keywords", {"text": text})

    def check_beneficiary_for_bank_transfer(
        self,
        recipient_name: str,
        account_number: str,
    ) -> dict[str, Any]:
        return {
            "name_account_check": "unknown",
            "reported_risk_status": "unknown",
            "source": "mcp",
            "fallback": "not_supported_by_scam_mcp",
        }

    def report_beneficiary_risk_for_bank_transfer(
        self,
        *,
        account_number: str,
        reason_code: str,
        recipient_name: str | None = None,
        case_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "status": "rejected",
            "report_id": "",
            "source": "mcp",
            "fallback": "not_supported_by_scam_mcp",
        }

    def update_scamdatabase_number(
        self,
        *,
        number: str,
        risk: float,
        reason: str,
        event_id: str,
        source_model: str,
        weight: float = 0.6,
        tag: str = "auto_detected",
    ) -> dict[str, Any]:
        return self._call_tool(
            "update_scamdatabase_number",
            {
                "number": number,
                "risk": risk,
                "reason": reason,
                "event_id": event_id,
                "source_model": source_model,
                "weight": weight,
                "tag": tag,
            },
        )

    def _call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return asyncio.run(self._call_tool_async(tool_name, arguments))

    async def _call_tool_async(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async with streamable_http_client(self.endpoint) as (
            read_stream,
            write_stream,
            _,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await asyncio.wait_for(session.initialize(), timeout=self.timeout_s)
                result = await asyncio.wait_for(
                    session.call_tool(
                        tool_name,
                        arguments={k: v for k, v in arguments.items() if v is not None},
                    ),
                    timeout=self.timeout_s,
                )
                return _parse_mcp_tool_result(
                    result=result,
                    source="mcp",
                    tool_name=tool_name,
                )


class McpBankReviewClient:
    """MCP client for the bank transfer beneficiary review server."""

    def __init__(self, endpoint: str, *, timeout_s: float = 5.0) -> None:
        self.endpoint = _normalize_streamable_http_endpoint(endpoint)
        self.timeout_s = timeout_s

    def check_beneficiary_for_bank_transfer(
        self,
        recipient_name: str,
        account_number: str,
    ) -> dict[str, Any]:
        return self._call_tool(
            "check_beneficiary_for_bank_transfer",
            {
                "recipient_name": recipient_name,
                "account_number": account_number,
            },
        )

    def report_beneficiary_risk_for_bank_transfer(
        self,
        *,
        account_number: str,
        reason_code: str,
        recipient_name: str | None = None,
        case_id: str | None = None,
    ) -> dict[str, Any]:
        return self._call_tool(
            "report_beneficiary_risk_for_bank_transfer",
            {
                "account_number": account_number,
                "reason_code": reason_code,
                "recipient_name": recipient_name,
                "case_id": case_id,
            },
        )

    def _call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return asyncio.run(self._call_tool_async(tool_name, arguments))

    async def _call_tool_async(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async with streamable_http_client(self.endpoint) as (
            read_stream,
            write_stream,
            _,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await asyncio.wait_for(session.initialize(), timeout=self.timeout_s)
                result = await asyncio.wait_for(
                    session.call_tool(
                        tool_name,
                        arguments={k: v for k, v in arguments.items() if v is not None},
                    ),
                    timeout=self.timeout_s,
                )
                return _parse_mcp_tool_result(
                    result=result,
                    source="bank_review_mcp",
                    tool_name=tool_name,
                )


class FallbackProvider(ScamSignalProvider):
    """Try MCP first; fall back to local provider on any failure."""

    def __init__(
        self,
        *,
        mcp: ScamSignalProvider,
        local: ScamSignalProvider,
        bank_review_mcp: McpBankReviewClient | None = None,
        strict: bool = False,
    ) -> None:
        self._mcp = mcp
        self._local = local
        self._bank_review_mcp = bank_review_mcp
        self._strict = strict

    def lookup_number(self, number: str) -> dict[str, Any]:
        try:
            return self._mcp.lookup_number(number)
        except Exception:
            if self._strict:
                raise
            out = self._local.lookup_number(number)
            if isinstance(out, dict):
                out["fallback"] = "local"
            return out

    def check_domain(self, text: str) -> dict[str, Any]:
        try:
            return self._mcp.check_domain(text)
        except Exception:
            if self._strict:
                raise
            out = self._local.check_domain(text)
            if isinstance(out, dict):
                out["fallback"] = "local"
            return out

    def search_keywords(self, text: str) -> dict[str, Any]:
        try:
            return self._mcp.search_keywords(text)
        except Exception:
            if self._strict:
                raise
            out = self._local.search_keywords(text)
            if isinstance(out, dict):
                out["fallback"] = "local"
            return out

    def check_beneficiary_for_bank_transfer(
        self,
        recipient_name: str,
        account_number: str,
    ) -> dict[str, Any]:
        if self._bank_review_mcp is None:
            return self._local.check_beneficiary_for_bank_transfer(
                recipient_name,
                account_number,
            )
        try:
            return self._bank_review_mcp.check_beneficiary_for_bank_transfer(
                recipient_name,
                account_number,
            )
        except Exception:
            if self._strict:
                raise
            out = self._local.check_beneficiary_for_bank_transfer(
                recipient_name,
                account_number,
            )
            if isinstance(out, dict):
                out["fallback"] = "local"
            return out

    def report_beneficiary_risk_for_bank_transfer(
        self,
        *,
        account_number: str,
        reason_code: str,
        recipient_name: str | None = None,
        case_id: str | None = None,
    ) -> dict[str, Any]:
        if self._bank_review_mcp is None:
            return self._local.report_beneficiary_risk_for_bank_transfer(
                account_number=account_number,
                reason_code=reason_code,
                recipient_name=recipient_name,
                case_id=case_id,
            )
        try:
            return self._bank_review_mcp.report_beneficiary_risk_for_bank_transfer(
                account_number=account_number,
                reason_code=reason_code,
                recipient_name=recipient_name,
                case_id=case_id,
            )
        except Exception:
            if self._strict:
                raise
            out = self._local.report_beneficiary_risk_for_bank_transfer(
                account_number=account_number,
                reason_code=reason_code,
                recipient_name=recipient_name,
                case_id=case_id,
            )
            if isinstance(out, dict):
                out["fallback"] = "local"
            return out

    def update_scamdatabase_number(
        self,
        *,
        number: str,
        risk: float,
        reason: str,
        event_id: str,
        source_model: str,
        weight: float = 0.6,
        tag: str = "auto_detected",
    ) -> dict[str, Any]:
        try:
            return self._mcp.update_scamdatabase_number(
                number=number,
                risk=risk,
                reason=reason,
                event_id=event_id,
                source_model=source_model,
                weight=weight,
                tag=tag,
            )
        except Exception:
            if self._strict:
                raise
            out = self._local.update_scamdatabase_number(
                number=number,
                risk=risk,
                reason=reason,
                event_id=event_id,
                source_model=source_model,
                weight=weight,
                tag=tag,
            )
            if isinstance(out, dict):
                out["fallback"] = "local"
            return out


def _normalize_streamable_http_endpoint(endpoint: str) -> str:
    base = endpoint.strip().rstrip("/")
    if not base:
        return base
    if base.endswith("/mcp"):
        return base
    return f"{base}/mcp"


def _parse_mcp_tool_result(
    *,
    result: Any,
    source: str,
    tool_name: str,
) -> dict[str, Any]:
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        structured.setdefault("source", source)
        return structured

    content = getattr(result, "content", None)
    if isinstance(content, list) and content:
        text = getattr(content[0], "text", None)
        if isinstance(text, str):
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                parsed.setdefault("source", source)
                return parsed
    raise RuntimeError(f"Unexpected MCP tool result for {tool_name}")


def _normalize_number_key(number: str) -> str:
    return "".join(ch for ch in number if ch.isdigit() or ch == "+")
