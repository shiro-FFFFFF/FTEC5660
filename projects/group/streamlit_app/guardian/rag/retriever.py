"""Retrieval helpers for the anti-scam RAG subsystem."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

from .config import RagConfig, load_config
from .embeddings import make_embeddings
from .vector_store import RagVectorStore, VectorMatch

log = logging.getLogger(__name__)

SCAM_PATTERN_CATEGORIES = [
    "scam_patterns",
    "benign_patterns",
    "tactics",
    "scenario_notes",
]
TRANSFER_GUIDANCE_CATEGORIES = ["transfer_guidance"]


@dataclass(frozen=True)
class RetrievalResult:
    status: str
    query: str
    matches: list[dict[str, Any]]
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RagRetriever:
    def __init__(self, config: RagConfig | None = None) -> None:
        self._config = config or load_config()
        self._embeddings = make_embeddings(self._config) if self._config.enabled else None
        self._store = (
            RagVectorStore(self._config, self._embeddings) if self._embeddings is not None else None
        )
        log.info("RAG state: %s", self._config.message)

    def retrieve_scam_patterns(
        self,
        *,
        query: str,
        top_k: int | None = None,
        category_filter: str | None = None,
    ) -> RetrievalResult:
        return self._retrieve(
            query=query,
            categories=SCAM_PATTERN_CATEGORIES,
            top_k=top_k,
            category_filter=category_filter,
        )

    def retrieve_transfer_guidance(
        self,
        *,
        query: str,
        top_k: int | None = None,
        category_filter: str | None = None,
    ) -> RetrievalResult:
        return self._retrieve(
            query=query,
            categories=TRANSFER_GUIDANCE_CATEGORIES,
            top_k=top_k,
            category_filter=category_filter,
        )

    def _retrieve(
        self,
        *,
        query: str,
        categories: list[str],
        top_k: int | None,
        category_filter: str | None,
    ) -> RetrievalResult:
        clean_query = query.strip()
        if not clean_query:
            return RetrievalResult(
                status="error",
                query=query,
                matches=[],
                message="Query must not be empty.",
            )
        if not self._config.enabled:
            return RetrievalResult(
                status="disabled",
                query=clean_query,
                matches=[],
                message=self._config.message,
            )
        if self._store is None:
            return RetrievalResult(
                status="disabled",
                query=clean_query,
                matches=[],
                message=self._config.message,
            )
        if not self._store.exists():
            return RetrievalResult(
                status="error",
                query=clean_query,
                matches=[],
                message="RAG index is missing. Build the index before retrieving.",
            )

        try:
            matches = self._store.query(
                clean_query,
                top_k=top_k or self._config.top_k,
                categories=categories,
                extra_category=category_filter,
            )
        except Exception as exc:
            log.exception("RAG retrieval failed: %s", exc)
            return RetrievalResult(
                status="error",
                query=clean_query,
                matches=[],
                message=f"RAG retrieval failed: {exc}",
            )

        log.info("RAG retrieval ok: %d match(es) for categories=%s", len(matches), categories)
        return RetrievalResult(
            status="ok",
            query=clean_query,
            matches=[_format_match(match, clean_query) for match in matches],
            message="Retrieved RAG matches successfully.",
        )


def _format_match(match: VectorMatch, query: str) -> dict[str, Any]:
    return {
        "doc_id": match.doc_id,
        "title": match.title,
        "category": match.category,
        "score": round(match.score, 4),
        "snippet": _build_snippet(match.text, query),
        "source_path": match.source_path,
    }


def _build_snippet(text: str, query: str, limit: int = 220) -> str:
    clean = " ".join(text.split())
    lower = clean.lower()
    terms = [term for term in query.lower().split() if len(term) > 2]
    if not terms:
        return clean[:limit] + ("..." if len(clean) > limit else "")

    positions = [lower.find(term) for term in terms if lower.find(term) >= 0]
    if not positions:
        return clean[:limit] + ("..." if len(clean) > limit else "")

    start = max(0, min(positions) - 60)
    end = min(len(clean), start + limit)
    snippet = clean[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(clean):
        snippet = snippet + "..."
    return snippet
