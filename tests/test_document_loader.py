"""Tests for document_loader.py — loading PDF, TXT, MD documents."""

import pytest
from pathlib import Path

from document_loader import Document, load_knowledge_base, load_text, format_for_context


KB_DIR = Path(__file__).parent.parent / "knowledge_base"


class TestLoadKnowledgeBase:
    def test_loads_all_documents(self):
        docs = load_knowledge_base(str(KB_DIR))
        assert len(docs) >= 2
        names = [d.filename for d in docs]
        assert "benefits_guide.txt" in names
        assert "company_handbook.md" in names

    def test_document_has_content(self):
        docs = load_knowledge_base(str(KB_DIR))
        for doc in docs:
            assert doc.content.strip(), f"{doc.filename} has no content"
            assert doc.format in ("txt", "md", "pdf")
            assert doc.filename
            assert doc.source_path

    def test_nonexistent_directory_raises(self):
        with pytest.raises(FileNotFoundError):
            load_knowledge_base("nonexistent_dir_xyz")

    def test_empty_directory(self, tmp_path):
        docs = load_knowledge_base(str(tmp_path))
        assert docs == []

    def test_ignores_unsupported_files(self, tmp_path):
        (tmp_path / "data.csv").write_text("a,b,c", encoding="utf-8")
        (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
        docs = load_knowledge_base(str(tmp_path))
        assert len(docs) == 1
        assert docs[0].filename == "notes.txt"


class TestLoadText:
    def test_loads_txt(self):
        path = KB_DIR / "benefits_guide.txt"
        content = load_text(path)
        assert "HEALTH INSURANCE" in content
        assert "Dental" in content

    def test_loads_md(self):
        path = KB_DIR / "company_handbook.md"
        content = load_text(path)
        assert "Acme Corp" in content


class TestDocument:
    def test_document_fields(self):
        doc = Document(
            filename="test.txt",
            format="txt",
            content="Hello world",
            source_path="/tmp/test.txt",
        )
        assert doc.filename == "test.txt"
        assert doc.format == "txt"
        assert doc.content == "Hello world"


class TestFormatForContext:
    def test_formats_documents(self):
        docs = [
            Document(filename="a.txt", format="txt", content="Doc A content", source_path="a.txt"),
            Document(filename="b.md", format="md", content="Doc B content", source_path="b.md"),
        ]
        result = format_for_context(docs)
        assert "SOURCE: a.txt" in result
        assert "SOURCE: b.md" in result
        assert "Doc A content" in result
        assert "Doc B content" in result

    def test_empty_list(self):
        result = format_for_context([])
        assert result == ""
