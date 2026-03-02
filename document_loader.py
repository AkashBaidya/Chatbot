"""
document_loader.py
------------------
Responsible for loading documents from the knowledge_base directory.
Supports: .pdf, .txt, .md

Design decision: We load all documents into memory as plain text chunks at startup.
For a small knowledge base (< ~50 docs), this is simpler and faster than a vector DB.
Each document becomes a "Document" object with its content and metadata.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Document:
    """Represents a loaded document from the knowledge base."""
    filename: str
    format: str          # "pdf", "txt", "md"
    content: str
    source_path: str


def load_pdf(path: Path) -> Optional[str]:
    """Extract text from a PDF file using pypdf."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages).strip()
    except ImportError:
        print("  [warning] pypdf not installed — skipping PDF files. Run: pip install pypdf")
        return None
    except Exception as e:
        print(f"  [warning] Failed to read PDF {path.name}: {e}")
        return None


def load_text(path: Path) -> str:
    """Load a plain text or Markdown file."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def load_knowledge_base(directory: str = "knowledge_base") -> list[Document]:
    """
    Walk the knowledge_base directory and load all supported documents.
    Returns a list of Document objects.
    """
    kb_path = Path(directory)
    if not kb_path.exists():
        raise FileNotFoundError(f"Knowledge base directory not found: {directory}")

    documents: list[Document] = []
    supported = {".pdf": "pdf", ".txt": "txt", ".md": "md"}

    for file_path in sorted(kb_path.iterdir()):
        suffix = file_path.suffix.lower()
        if suffix not in supported:
            continue

        fmt = supported[suffix]
        print(f"  Loading [{fmt.upper()}] {file_path.name}...")

        if fmt == "pdf":
            content = load_pdf(file_path)
        else:
            content = load_text(file_path)

        if content:
            documents.append(Document(
                filename=file_path.name,
                format=fmt,
                content=content,
                source_path=str(file_path),
            ))

    return documents


def format_for_context(documents: list[Document]) -> str:
    """
    Format all documents into a single context string for the LLM.
    Each document is wrapped with clear source markers.
    """
    parts = []
    for doc in documents:
        parts.append(
            f"=== SOURCE: {doc.filename} ({doc.format.upper()}) ===\n"
            f"{doc.content}\n"
            f"=== END OF {doc.filename} ==="
        )
    return "\n\n".join(parts)
