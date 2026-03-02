"""Tests for rag_engine.py — RAG chunking, indexing, retrieval."""

import pytest

from document_loader import Document, load_knowledge_base
from rag_engine import (
    chunk_document,
    index_documents,
    retrieve,
    format_retrieved_context,
    _estimate_tokens,
    _generate_chunk_id,
)


KB_DIR = "knowledge_base"


class TestEstimateTokens:
    def test_short_text(self):
        assert _estimate_tokens("hello") == 1  # 5 chars // 4

    def test_longer_text(self):
        text = "a" * 400
        assert _estimate_tokens(text) == 100


class TestGenerateChunkId:
    def test_deterministic(self):
        id1 = _generate_chunk_id("file.txt", 0)
        id2 = _generate_chunk_id("file.txt", 0)
        assert id1 == id2

    def test_different_for_different_chunks(self):
        id1 = _generate_chunk_id("file.txt", 0)
        id2 = _generate_chunk_id("file.txt", 1)
        assert id1 != id2

    def test_different_for_different_sources(self):
        id1 = _generate_chunk_id("a.txt", 0)
        id2 = _generate_chunk_id("b.txt", 0)
        assert id1 != id2


class TestChunkDocument:
    def test_small_document_single_chunk(self):
        doc = Document(
            filename="small.txt",
            format="txt",
            content="This is a small document.",
            source_path="small.txt",
        )
        chunks = chunk_document(doc)
        assert len(chunks) == 1
        assert chunks[0]["source"] == "small.txt"
        assert chunks[0]["text"] == "This is a small document."
        assert chunks[0]["chunk_index"] == 0

    def test_empty_document(self):
        doc = Document(filename="empty.txt", format="txt", content="", source_path="empty.txt")
        chunks = chunk_document(doc)
        assert chunks == []

    def test_whitespace_only_document(self):
        doc = Document(filename="ws.txt", format="txt", content="   \n\n  ", source_path="ws.txt")
        chunks = chunk_document(doc)
        assert chunks == []

    def test_large_document_multiple_chunks(self):
        # Create a document with enough content to split into multiple chunks
        paragraphs = [f"Paragraph {i}. " + "x " * 200 for i in range(10)]
        content = "\n\n".join(paragraphs)
        doc = Document(filename="big.txt", format="txt", content=content, source_path="big.txt")
        chunks = chunk_document(doc)
        assert len(chunks) > 1
        for i, chunk in enumerate(chunks):
            assert chunk["source"] == "big.txt"
            assert chunk["chunk_index"] == i
            assert len(chunk["text"]) > 0

    def test_real_documents(self):
        docs = load_knowledge_base(KB_DIR)
        for doc in docs:
            chunks = chunk_document(doc)
            assert len(chunks) >= 1, f"{doc.filename} produced no chunks"
            for c in chunks:
                assert c["source"] == doc.filename
                assert len(c["text"]) > 0

    def test_chunk_metadata(self):
        doc = Document(filename="test.md", format="md", content="Some content", source_path="test.md")
        chunks = chunk_document(doc)
        assert chunks[0]["format"] == "md"


class TestIndexAndRetrieve:
    @pytest.fixture(autouse=True)
    def index_docs(self):
        """Index real knowledge base docs before each test."""
        docs = load_knowledge_base(KB_DIR)
        self.chunk_count = index_documents(docs)

    def test_index_returns_chunk_count(self):
        assert self.chunk_count >= 3

    def test_retrieve_vacation_policy(self):
        results = retrieve("vacation days policy")
        assert len(results) > 0
        # benefits_guide.txt has vacation info
        sources = [r["source"] for r in results]
        assert "benefits_guide.txt" in sources

    def test_retrieve_dental_coverage(self):
        results = retrieve("dental allowance coverage")
        assert len(results) > 0
        # Top result should be benefits_guide.txt (contains dental info)
        assert results[0]["source"] == "benefits_guide.txt"
        assert results[0]["score"] > 0

    def test_retrieve_working_hours(self):
        results = retrieve("working hours remote work")
        assert len(results) > 0
        sources = [r["source"] for r in results]
        assert "company_handbook.md" in sources

    def test_retrieve_password_policy(self):
        results = retrieve("password policy security")
        assert len(results) > 0
        sources = [r["source"] for r in results]
        assert "it_security_policy.pdf" in sources

    def test_retrieve_returns_scores(self):
        results = retrieve("benefits")
        for r in results:
            assert "text" in r
            assert "source" in r
            assert "score" in r
            assert isinstance(r["score"], float)

    def test_retrieve_top_k(self):
        results = retrieve("policy", top_k=2)
        assert len(results) <= 2

    def test_retrieve_empty_collection(self):
        # Index with empty list to clear
        index_documents([])
        results = retrieve("anything")
        assert results == []


class TestFormatRetrievedContext:
    def test_formats_chunks(self):
        chunks = [
            {"text": "Chunk one text", "source": "a.txt", "score": 0.85},
            {"text": "Chunk two text", "source": "b.md", "score": 0.72},
        ]
        result = format_retrieved_context(chunks)
        assert "[Source: a.txt | Relevance: 0.85]" in result
        assert "[Source: b.md | Relevance: 0.72]" in result
        assert "Chunk one text" in result
        assert "Chunk two text" in result

    def test_empty_chunks(self):
        result = format_retrieved_context([])
        assert "No relevant" in result
