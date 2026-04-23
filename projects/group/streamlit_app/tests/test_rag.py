from __future__ import annotations

from pathlib import Path

from guardian.rag.chunking import chunk_document
from guardian.rag.loader import RagDocument, extract_title
from guardian.rag.retriever import RagRetriever


def test_extract_title_prefers_h1() -> None:
    text = "# Fake Police Scam\n\nDetails"
    assert extract_title(text, "fallback") == "Fake Police Scam"


def test_chunk_document_preserves_metadata() -> None:
    document = RagDocument(
        doc_id="scam_patterns/demo",
        title="Demo",
        category="scam_patterns",
        source_path="scam_patterns/demo.md",
        text="# Demo\n\nFirst section.\n\n## Next\n\nSecond section.",
    )
    chunks = chunk_document(document)
    assert chunks
    assert chunks[0].metadata["doc_id"] == document.doc_id
    assert chunks[0].metadata["category"] == "scam_patterns"
    assert "chunk_id" in chunks[0].metadata


def test_retriever_disabled_without_embedding_endpoint(monkeypatch: object) -> None:
    monkeypatch.delenv("GUARDIAN_EMBEDDING_BASE_URL", raising=False)
    monkeypatch.setenv("GUARDIAN_RAG_ENABLED", "1")
    monkeypatch.setenv("GUARDIAN_EMBEDDING_MODEL", "demo-model")

    retriever = RagRetriever()
    result = retriever.retrieve_scam_patterns(query="urgent transfer")

    assert result.status == "disabled"
    assert result.matches == []
