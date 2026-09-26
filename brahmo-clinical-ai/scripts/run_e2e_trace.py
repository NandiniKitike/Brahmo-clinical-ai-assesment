"""
Module C: End-to-End Trace Script.
Takes a sample prescription and clinical question, runs the Trace API logic,
and saves the result to outputs/e2e_trace_sample.json.
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.drug_master.safety_rail import SafetyRail, PrescriptionItem, RAIL_DATA_VERSION, RAIL_RULE_VERSION
from app.rag.retriever import retrieve
from app.rag.answerer import generate_answer
from app.config import settings
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

def run_trace():
    db = SessionLocal()
    rail = SafetyRail(db)
    
    # Sample Case:
    # Patient prescribed Dolo 650 (Paracetamol) + Sinarest (Paracetamol+CPM+Phenylephrine)
    # This should trigger the cumulative exposure check!
    # Question: A clinical doubt about one of the drugs.
    
    rx_items = [
        PrescriptionItem(raw_input="Dolo 650", doses_per_day=3),
        PrescriptionItem(raw_input="Sinarest Tablet", doses_per_day=2),
        PrescriptionItem(raw_input="Mox 500", doses_per_day=3)
    ]
    
    question = "Which analgesic class must be avoided in suspected dengue, and why?"
    
    logger.info("Running Safety Rail...")
    rail_result = rail.check_prescription(rx_items)
    
    logger.info("Running Grounded Q&A...")
    chunks = retrieve(db, question)
    answer, citations = generate_answer(question, chunks)
    
    trace_out = {
        "rail_output": rail_result.to_dict(),
        "question": question,
        "grounded_answer": answer,
        "citations": citations,
        "versions": {
            "api_version": "v1.0",
            "rail_data_version": RAIL_DATA_VERSION,
            "rail_rule_version": RAIL_RULE_VERSION,
            "llm_model": settings.llm_model,
            "embedding_model": settings.embedding_model,
        }
    }
    
    out_dir = Path(__file__).parent.parent / "outputs"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / "e2e_trace_sample.json"
    
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(trace_out, f, indent=2)
        
    logger.info(f"Trace complete. JSON saved to {out_file}")

if __name__ == "__main__":
    run_trace()
