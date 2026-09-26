"""
Embedder for Module B (Grounded Q&A).
Uses Gemini's text-embedding-004 model.
"""
import os
import google.generativeai as genai
from sqlalchemy.orm import Session
from app.models import CorpusChunk
from app.config import settings
import logging

logger = logging.getLogger(__name__)

# Configure Gemini
genai.configure(api_key=settings.gemini_api_key)


def get_embedding(text: str) -> list[float]:
    """Get embedding for a single string using Gemini API."""
    try:
        # text-embedding-004 supports 768 dimensions
        result = genai.embed_content(
            model=settings.embedding_model,
            content=text,
            task_type="retrieval_document"
        )
        return result['embedding']
    except Exception as e:
        logger.error(f"Error getting embedding: {e}")
        return []


def embed_corpus(db: Session):
    """
    Generate embeddings for all chunks that don't have one.
    Updates the db in place.
    """
    unembedded_chunks = db.query(CorpusChunk).filter(CorpusChunk.embedding == None).all()
    logger.info(f"Found {len(unembedded_chunks)} chunks needing embeddings.")
    
    count = 0
    for chunk in unembedded_chunks:
        # Include metadata in the embedded text for better retrieval
        text_to_embed = f"Condition: {chunk.condition}\nSpecialty: {chunk.specialty}\nContent: {chunk.content}"
        
        emb = get_embedding(text_to_embed)
        if emb:
            chunk.embedding = emb
            count += 1
            
        # Commit periodically
        if count % 50 == 0:
            db.commit()
            
    db.commit()
    logger.info(f"Successfully embedded {count} chunks.")
