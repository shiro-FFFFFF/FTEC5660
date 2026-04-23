"""LangChain embeddings helpers for the local RAG subsystem."""

from __future__ import annotations

from langchain_openai import OpenAIEmbeddings

from .config import RagConfig


def make_embeddings(config: RagConfig) -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=config.embedding_model,
        base_url=config.embedding_base_url,
        api_key=config.embedding_api_key,
        timeout=config.request_timeout_s,
        # Local OpenAI-compatible embedding servers such as LM Studio and Ollama
        # typically expect raw strings in the `input` field, not token arrays.
        # Disabling LangChain's length-safe tokenization path keeps requests in
        # the simpler string-list shape those servers accept.
        check_embedding_ctx_length=False,
    )
