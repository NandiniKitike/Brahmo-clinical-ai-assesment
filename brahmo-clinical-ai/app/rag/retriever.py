"""
Hybrid Retriever for Module B (Grounded Q&A).
Combines semantic search (cosine similarity via numpy) and lexical search (BM25)
to find relevant clinical chunks.

Note: Uses Python-based cosine similarity instead of pgvector for compatibility
with standard PostgreSQL installations. In production, migrate to pgvector + HNSW
index for sub-millisecond retrieval at scale (documented in SCALE.md).
"""
from sqlalchemy.orm import Session
from app.models import CorpusChunk
from app.rag.embedder import get_embedding
from app.config import settings
from rank_bm25 import BM25Okapi
import numpy as np
import logging

logger = logging.getLogger(__name__)


def _cosine_similarity(vec_a: list, vec_b: list) -> float:
    """Compute cosine similarity between two vectors."""
    a = np.array(vec_a, dtype=np.float32)
    b = np.array(vec_b, dtype=np.float32)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def retrieve(db: Session, query: str, top_k: int = settings.retrieval_top_k) -> list[CorpusChunk]:
    """
    Retrieve relevant chunks for a clinical question using a hybrid approach.
    1. Semantic search via numpy cosine similarity over JSONB-stored embeddings
    2. Lexical search via BM25 (in-memory)
    3. Reciprocal Rank Fusion (RRF) to combine results
    """
    logger.info(f"Retrieving chunks for query: {query}")

    all_chunks = db.query(CorpusChunk).all()
    if not all_chunks:
        logger.warning("No corpus chunks found in DB. Run scripts/load_all_data.py first.")
        return []

    chunk_dict = {c.id: c for c in all_chunks}

    # 1. Semantic Search (cosine similarity in Python)
    query_embedding = get_embedding(query)
    semantic_results = []

    if query_embedding:
        scored = []
        for chunk in all_chunks:
            if chunk.embedding:
                sim = _cosine_similarity(query_embedding, chunk.embedding)
                scored.append((chunk.id, sim))
        scored.sort(key=lambda x: x[1], reverse=True)
        semantic_results = scored[:top_k * 2]

    # 2. Lexical Search (BM25)
    tokenized_corpus = [c.content.lower().split() for c in all_chunks]
    bm25 = BM25Okapi(tokenized_corpus)
    tokenized_query = query.lower().split()
    bm25_scores = bm25.get_scores(tokenized_query)
    top_bm25_idx = np.argsort(bm25_scores)[::-1][:top_k * 2]
    lexical_results = [(all_chunks[idx].id, bm25_scores[idx]) for idx in top_bm25_idx if bm25_scores[idx] > 0]

    # 3. Reciprocal Rank Fusion (RRF)
    k = 60
    rrf_scores = {}
    for rank, (chunk_id, _) in enumerate(semantic_results):
        rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0) + (1.0 / (k + rank))
    for rank, (chunk_id, _) in enumerate(lexical_results):
        rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0) + (1.0 / (k + rank))

    sorted_fused = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    final_chunks = [chunk_dict[chunk_id] for chunk_id, _ in sorted_fused if chunk_id in chunk_dict]

    logger.info(f"Retrieved {len(final_chunks)} chunks.")
    return final_chunks

