from pydantic import BaseModel
from typing import List, Optional, Dict, Any


class PrescriptionItemInput(BaseModel):
    raw_input: str
    doses_per_day: Optional[int] = None


class TraceRequest(BaseModel):
    prescription_items: List[PrescriptionItemInput]
    clinical_question: str


class Citation(BaseModel):
    chunk_id: str
    source_file: str
    page_anchor: str
    is_local_protocol: bool


class TraceResponse(BaseModel):
    # Module A: Normalization & Safety Rail
    rail_output: Dict[str, Any]
    
    # Module B: Grounded Q&A
    question: str
    grounded_answer: str
    citations: List[Citation]
    
    # Trace Info
    versions: Dict[str, str]
