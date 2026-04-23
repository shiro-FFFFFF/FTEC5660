"""CLI entry point to build the local anti-scam RAG index."""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, UTC

from guardian.rag.chunking import chunk_documents
from guardian.rag.config import load_config
from guardian.rag.embeddings import make_embeddings
from guardian.rag.loader import load_markdown_documents
from guardian.rag.vector_store import RagVectorStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(__name__)


def build_index() -> dict:
    config = load_config()
    if not config.enabled:
        result = {
            "status": "disabled",
            "message": config.message,
            "docs_indexed": 0,
            "chunks_indexed": 0,
        }
        log.info(result["message"])
        return result

    documents = load_markdown_documents(config.knowledge_dir)
    chunks = chunk_documents(documents)
    log.info("RAG build start: %d docs, %d chunks", len(documents), len(chunks))

    try:
        embeddings = make_embeddings(config)
        store = RagVectorStore(config, embeddings)
    except Exception as exc:
        result = {
            "status": "error",
            "message": f"Failed to initialize LangChain RAG components: {exc}",
            "docs_indexed": 0,
            "chunks_indexed": 0,
        }
        log.error(result["message"])
        return result

    categories = sorted({document.category for document in documents})
    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "knowledge_dir": str(config.knowledge_dir),
        "docs_indexed": len(documents),
        "chunks_indexed": len(chunks),
        "categories": categories,
        "documents": [
            {
                "doc_id": document.doc_id,
                "title": document.title,
                "category": document.category,
                "source_path": document.source_path,
            }
            for document in documents
        ],
    }

    try:
        store.rebuild(chunks, manifest)
        result = {
            "status": "ok",
            "message": f"Indexed {len(documents)} docs and {len(chunks)} chunks.",
            "docs_indexed": len(documents),
            "chunks_indexed": len(chunks),
            "index_path": str(config.index_dir),
            "manifest_path": str(config.manifest_path),
        }
        log.info(result["message"])
        return result
    except Exception as exc:
        result = {
            "status": "error",
            "message": f"Failed to build LangChain Chroma index: {exc}",
            "docs_indexed": 0,
            "chunks_indexed": 0,
        }
        log.error(result["message"])
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the local anti-scam RAG index.")
    parser.parse_args()
    result = build_index()
    print(json.dumps(result, indent=2))
    return 0 if result["status"] in {"ok", "disabled"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
