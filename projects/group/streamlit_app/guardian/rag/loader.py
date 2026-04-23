"""Markdown document loading and metadata extraction for RAG knowledge."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class RagDocument:
    doc_id: str
    title: str
    category: str
    source_path: str
    text: str


def load_markdown_documents(knowledge_dir: Path) -> list[RagDocument]:
    documents: list[RagDocument] = []
    if not knowledge_dir.exists():
        return documents

    for path in sorted(knowledge_dir.rglob("*.md")):
        source_path = path.relative_to(knowledge_dir).as_posix()
        category = source_path.split("/", 1)[0] if "/" in source_path else "uncategorized"
        text = path.read_text(encoding="utf-8")
        documents.append(
            RagDocument(
                doc_id=path.relative_to(knowledge_dir).with_suffix("").as_posix(),
                title=extract_title(text, path.stem),
                category=category,
                source_path=source_path,
                text=text,
            )
        )
    return documents


def extract_title(text: str, fallback: str) -> str:
    match = _H1_RE.search(text)
    if match:
        return match.group(1).strip()
    return fallback.replace("_", " ").strip()
