"""Small RAG smoke test for the anti-scam knowledge base.

Usage:

    python streamlit_app/tools/test_rag_search.py
    python -m streamlit_app.tools.test_rag_search

This script assumes LM Studio embedding env vars are configured when RAG
is enabled. It keeps ``top_k`` small and checks that highly specific
queries retrieve the expected documents from the local knowledge base.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

# Make ``guardian`` importable when run as a file.
_SELF = Path(__file__).resolve()
sys.path.insert(0, str(_SELF.parents[1]))  # streamlit_app/

from guardian.rag.build_index import build_index  # noqa: E402
from guardian.rag.config import load_config  # noqa: E402
from guardian.rag.retriever import RagRetriever  # noqa: E402


@dataclass(frozen=True)
class RagSearchCase:
    name: str
    mode: str
    query: str
    top_k: int
    expected_doc_id: str


CASES = [
    RagSearchCase(
        name="scam pattern: fake police authority impersonation",
        mode="scam",
        query="police investigation cybercrime do not tell anyone safe account",
        top_k=2,
        expected_doc_id="scam_patterns/fake_police_authority_impersonation",
    ),
    RagSearchCase(
        name="scam pattern: romance investment trust building",
        mode="scam",
        query="vip tip guaranteed returns relationship builds trust over time exclusive opportunity",
        top_k=2,
        expected_doc_id="scam_patterns/romance_investment_pig_butchering",
    ),
    RagSearchCase(
        name="scam pattern: sms phishing delivery customs",
        mode="scam",
        query="parcel customs re-delivery fee suspicious link pay now non-official domain",
        top_k=2,
        expected_doc_id="scam_patterns/sms_phishing_delivery_customs",
    ),
    RagSearchCase(
        name="scam pattern: urgent transfer pressure",
        mode="scam",
        query="recent sms first-time recipient beneficiary previously reported urgent transfer request",
        top_k=2,
        expected_doc_id="scam_patterns/urgent_transfer_pressure",
    ),
    RagSearchCase(
        name="benign pattern: family transfer",
        mode="scam",
        query="routine support reimbursement familiar recipient clear explanation no suspicious links",
        top_k=2,
        expected_doc_id="benign_patterns/family_transfer_normal",
    ),
    RagSearchCase(
        name="benign pattern: utility bill payment",
        mode="scam",
        query="expected monthly cycle known biller ordinary amount routine payment behavior",
        top_k=2,
        expected_doc_id="benign_patterns/utility_bill_payment_normal",
    ),
    RagSearchCase(
        name="scenario note: sms phishing",
        mode="scam",
        query="scenario suspicious sms arrives urgency builds phishing-style wording transfer follows suspicious sms context",
        top_k=2,
        expected_doc_id="scenario_notes/01_sms_phishing",
    ),
    RagSearchCase(
        name="scenario note: voice police",
        mode="scam",
        query="scenario fake police call keep silent asset protection story transfer influenced by fear and authority",
        top_k=2,
        expected_doc_id="scenario_notes/02_voice_police",
    ),
    RagSearchCase(
        name="scenario note: romance investment",
        mode="scam",
        query="scenario extended chat builds trust investment narrative historical context matters more than any single event",
        top_k=2,
        expected_doc_id="scenario_notes/03_romance_investment",
    ),
    RagSearchCase(
        name="scenario note: urgent transfer",
        mode="scam",
        query="scenario temporal proximity between suspicious communication and transfer is highly important new or risky beneficiary details",
        top_k=2,
        expected_doc_id="scenario_notes/04_urgent_transfer",
    ),
    RagSearchCase(
        name="scenario note: benign family transfer",
        mode="scam",
        query="scenario ordinary conversation understandable transfer purpose avoid unnecessary friction when prior context is benign",
        top_k=2,
        expected_doc_id="scenario_notes/benign_01_family_transfer",
    ),
    RagSearchCase(
        name="scenario note: benign utility bill",
        mode="scam",
        query="scenario routine payment behavior expected context distinguish expected payment behavior from scam escalation",
        top_k=2,
        expected_doc_id="scenario_notes/benign_02_utility_bill",
    ),
    RagSearchCase(
        name="tactic: authority impersonation",
        mode="scam",
        query="government officer official case security team investigation authority pressure police",
        top_k=2,
        expected_doc_id="tactics/authority_impersonation",
    ),
    RagSearchCase(
        name="tactic: isolation secrecy",
        mode="scam",
        query="keep this confidential this is secret do not discuss this do not tell anyone",
        top_k=2,
        expected_doc_id="tactics/isolation_secrecy",
    ),
    RagSearchCase(
        name="tactic: payment redirection",
        mode="scam",
        query="transfer to this account instead updated beneficiary details holding account secure account",
        top_k=2,
        expected_doc_id="tactics/payment_redirection",
    ),
    RagSearchCase(
        name="tactic: urgency",
        mode="scam",
        query="urgent immediately final notice hurry act now",
        top_k=2,
        expected_doc_id="tactics/urgency",
    ),
    RagSearchCase(
        name="transfer guidance: beneficiary checks",
        mode="transfer",
        query="recipient name account number mismatch prior risk reports first time recipient",
        top_k=2,
        expected_doc_id="transfer_guidance/bank_transfer_beneficiary_checks",
    ),
    RagSearchCase(
        name="transfer guidance: contextual transfer risk",
        mode="transfer",
        query="transfer should not be judged in isolation trust-building chat history urgency or secrecy across channels",
        top_k=2,
        expected_doc_id="transfer_guidance/contextual_transfer_risk",
    ),
]


def main() -> int:
    config = load_config()
    if not config.enabled:
        print(
            json.dumps(
                {
                    "status": "disabled",
                    "message": config.message,
                },
                indent=2,
            )
        )
        return 2

    if not config.chroma_db_path.exists():
        print(f"RAG index missing at {config.chroma_db_path}. Building index first...")
        build_result = build_index()
        print(json.dumps(build_result, indent=2))
        if build_result.get("status") != "ok":
            return 1

    retriever = RagRetriever(config)
    failures: list[dict[str, object]] = []
    for case in CASES:
        result = _run_case(retriever, case)
        print(json.dumps(result, indent=2))
        if result["status"] != "ok":
            failures.append(result)

    if failures:
        print(
            f"\nRAG smoke test failed: {len(failures)} case(s) did not match expectations."
        )
        return 1

    print(
        f"\nRAG smoke test passed: {len(CASES)} case(s) ALL matched expected documents."
    )
    return 0


def _run_case(retriever: RagRetriever, case: RagSearchCase) -> dict[str, object]:
    if case.mode == "scam":
        result = retriever.retrieve_scam_patterns(query=case.query, top_k=case.top_k)
    else:
        result = retriever.retrieve_transfer_guidance(
            query=case.query, top_k=case.top_k
        )

    payload = result.to_dict()
    matches = payload.get("matches", [])
    matched_doc_ids = [
        match.get("doc_id") for match in matches if isinstance(match, dict)
    ]
    return {
        "case": case.name,
        "query": case.query,
        "top_k": case.top_k,
        "expected_doc_id": case.expected_doc_id,
        "matched_doc_ids": matched_doc_ids,
        "status": (
            "ok"
            if payload.get("status") == "ok" and case.expected_doc_id in matched_doc_ids
            else "error"
        ),
        "retrieval_status": payload.get("status"),
        "matches": matches,
        "message": payload.get("message"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
