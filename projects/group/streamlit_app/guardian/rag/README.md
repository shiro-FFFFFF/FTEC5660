# Local RAG Subsystem

This directory contains the local RAG subsystem for the anti-scam app.

It supports:

- markdown knowledge ingestion from `root/data/rag_knowledge`
- heading-aware chunking with metadata
- embeddings via LangChain `OpenAIEmbeddings` against an LM Studio OpenAI-compatible endpoint
- a local persisted LangChain `Chroma` vector store under `root/data/rag_vector_store`
- tool-style retrieval helpers for scam-pattern and transfer-guidance retrieval
- graceful disabled behavior when embedding configuration is missing

## Paths

- Knowledge base: `data/rag_knowledge`
- Persisted vector store: `data/rag_vector_store/chroma.sqlite3`
- Manifest: `data/rag_vector_store/manifest.json`

All code lives under `streamlit_app/guardian/rag/`.

## Environment variables

Add these to `streamlit_app/.env` if you want RAG enabled:

```env
GUARDIAN_RAG_ENABLED=1
GUARDIAN_EMBEDDING_BASE_URL=http://127.0.0.1:1234/v1
GUARDIAN_EMBEDDING_MODEL=text-embedding-model-name
GUARDIAN_RAG_TOP_K=5
GUARDIAN_EMBEDDING_TIMEOUT_S=10
```

Disabled behavior:

- if `GUARDIAN_RAG_ENABLED=0`, retrieval returns `status="disabled"`
- if `GUARDIAN_EMBEDDING_BASE_URL` is missing, retrieval returns `status="disabled"`
- if `GUARDIAN_EMBEDDING_MODEL` is missing, retrieval returns `status="disabled"`
- if the index is missing, retrieval returns `status="error"` with a rebuild message

## Build the index

From `streamlit_app/`:

```bash
python -m guardian.rag.build_index
```

This will:

1. scan `data/rag_knowledge`
2. load markdown documents
3. chunk them
4. request embeddings from LM Studio
5. rebuild the SQLite vector store under `data/rag_vector_store`

## Retrieval functions

### `retrieve_scam_patterns`

Searches these categories:

- `scam_patterns`
- `benign_patterns`
- `tactics`
- `scenario_notes`

Example:

```python
from guardian.rag.tools import retrieve_scam_patterns

result = retrieve_scam_patterns(
    query="urgent transfer after police call with secrecy language",
    top_k=5,
)
```

### `retrieve_transfer_guidance`

Searches:

- `transfer_guidance`

Example:

```python
from guardian.rag.tools import retrieve_transfer_guidance

result = retrieve_transfer_guidance(
    query="new payee beneficiary mismatch and prior risk reports",
    top_k=3,
)
```

## Output shape

Retrieval results are tool-friendly JSON-compatible dicts:

```json
{
  "status": "ok",
  "query": "urgent transfer after police call",
  "matches": [
    {
      "doc_id": "scam_patterns/urgent_transfer_pressure",
      "title": "Urgent Transfer Pressure",
      "category": "scam_patterns",
      "score": 0.8123,
      "snippet": "...",
      "source_path": "scam_patterns/urgent_transfer_pressure.md"
    }
  ],
  "message": "Retrieved RAG matches successfully."
}
```

Disabled example:

```json
{
  "status": "disabled",
  "query": "beneficiary mismatch",
  "matches": [],
  "message": "RAG is disabled because embedding endpoint is not configured."
}
```

## Intended usage

The agent is expected to build its own query from event context and then call:

- `retrieve_scam_patterns(...)` for SMS / call / chat / general scam-pattern retrieval
- `retrieve_transfer_guidance(...)` for transfer-review-specific guidance retrieval

The retriever deliberately stays simple:

- no complex query rewriting
- no large document dumps
- concise snippets with metadata and scores

## LangChain implementation notes

This RAG layer follows the LangChain RAG pattern:

- load markdown documents
- split them with LangChain text splitters
- index them into Chroma with a local `persist_directory`
- retrieve with similarity search and metadata filters

Relevant docs:

- [LangChain RAG guide](https://docs.langchain.com/oss/python/langchain/rag)
- [LangChain Chroma integration](https://docs.langchain.com/oss/python/integrations/vectorstores/chroma)
- [LangChain OpenAIEmbeddings integration](https://docs.langchain.com/oss/python/integrations/embeddings/openai)
