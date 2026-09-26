from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas.trace import TraceRequest, TraceResponse
from app.drug_master.safety_rail import SafetyRail, PrescriptionItem, RAIL_DATA_VERSION, RAIL_RULE_VERSION
from app.rag.retriever import retrieve
from app.rag.answerer import generate_answer
from app.config import settings
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/trace", response_model=TraceResponse)
def run_end_to_end_trace(request: TraceRequest, db: Session = Depends(get_db)):
    """
    Module C: End-to-End Trace.
    Takes a draft prescription and a clinical question, returns a single JSON trace
    with normalization, safety checks, grounded answer, and version info.
    """
    
    # 1. Module A: Safety Rail
    rail = SafetyRail(db)
    
    rx_items = [
        PrescriptionItem(
            raw_input=i.raw_input,
            doses_per_day=i.doses_per_day
        )
        for i in request.prescription_items
    ]
    
    rail_result = rail.check_prescription(rx_items)
    
    # 2. Module B: Grounded Q&A
    retrieved_chunks = retrieve(db, request.clinical_question)
    answer, citations = generate_answer(request.clinical_question, retrieved_chunks)
    
    # 3. Assemble Output
    return TraceResponse(
        rail_output=rail_result.to_dict(),
        question=request.clinical_question,
        grounded_answer=answer,
        citations=citations,
        versions={
            "api_version": "v1.0",
            "rail_data_version": RAIL_DATA_VERSION,
            "rail_rule_version": RAIL_RULE_VERSION,
            "llm_model": settings.llm_model,
            "embedding_model": settings.embedding_model,
        }
    )
