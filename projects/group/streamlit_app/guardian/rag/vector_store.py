"""LangChain Chroma vector store helpers for local RAG."""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from typing import Any

import chromadb
from chromadb.config import Settings
from langchain_chroma import Chroma
from langchain_core.documents import Document

from .config import RagConfig

log = logging.getLogger(__name__)
COLLECTION_NAME = "guardian_rag"


@dataclass(frozen=True)
class VectorMatch:
    doc_id: str
    title: str
    category: str
    source_path: str
    score: float
    text: str


class RagVectorStore:
    def __init__(self, config: RagConfig, embeddings: Any) -> None:
        self._config = config
        self._embeddings = embeddings
        self._client: chromadb.ClientAPI | None = None
        self._store_instance: Chroma | None = None

    def rebuild(self, documents: list[Document], manifest: dict[str, Any]) -> None:
        if self._config.index_dir.exists():
            shutil.rmtree(self._config.index_dir)
        self._config.index_dir.mkdir(parents=True, exist_ok=True)
        self._client = None
        self._store_instance = None

        store = self._store()
        if documents:
            ids = [str(doc.metadata["chunk_id"]) for doc in documents]
            store.add_documents(documents=documents, ids=ids)
        self._config.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    def exists(self) -> bool:
        return self._config.index_dir.exists() and any(self._config.index_dir.iterdir())

    def query(
        self,
        query: str,
        *,
        top_k: int,
        categories: list[str] | None = None,
        extra_category: str | None = None,
    ) -> list[VectorMatch]:
        filters = list(categories or [])
        if extra_category:
            filters = [category for category in filters if category == extra_category] or [extra_category]

        search_kwargs: dict[str, Any] = {"k": top_k}
        if filters:
            if len(filters) == 1:
                search_kwargs["filter"] = {"category": filters[0]}
            else:
                search_kwargs["filter"] = {"$or": [{"category": category} for category in filters]}

        store = self._store()
        results = store.similarity_search_with_score(query, **search_kwargs)
        matches: list[VectorMatch] = []
        for document, raw_score in results:
            metadata = document.metadata
            matches.append(
                VectorMatch(
                    doc_id=str(metadata.get("doc_id", "")),
                    title=str(metadata.get("title", "")),
                    category=str(metadata.get("category", "")),
                    source_path=str(metadata.get("source_path", "")),
                    score=_to_similarity_score(float(raw_score)),
                    text=document.page_content,
                )
            )
        return matches

    def _store(self) -> Chroma:
        if self._store_instance is not None:
            return self._store_instance

        self._config.index_dir.mkdir(parents=True, exist_ok=True)
        if self._client is None:
            self._client = chromadb.PersistentClient(
                path=str(self._config.index_dir),
                settings=Settings(),
            )
        self._store_instance = Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=self._embeddings,
            client=self._client,
            persist_directory=str(self._config.index_dir),
        )
        return self._store_instance


def _to_similarity_score(raw_score: float) -> float:
    # Chroma returns a distance-like score here; lower is better.
    return 1.0 / (1.0 + max(raw_score, 0.0))
