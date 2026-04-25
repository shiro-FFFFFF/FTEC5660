"""SQLite storage for the bank transfer review MCP server."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from guardian.paths import DATA_DIR

from .utils import (
    classify_name_match,
    hash_account_number,
    mask_account_number,
    normalize_name,
)

log = logging.getLogger(__name__)

DEFAULT_DB_PATH = DATA_DIR / "bank_transfer_review.db"

REPORT_SEVERITY_BY_REASON = {
    "suspected_scam": "medium",
    "confirmed_fraud": "high",
    "customer_dispute": "medium",
    "manual_review": "low",
}
VALID_REASON_CODES = set(REPORT_SEVERITY_BY_REASON)


@dataclass(frozen=True)
class BeneficiaryCheckResult:
    name_account_check: str
    reported_risk_status: str

    def to_dict(self) -> dict[str, str]:
        return {
            "name_account_check": self.name_account_check,
            "reported_risk_status": self.reported_risk_status,
        }


@dataclass(frozen=True)
class ReportResult:
    status: str
    report_id: str

    def to_dict(self) -> dict[str, str]:
        return {"status": self.status, "report_id": self.report_id}


class BankReviewRepository:
    """Small SQLite repository for bank transfer beneficiary review."""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        """Create the SQLite database, schema, and seed data if missing."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.connect() as conn:
                conn.executescript(_SCHEMA_SQL)
                conn.commit()
                self._seed_if_empty(conn)
        except sqlite3.Error as exc:
            raise RuntimeError(f"Failed to initialize SQLite database: {exc}") from exc

    def check_beneficiary(
        self,
        *,
        recipient_name: str,
        account_number: str,
    ) -> BeneficiaryCheckResult:
        """Check name/account alignment and prior risk for bank transfer review."""
        if not account_number.strip():
            return BeneficiaryCheckResult("unknown", "unknown")
        if not recipient_name.strip():
            return BeneficiaryCheckResult("unknown", "unknown")

        account_hash = hash_account_number(account_number)
        try:
            with self.connect() as conn:
                registry_row = conn.execute(
                    """
                    SELECT official_name_norm, official_name_raw, alias_names_json, account_status
                    FROM beneficiary_registry
                    WHERE account_number_hash = ?
                    """,
                    (account_hash,),
                ).fetchone()
                if registry_row is None:
                    return BeneficiaryCheckResult(
                        "unknown", self._risk_status(conn, account_hash)
                    )

                if registry_row["account_status"] != "active":
                    return BeneficiaryCheckResult(
                        "unknown", self._risk_status(conn, account_hash)
                    )

                aliases = _parse_alias_json(registry_row["alias_names_json"])
                name_check = classify_name_match(
                    recipient_name,
                    registry_row["official_name_norm"]
                    or registry_row["official_name_raw"]
                    or "",
                    aliases,
                )
                risk_status = self._risk_status(conn, account_hash)
                return BeneficiaryCheckResult(name_check, risk_status)
        except sqlite3.Error as exc:
            log.exception("Bank transfer beneficiary check failed: %s", exc)
            return BeneficiaryCheckResult("unknown", "unknown")

    def report_beneficiary_risk(
        self,
        *,
        account_number: str,
        recipient_name: str | None,
        reason_code: str,
        case_id: str | None,
        source_type: str = "bank_transfer_review_mcp",
        created_by: str = "mcp_tool",
    ) -> ReportResult:
        """Record a suspicious beneficiary for bank transfer scam/risk review."""
        if not account_number.strip():
            return ReportResult("rejected", "")
        if reason_code not in VALID_REASON_CODES:
            return ReportResult("rejected", "")

        account_hash = hash_account_number(account_number)
        account_masked = mask_account_number(account_number)
        recipient_name_norm = normalize_name(recipient_name)
        severity = REPORT_SEVERITY_BY_REASON[reason_code]
        now = utc_now()

        try:
            with self.connect() as conn:
                duplicate_report_id = self._find_duplicate_report(
                    conn=conn,
                    account_number_hash=account_hash,
                    reason_code=reason_code,
                    case_id=(case_id or "").strip() or None,
                    recipient_name_norm=recipient_name_norm or None,
                    created_after=now - timedelta(days=7),
                )
                if duplicate_report_id is not None:
                    log.info(
                        "Duplicate bank transfer report skipped for %s", account_masked
                    )
                    return ReportResult("duplicate", str(duplicate_report_id))

                cursor = conn.execute(
                    """
                    INSERT INTO beneficiary_reports (
                        account_number_hash,
                        account_number_masked,
                        recipient_name_norm,
                        reason_code,
                        report_status,
                        severity,
                        source_type,
                        case_id,
                        evidence_note,
                        created_at,
                        created_by,
                        updated_at
                    ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        account_hash,
                        account_masked,
                        recipient_name_norm or None,
                        reason_code,
                        severity,
                        source_type,
                        (case_id or "").strip() or None,
                        _default_evidence_note(reason_code, recipient_name_norm),
                        now.isoformat(),
                        created_by,
                        now.isoformat(),
                    ),
                )
                conn.commit()
                report_id = str(cursor.lastrowid or "")
                log.info(
                    "Accepted bank transfer risk report %s for %s",
                    report_id,
                    account_masked,
                )
                return ReportResult("accepted", report_id)
        except sqlite3.IntegrityError:
            log.info("Duplicate bank transfer report blocked for %s", account_masked)
            return ReportResult("duplicate", "")
        except sqlite3.Error as exc:
            log.exception(
                "Failed to record bank transfer risk report for %s: %s",
                account_masked,
                exc,
            )
            return ReportResult("error", "")

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _seed_if_empty(self, conn: sqlite3.Connection) -> None:
        existing = conn.execute(
            "SELECT COUNT(*) AS count FROM beneficiary_registry"
        ).fetchone()
        if existing and int(existing["count"]) > 0:
            return

        now = utc_now().isoformat()
        registry_rows = [
            {
                "account_number": "123-456-789-001",
                "official_name_raw": "APEX SOLUTIONS LIMITED",
                "bank_code": "004",
                "aliases": ["APEX SOLUTIONS LTD", "APEX SOLUTIONS"],
            },
            {
                "account_number": "987-654-321-002",
                "official_name_raw": "CHAN TAI MAN COMPANY LIMITED",
                "bank_code": "012",
                "aliases": ["CHAN TAI MAN CO LTD", "C T M CO LTD"],
            },
            {
                "account_number": "555-666-777-003",
                "official_name_raw": "HARBOUR VIEW TRADING LTD",
                "bank_code": "388",
                "aliases": ["HARBOUR VIEW TRADING", "HARBOURVIEW TRADING LTD"],
            },
            {
                "account_number": "012-345678-999",
                "official_name_raw": "Unknown Ltd",
                "bank_code": "999",
                "aliases": ["unknown", "unknown ltd"],
            },
        ]
        for row in registry_rows:
            conn.execute(
                """
                INSERT INTO beneficiary_registry (
                    account_number_hash,
                    account_number_masked,
                    official_name_norm,
                    official_name_raw,
                    alias_names_json,
                    bank_code,
                    account_status,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    hash_account_number(row["account_number"]),
                    mask_account_number(row["account_number"]),
                    normalize_name(row["official_name_raw"]),
                    row["official_name_raw"],
                    json.dumps(row["aliases"]),
                    row["bank_code"],
                    now,
                    now,
                ),
            )

        report_rows = [
            {
                "account_number": "987-654-321-002",
                "recipient_name": "CHAN TAI MAN CO LTD",
                "reason_code": "suspected_scam",
                "severity": "medium",
                "case_id": "CASE-1001",
                "created_by": "seed",
            },
            {
                "account_number": "555-666-777-003",
                "recipient_name": "HARBOUR VIEW TRADING LTD",
                "reason_code": "confirmed_fraud",
                "severity": "high",
                "case_id": "CASE-2001",
                "created_by": "seed",
            },
            {
                "account_number": "555-666-777-003",
                "recipient_name": "HARBOUR VIEW TRADING LTD",
                "reason_code": "customer_dispute",
                "severity": "medium",
                "case_id": "CASE-2002",
                "created_by": "seed",
            },
            {
                "account_number": "012-345678-999",
                "recipient_name": "Unknown Ltd",
                "reason_code": "suspected_scam",
                "reason_code": "confirmed_fraud",
                "severity": "high",
                "case_id": "CASE-2003",
                "created_by": "seed",
            },
        ]
        for row in report_rows:
            conn.execute(
                """
                INSERT INTO beneficiary_reports (
                    account_number_hash,
                    account_number_masked,
                    recipient_name_norm,
                    reason_code,
                    report_status,
                    severity,
                    source_type,
                    case_id,
                    evidence_note,
                    created_at,
                    created_by,
                    updated_at
                ) VALUES (?, ?, ?, ?, 'active', ?, 'seed_data', ?, ?, ?, ?, ?)
                """,
                (
                    hash_account_number(row["account_number"]),
                    mask_account_number(row["account_number"]),
                    normalize_name(row["recipient_name"]),
                    row["reason_code"],
                    row["severity"],
                    row["case_id"],
                    "Seed data for local bank transfer review demo",
                    now,
                    row["created_by"],
                    now,
                ),
            )
        conn.commit()

    def _risk_status(self, conn: sqlite3.Connection, account_hash: str) -> str:
        rows = conn.execute(
            """
            SELECT severity
            FROM beneficiary_reports
            WHERE account_number_hash = ? AND report_status = 'active'
            """,
            (account_hash,),
        ).fetchall()
        if not rows:
            return "none"

        severities = [row["severity"] for row in rows]
        if "high" in severities or len(rows) >= 2:
            return "high_risk"
        return "reported"

    def _find_duplicate_report(
        self,
        *,
        conn: sqlite3.Connection,
        account_number_hash: str,
        reason_code: str,
        case_id: str | None,
        recipient_name_norm: str | None,
        created_after: datetime,
    ) -> int | None:
        if case_id:
            row = conn.execute(
                """
                SELECT report_id
                FROM beneficiary_reports
                WHERE account_number_hash = ?
                  AND reason_code = ?
                  AND IFNULL(case_id, '') = ?
                  AND created_at >= ?
                ORDER BY report_id DESC
                LIMIT 1
                """,
                (
                    account_number_hash,
                    reason_code,
                    case_id,
                    created_after.isoformat(),
                ),
            ).fetchone()
            return int(row["report_id"]) if row else None

        row = conn.execute(
            """
            SELECT report_id
            FROM beneficiary_reports
            WHERE account_number_hash = ?
              AND reason_code = ?
              AND IFNULL(recipient_name_norm, '') = ?
              AND created_at >= ?
            ORDER BY report_id DESC
            LIMIT 1
            """,
            (
                account_number_hash,
                reason_code,
                recipient_name_norm or "",
                created_after.isoformat(),
            ),
        ).fetchone()
        return int(row["report_id"]) if row else None


