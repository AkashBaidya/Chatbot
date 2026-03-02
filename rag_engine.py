"""
rag_engine.py
-------------
RAG (Retrieval-Augmented Generation) engine using sentence-transformers
and ChromaDB. Handles document chunking, embedding, storage, and retrieval.
"""

import hashlib
import re
from pathlib import Path

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

from document_loader import Document

# ---- Configuration ----
CHROMA_PERSIST_DIR = Path(__file__).parent / "chroma_db"
COLLECTION_NAME = "knowledge_base"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
CHUNK_SIZE = 500        # approximate tokens per chunk
CHUNK_OVERLAP = 50      # approximate token overlap
TOP_K = 5               # chunks to retrieve per query

# ---- Module-level singletons (lazy-loaded) ----
_model: SentenceTransformer | None = None
_client: chromadb.ClientAPI | None = None
_collection: chromadb.Collection | None = None


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English text."""
    return len(text) // 4


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        print("  Loading embedding model (first time only)...")
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def _get_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        CHROMA_PERSIST_DIR.mkdir(exist_ok=True)
        _client = chromadb.PersistentClient(
            path=str(CHROMA_PERSIST_DIR),
            settings=Settings(anonymized_telemetry=False),
        )
    return _client


def _get_or_create_collection() -> chromadb.Collection:
    global _collection
    client = _get_client()
    _collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    return _collection


# ---- Chunking ----

def chunk_document(doc: Document) -> list[dict]:
    """
    Split a Document into overlapping chunks of ~CHUNK_SIZE tokens.
    Returns list of dicts with text, source, format, chunk_index.
    """
    text = doc.content.strip()
    if not text:
        return []

    # Split by paragraph boundaries
    paragraphs = re.split(r'\n\s*\n', text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    chunks: list[str] = []
    current_chunk = ""

    char_limit = CHUNK_SIZE * 4          # ~tokens to chars
    overlap_chars = CHUNK_OVERLAP * 4

    for para in paragraphs:
        # If a single paragraph exceeds chunk size, split by sentences
        if _estimate_tokens(para) > CHUNK_SIZE:
            sentences = re.split(r'(?<=[.!?])\s+', para)
            for sentence in sentences:
                candidate = (current_chunk + " " + sentence).strip() if current_chunk else sentence
                if len(candidate) > char_limit and current_chunk:
                    chunks.append(current_chunk.strip())
                    overlap_text = current_chunk.strip()[-overlap_chars:]
                    current_chunk = overlap_text + " " + sentence
                else:
                    current_chunk = candidate
        else:
            candidate = (current_chunk + "\n\n" + para).strip() if current_chunk else para
            if len(candidate) > char_limit and current_chunk:
                chunks.append(current_chunk.strip())
                overlap_text = current_chunk.strip()[-overlap_chars:]
                current_chunk = overlap_text + "\n\n" + para
            else:
                current_chunk = candidate

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return [
        {
            "text": chunk_text,
            "source": doc.filename,
            "format": doc.format,
            "chunk_index": i,
        }
        for i, chunk_text in enumerate(chunks)
    ]


# ---- Indexing ----

def _generate_chunk_id(source: str, chunk_index: int) -> str:
    """Deterministic ID for a chunk."""
    raw = f"{source}::chunk_{chunk_index}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def index_documents(documents: list[Document]) -> int:
    """
    Clear and re-index all documents into ChromaDB.
    Returns the total number of chunks indexed.
    """
    client = _get_client()

    # Delete and recreate for clean state
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass

    global _collection
    _collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    all_chunks = []
    for doc in documents:
        chunks = chunk_document(doc)
        all_chunks.extend(chunks)

    if not all_chunks:
        return 0

    model = _get_model()
    texts = [c["text"] for c in all_chunks]
    ids = [_generate_chunk_id(c["source"], c["chunk_index"]) for c in all_chunks]
    metadatas = [
        {"source": c["source"], "format": c["format"], "chunk_index": c["chunk_index"]}
        for c in all_chunks
    ]

    embeddings = model.encode(texts, show_progress_bar=False).tolist()

    _collection.add(
        ids=ids,
        documents=texts,
        metadatas=metadatas,
        embeddings=embeddings,
    )

    print(f"  Indexed {len(all_chunks)} chunks from {len(documents)} document(s).")
    return len(all_chunks)


# ---- Retrieval ----

def retrieve(query: str, top_k: int = TOP_K) -> list[dict]:
    """
    Embed the query, search ChromaDB, return top-k relevant chunks.
    Returns list of {"text": str, "source": str, "score": float}.
    """
    collection = _get_or_create_collection()

    if collection.count() == 0:
        return []

    model = _get_model()
    query_embedding = model.encode([query], show_progress_bar=False).tolist()

    results = collection.query(
        query_embeddings=query_embedding,
        n_results=min(top_k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    retrieved = []
    for i in range(len(results["ids"][0])):
        retrieved.append({
            "text": results["documents"][0][i],
            "source": results["metadatas"][0][i]["source"],
            "score": 1.0 - results["distances"][0][i],  # cosine distance -> similarity
        })

    return retrieved


def format_retrieved_context(chunks: list[dict]) -> str:
    """Format retrieved chunks for inclusion in the system prompt."""
    if not chunks:
        return "(No relevant documents found in the knowledge base.)"

    parts = []
    for chunk in chunks:
        parts.append(
            f"[Source: {chunk['source']} | Relevance: {chunk['score']:.2f}]\n"
            f"{chunk['text']}"
        )
    return "\n\n---\n\n".join(parts)
