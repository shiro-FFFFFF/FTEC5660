"""Environment-based configuration for the local RAG subsystem."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from guardian.paths import DATA_DIR

RAG_KNOWLEDGE_DIR = DATA_DIR / "rag_knowledge"
RAG_INDEX_DIR = DATA_DIR / "rag_vector_store"
RAG_CHROMA_DB_PATH = RAG_INDEX_DIR / "chroma.sqlite3"
RAG_MANIFEST_PATH = RAG_INDEX_DIR / "manifest.json"


@dataclass(frozen=True)
class RagConfig:
    enabled: bool
    message: str
    embedding_base_url: str
    embedding_model: str
    embedding_api_key: str
    top_k: int
    knowledge_dir: Path
    index_dir: Path
    chroma_db_path: Path
    manifest_path: Path
    request_timeout_s: float


def load_config() -> RagConfig:
    enabled_raw = os.environ.get("GUARDIAN_RAG_ENABLED", "1").strip().lower()
    enabled = enabled_raw not in {"0", "false", "no", "off"}
    base_url = os.environ.get("GUARDIAN_EMBEDDING_BASE_URL", "").strip()
    model = os.environ.get("GUARDIAN_EMBEDDING_MODEL", "").strip()
    top_k = _int_env("GUARDIAN_RAG_TOP_K", 5)
    timeout_s = _float_env("GUARDIAN_EMBEDDING_TIMEOUT_S", 10.0)
    api_key = os.environ.get("GUARDIAN_EMBEDDING_API_KEY", "lm-studio").strip() or "lm-studio"

    if not enabled:
        return RagConfig(
            enabled=False,
            message="RAG is disabled because GUARDIAN_RAG_ENABLED is set to 0.",
            embedding_base_url=base_url,
            embedding_model=model,
            embedding_api_key=api_key,
            top_k=top_k,
            knowledge_dir=RAG_KNOWLEDGE_DIR,
            index_dir=RAG_INDEX_DIR,
            chroma_db_path=RAG_CHROMA_DB_PATH,
            manifest_path=RAG_MANIFEST_PATH,
            request_timeout_s=timeout_s,
        )

    if not base_url:
        return RagConfig(
            enabled=False,
            message="RAG is disabled because embedding endpoint is not configured.",
            embedding_base_url=base_url,
            embedding_model=model,
            embedding_api_key=api_key,
            top_k=top_k,
            knowledge_dir=RAG_KNOWLEDGE_DIR,
            index_dir=RAG_INDEX_DIR,
            chroma_db_path=RAG_CHROMA_DB_PATH,
            manifest_path=RAG_MANIFEST_PATH,
            request_timeout_s=timeout_s,
        )

    if not model:
        return RagConfig(
            enabled=False,
            message="RAG is disabled because embedding model is not configured.",
            embedding_base_url=base_url,
            embedding_model=model,
            embedding_api_key=api_key,
            top_k=top_k,
            knowledge_dir=RAG_KNOWLEDGE_DIR,
            index_dir=RAG_INDEX_DIR,
            chroma_db_path=RAG_CHROMA_DB_PATH,
            manifest_path=RAG_MANIFEST_PATH,
            request_timeout_s=timeout_s,
        )

    return RagConfig(
        enabled=True,
        message="RAG is enabled.",
        embedding_base_url=base_url.rstrip("/"),
        embedding_model=model,
        embedding_api_key=api_key,
        top_k=top_k,
        knowledge_dir=RAG_KNOWLEDGE_DIR,
        index_dir=RAG_INDEX_DIR,
        chroma_db_path=RAG_CHROMA_DB_PATH,
        manifest_path=RAG_MANIFEST_PATH,
        request_timeout_s=timeout_s,
    )


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default
