"""
Answer generation for Module B (Grounded Q&A).
Uses Gemini 1.5 Flash to generate grounded answers with strict citation rules.
"""

import google.generativeai as genai
from app.models import CorpusChunk
from app.config import settings
import logging
from typing import Tuple

logger = logging.getLogger(__name__)

# System prompt enforcing binding laws for Q&A
RAG_SYSTEM_PROMPT = """You are BRAHMO Clinical AI, an assistant for Indian doctors.
You answer clinical questions strictly based on the provided retrieved text chunks.

BINDING LAWS FOR ANSWERING:
1. Grounded or honest: Your answer must come ONLY from the provided text. Do not use outside medical knowledge.
2. Abstention: If the provided text does not contain the answer, you must state exactly: "I cannot answer this question based on the provided corpus." and briefly state what is missing. Do not guess.
3. Claim-level citations: Every clinical claim must end with a citation to the source chunk. Format: [Source File, Page Anchor].
4. Conflict rule: If two sources conflict, you must state BOTH conflicting recommendations and their effective dates. Do NOT synthesize a third recommendation. Do NOT pick a winner.
5. Doses: If asked for a dose, quote the text as written. NEVER calculate a dose for a specific patient.
6. Local Protocol: If an answer comes from a source marked as "local_protocol", you MUST explicitly state "According to the clinic's own protocol..."
"""

def generate_answer(query: str, chunks: list[CorpusChunk]) -> Tuple[str, list[dict]]:
    """
    Generate an answer using the LLM, strictly grounded in the provided chunks.
    Returns the answer string and a list of citation metadata.
    """
    if not chunks:
        return "I cannot answer this question because no relevant information was found in the corpus.", []

    # Format chunks for the prompt
    context_parts = []
    citations_meta = []
    
    for i, chunk in enumerate(chunks, start=1):
        is_local = "YES" if chunk.is_local_protocol else "NO"
        context_parts.append(
            f"--- CHUNK {i} ---\n"
            f"Source File: {chunk.source_file}\n"
            f"Page Anchor: {chunk.page_anchor}\n"
            f"Specialty: {chunk.specialty}\n"
            f"Condition: {chunk.condition}\n"
            f"Effective Date: {chunk.effective_date}\n"
            f"Is Local Protocol: {is_local}\n"
            f"Content: {chunk.content}\n"
        )
        citations_meta.append({
            "chunk_id": chunk.id,
            "source_file": chunk.source_file,
            "page_anchor": chunk.page_anchor,
            "is_local_protocol": chunk.is_local_protocol
        })

    context_str = "\n".join(context_parts)
    
    prompt = f"""
QUESTION: {query}

RETRIEVED CONTEXT:
{context_str}

Please provide your answer following the binding laws.
"""

    import time

    model = genai.GenerativeModel(
        model_name=settings.llm_model,
        system_instruction=RAG_SYSTEM_PROMPT
    )

    for attempt in range(5):
        try:
            response = model.generate_content(prompt, generation_config={"temperature": 0.0})
            answer = response.text.strip()
            return answer, citations_meta

        except Exception as e:
            err_str = str(e)
            # Rate limit — extract retry delay if present, else use exponential backoff
            if "429" in err_str or "quota" in err_str.lower():
                import re
                delay_match = re.search(r"retry_delay\s*\{\s*seconds:\s*(\d+)", err_str)
                wait = int(delay_match.group(1)) + 2 if delay_match else (2 ** attempt) * 15
                logger.warning(f"Rate limit hit (attempt {attempt+1}/5). Waiting {wait}s before retry...")
                time.sleep(wait)
                continue
            # Non-retryable error
            logger.error(f"Error generating answer: {e}")
            return f"Error generating answer: {str(e)}", []

    logger.error("Max retries exceeded for rate limit.")
    return "I cannot answer this question — API rate limit exceeded after retries.", []
