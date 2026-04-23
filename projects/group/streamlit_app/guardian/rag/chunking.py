"""LangChain-based chunking helpers for local markdown-based RAG."""

from __future__ import annotations

from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from .loader import RagDocument
_HEADER_SPLITTER = MarkdownHeaderTextSplitter(
    headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")]
)
_TEXT_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200,
    add_start_index=True,
)


def chunk_document(document: RagDocument) -> list[Document]:
    base_metadata = {
        "doc_id": document.doc_id,
        "title": document.title,
        "category": document.category,
        "source_path": document.source_path,
    }

    header_docs = _HEADER_SPLITTER.split_text(document.text)
    if not header_docs:
        header_docs = [Document(page_content=document.text, metadata={})]

    prepared_docs = [
        Document(
            page_content=header_doc.page_content,
            metadata={
                **base_metadata,
                **header_doc.metadata,
            },
        )
        for header_doc in header_docs
        if header_doc.page_content.strip()
    ]

    split_docs = _TEXT_SPLITTER.split_documents(prepared_docs)
    for index, split_doc in enumerate(split_docs):
        split_doc.metadata["chunk_id"] = f"{document.doc_id}::chunk_{index}"
        split_doc.metadata["chunk_index"] = index
        split_doc.metadata["text"] = split_doc.page_content
    return split_docs


def chunk_documents(documents: list[RagDocument]) -> list[Document]:
    chunks: list[Document] = []
    for document in documents:
        chunks.extend(chunk_document(document))
    return chunks
