"""
Module B: Mini-Eval Harness.
Runs the grounded Q&A system against the sample questions.
Outputs to outputs/mini_eval_results.json.
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.rag.retriever import retrieve
from app.rag.answerer import generate_answer
from app.config import settings
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

QUESTIONS = [
    "What is the first-line antibiotic, dose basis, and duration for acute otitis media in a child?",
    "A 6-year-old with non-severe community pneumonia: what is the amoxicillin dose exactly as the workflow states it?",
    "What is the first-line initial drug therapy for newly diagnosed adult hypertension?",
    "Which analgesic class must be avoided in suspected dengue, and why?",
    "What are the ORS volumes after each loose stool for a child aged 2–10 years, and what zinc course accompanies it?",
    "Which red flags in acute low back pain mandate imaging or referral?",
    "Which urinary antibiotic is avoided at 36+ weeks of pregnancy, and what is the stated alternative?",
    "At what HbA1c threshold at diagnosis does the workflow add a second agent to metformin, and which agent?",
    "What is the first-line prophylactic drug for migraine in adults?",
    "What is the standard drug regimen for newly diagnosed pulmonary tuberculosis?",
    "Per the clinic's own protocol, when are empirical antibiotics started in adult acute undifferentiated fever — and does the national workflow pack say the same? Label your sources."
]

def run_eval():
    db = SessionLocal()
    results = []
    
    logger.info(f"Running mini-eval on {len(QUESTIONS)} questions using {settings.llm_model}...")
    
    for i, q in enumerate(QUESTIONS, start=1):
        logger.info(f"Q{i}: {q}")
        chunks = retrieve(db, q)
        answer, citations = generate_answer(q, chunks)
        
        # Determine status (heuristically for the harness)
        status = "ANSWERED"
        if "cannot answer" in answer.lower():
            status = "ABSTAINED"
            
        results.append({
            "question_id": i,
            "question": q,
            "status": status,
            "answer": answer,
            "citations_count": len(citations),
            "citations": citations
        })
        
        logger.info(f"  -> {status} (Citations: {len(citations)})")

        # Respect free-tier rate limit (5 req/min = 12s between calls)
        if i < len(QUESTIONS):
            import time
            time.sleep(18)
        
    out_dir = Path(__file__).parent.parent / "outputs"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / "mini_eval_results.json"
    
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "model": settings.llm_model,
            "embedding": settings.embedding_model,
            "results": results
        }, f, indent=2)
        
    logger.info(f"Mini-eval complete. Results saved to {out_file}")

if __name__ == "__main__":
    run_eval()
