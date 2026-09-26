"""
Corpus chunker for Module B (Grounded Q&A).

Binding law §1: "Chunking into clinically meaningful decision units."
We do NOT use blind token slicing. We extract logical blocks
like Recommendations, Doses, and Contraindications, carrying
full metadata.
"""

import os
import re
import uuid
import pypdf
from pathlib import Path
from datetime import datetime
from sqlalchemy.orm import Session
from app.models import CorpusChunk
from app.config import settings
import logging

logger = logging.getLogger(__name__)


def chunk_stw_pdf(filepath: Path) -> list[dict]:
    """
    Extract meaningful chunks from a single STW PDF.
    This uses a heuristic approach based on the expected structure
    of ICMR STW documents (Headers, bullet points, bold text).
    """
    chunks = []
    filename = filepath.name

    # Extract STW code from filename (e.g., STW_GP_01_Acute_Pharyngitis.pdf -> STW-GP-01)
    stw_code_match = re.search(r"STW_([A-Z]+)_(\d+)", filename)
    stw_code = f"STW-{stw_code_match.group(1)}-{stw_code_match.group(2)}" if stw_code_match else "UNKNOWN"
    
    specialty_map = {
        "GP": "General Practice",
        "GYN": "Gynaecology",
        "ORT": "Orthopaedics",
        "PED": "Pediatrics"
    }
    specialty_code = stw_code_match.group(1) if stw_code_match else ""
    specialty = specialty_map.get(specialty_code, "General")

    # Extract condition from filename
    condition = filename.replace(".pdf", "")
    if stw_code_match:
        condition = condition.replace(stw_code_match.group(0) + "_", "").replace("_", " ")

    logger.info(f"Chunking {filename} (Code: {stw_code}, Specialty: {specialty})")

    try:
        with open(filepath, 'rb') as f:
            reader = pypdf.PdfReader(f)
            for page_num, page in enumerate(reader.pages, start=1):
                text = page.extract_text()
                if not text:
                    continue
                
                # Basic heuristic chunking: split by double newlines or major headings
                # In a real system, we'd use layout analysis or LLM-assisted structural parsing
                # For this assessment, we'll split into logical paragraphs and classify them
                
                paragraphs = re.split(r'\n\s*\n', text)
                
                current_section = "General"
                
                for para in paragraphs:
                    para = para.strip()
                    if not para or len(para) < 10:
                        continue
                        
                    # Try to detect section headers
                    if re.match(r'^(when to refer|treatment|diagnosis|clinical features|red flags)', para, re.IGNORECASE):
                        current_section = para.split('\n')[0].strip()
                        
                    chunk_type = "workflow_step"
                    if "dose" in para.lower() or "mg" in para.lower():
                        chunk_type = "recommendation"
                    elif "avoid" in para.lower() or "contraindicat" in para.lower():
                        chunk_type = "contraindication"
                        
                    chunks.append({
                        "source_file": filename,
                        "stw_code": stw_code,
                        "stw_version": "v1", # Usually found in footer, simplified here
                        "effective_date": "Unknown",
                        "specialty": specialty,
                        "condition": condition,
                        "page_anchor": f"p{page_num}",
                        "chunk_type": chunk_type,
                        "is_local_protocol": False,
                        "content": f"[{current_section}] {para}"
                    })
    except Exception as e:
        logger.error(f"Error parsing PDF {filename}: {e}")
        
    return chunks


def chunk_local_protocol(filepath: Path) -> list[dict]:
    """Parse the local markdown protocol."""
    chunks = []
    filename = filepath.name
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            text = f.read()
            
        # Split by markdown headers
        sections = re.split(r'(?m)^##\s+(.+)$', text)
        
        # Initial text before first header
        if sections[0].strip():
             chunks.append({
                "source_file": filename,
                "stw_code": "LOCAL-01",
                "stw_version": "current",
                "effective_date": "2024-01-01",
                "specialty": "General Practice",
                "condition": "Acute Undifferentiated Fever",
                "page_anchor": "intro",
                "chunk_type": "workflow_step",
                "is_local_protocol": True,
                "content": sections[0].strip()
            })
             
        # Process header/content pairs
        for i in range(1, len(sections), 2):
            header = sections[i].strip()
            content = sections[i+1].strip()
            
            if not content:
                continue
                
            chunks.append({
                "source_file": filename,
                "stw_code": "LOCAL-01",
                "stw_version": "current",
                "effective_date": "2024-01-01",
                "specialty": "General Practice",
                "condition": "Acute Undifferentiated Fever",
                "page_anchor": header.lower().replace(" ", "-"),
                "chunk_type": "recommendation",
                "is_local_protocol": True,
                "content": f"[{header}] {content}"
            })
            
    except Exception as e:
        logger.error(f"Error parsing local protocol {filename}: {e}")
        
    return chunks


def ingest_corpus(db: Session, corpus_dir: str, load_batch: str) -> dict:
    """Read all corpus files, chunk them, and store in DB."""
    path = Path(corpus_dir)
    stats = {"files_processed": 0, "chunks_created": 0, "errors": 0}
    
    if not path.exists():
        logger.error(f"Corpus directory {corpus_dir} not found.")
        return stats
        
    for filepath in path.iterdir():
        if filepath.suffix.lower() == ".pdf":
            chunks = chunk_stw_pdf(filepath)
            for c in chunks:
                chunk_record = CorpusChunk(
                    id=str(uuid.uuid4()),
                    source_file=c["source_file"],
                    stw_code=c["stw_code"],
                    stw_version=c["stw_version"],
                    effective_date=c["effective_date"],
                    specialty=c["specialty"],
                    condition=c["condition"],
                    page_anchor=c["page_anchor"],
                    chunk_type=c["chunk_type"],
                    is_local_protocol=c["is_local_protocol"],
                    content=c["content"],
                    load_batch=load_batch
                )
                db.add(chunk_record)
                stats["chunks_created"] += 1
            stats["files_processed"] += 1
            
    # Process local protocol from data dir
    local_protocol = Path("data") / "local_protocol_acute_fever.md"
    if local_protocol.exists():
        chunks = chunk_local_protocol(local_protocol)
        for c in chunks:
            chunk_record = CorpusChunk(
                id=str(uuid.uuid4()),
                source_file=c["source_file"],
                stw_code=c["stw_code"],
                stw_version=c["stw_version"],
                effective_date=c["effective_date"],
                specialty=c["specialty"],
                condition=c["condition"],
                page_anchor=c["page_anchor"],
                chunk_type=c["chunk_type"],
                is_local_protocol=c["is_local_protocol"],
                content=c["content"],
                load_batch=load_batch
            )
            db.add(chunk_record)
            stats["chunks_created"] += 1
        stats["files_processed"] += 1

    db.commit()
    logger.info(f"Corpus ingestion complete: {stats}")
    return stats