def utc_now() -> datetime:
    return datetime.now(UTC)


def _default_evidence_note(reason_code: str, recipient_name_norm: str) -> str:
    recipient_note = recipient_name_norm or "UNKNOWN BENEFICIARY"
    return f"Bank transfer review MCP report for {recipient_note} ({reason_code})."


def _parse_alias_json(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Malformed alias JSON in bank transfer registry row")
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data if isinstance(item, str)]


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS beneficiary_registry (
    beneficiary_id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_number_hash TEXT NOT NULL UNIQUE,
    account_number_masked TEXT NOT NULL,
    official_name_norm TEXT NOT NULL,
    official_name_raw TEXT,
    alias_names_json TEXT,
    bank_code TEXT,
    account_status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS beneficiary_reports (
    report_id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_number_hash TEXT NOT NULL,
    account_number_masked TEXT NOT NULL,
    recipient_name_norm TEXT,
    reason_code TEXT NOT NULL,
    report_status TEXT NOT NULL DEFAULT 'active',
    severity TEXT NOT NULL DEFAULT 'medium',
    source_type TEXT NOT NULL,
    case_id TEXT,
    evidence_note TEXT,
    created_at TEXT NOT NULL,
    created_by TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_beneficiary_registry_account_hash
ON beneficiary_registry(account_number_hash);

CREATE INDEX IF NOT EXISTS idx_beneficiary_reports_account_hash
ON beneficiary_reports(account_number_hash);

CREATE INDEX IF NOT EXISTS idx_beneficiary_reports_status
ON beneficiary_reports(report_status);

CREATE INDEX IF NOT EXISTS idx_beneficiary_reports_hash_status
ON beneficiary_reports(account_number_hash, report_status);
"""
