"""LangChain tools for the anti-scam RAG subsystem."""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool

from guardian.rag.retriever import RagRetriever


@tool
def retrieve_scam_patterns(
    query: Annotated[
        str,
        "Specific scam-pattern retrieval query built from SMS, call, chat, or general "
        "scam context. Use concrete phrases, tactics, or scam narrative details.",
    ],
    top_k: Annotated[
        int | None,
        "Optional max number of matches to return. Use a small integer such as 1 to 5.",
    ] = None,
    category_filter: Annotated[
        str | None,
        "Optional extra category restriction within scam-pattern retrieval. "
        "Accepted values are scam_patterns, benign_patterns, tactics, or scenario_notes.",
    ] = None,
) -> dict:
    """Retrieve scam-pattern evidence from the local anti-scam RAG knowledge base.

    Accepted params:
    - query: required string describing the suspicious wording, tactic, or scenario pattern
    - top_k: optional integer number of results to return
    - category_filter: optional category restriction within scam-pattern search

    Use this for SMS, call, chat, or general scam-pattern analysis. Do not use it
    for bank-transfer beneficiary account/name validation. For transfer-review-specific
    guidance, use retrieve_transfer_guidance instead.
    """
    retriever = RagRetriever()
    return retriever.retrieve_scam_patterns(
        query=query,
        top_k=top_k,
        category_filter=category_filter,
    ).to_dict()


@tool
def retrieve_transfer_guidance(
    query: Annotated[
        str,
        "Specific bank-transfer review query built from transfer context such as "
        "new recipient, urgency, beneficiary mismatch, recent suspicious call/SMS, "
        "or prior risk signals.",
    ],
    top_k: Annotated[
        int | None,
        "Optional max number of matches to return. Use a small integer such as 1 to 5.",
    ] = None,
    category_filter: Annotated[
        str | None,
        "Optional extra category restriction. Normally omit this; transfer guidance "
        "search already targets transfer_guidance documents.",
    ] = None,
) -> dict:
    """Retrieve transfer-review guidance from the local anti-scam RAG knowledge base.

    Accepted params:
    - query: required string describing the bank transfer situation
    - top_k: optional integer number of results to return
    - category_filter: optional category restriction, usually omitted

    Use this only for bank-transfer review context, especially when reasoning about
    urgency, suspicious lead-up events, beneficiary mismatch, first-time recipient,
    or other transfer-risk cues. Do not use it for website/domain checks or phone-number
    checking.
    """
    retriever = RagRetriever()
    return retriever.retrieve_transfer_guidance(
        query=query,
        top_k=top_k,
        category_filter=category_filter,
    ).to_dict()
