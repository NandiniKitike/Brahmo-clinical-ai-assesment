# Brahmo Clinical AI — Assessment Submission

> Senior Engineering Assessment · Clinical AI · India Drug Master + Grounded Q&A

## System Overview

BRAHMO Clinical AI is a doctor-facing clinical intelligence layer for Indian outpatient practice. It combines:
1. **India Drug Master** — brand → salt graph, FDC decomposition, event-sourced regulatory status
2. **Deterministic Safety Rail** — pure lookup checks (no LLM), 8-state output contract
3. **Grounded Clinical Q&A** — hybrid RAG over Indian STW protocols, claim-level citations
4. **End-to-End Trace** — single JSON output proving all three systems work together

## Quick Start (Fresh Machine, < 1 Hour)

### Prerequisites
- Python 3.11+
- PostgreSQL 15+ with `pgvector` extension
- Google Gemini API key (free tier sufficient)

### Setup

```bash
# 1. Clone the repo
git clone <your-repo-url>
cd brahmo-clinical-ai

# 2. Create virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env: add GEMINI_API_KEY and DATABASE_URL

# 5. Create database
createdb brahmo_clinical

# 6. Run migrations (in order)
python -m alembic upgrade head

# 7. Load all data
python scripts/load_all_data.py

# 8. Run the application
uvicorn app.main:app --reload
```

### Verify Installation

```bash
# Run the test suite
pytest tests/ -v

# Run Module B mini-eval
python scripts/run_mini_eval.py

# Run Module C end-to-end trace
python scripts/run_e2e_trace.py
```

### Expected output
- API running at http://localhost:8000
- Docs at http://localhost:8000/docs

---

## Repository Structure

```
brahmo-clinical-ai/
├── README.md
├── SUBMISSION.md
├── DESIGN.md
├── SCALE.md
├── GAPS_REGISTER.md
├── CLAUDE.md
├── .env.example
├── requirements.txt
├── alembic.ini
│
├── alembic/
│   └── versions/          # Numbered DB migrations
│
├── app/
│   ├── main.py            # FastAPI app entry point
│   ├── config.py          # All config loaded from env
│   ├── models/            # SQLAlchemy ORM models
│   ├── schemas/           # Pydantic request/response schemas
│   ├── api/               # API route handlers
│   ├── drug_master/       # Module A — drug master + safety rail
│   │   ├── normalizer.py
│   │   ├── fdc_decomposer.py
│   │   ├── regulatory.py
│   │   └── safety_rail.py
│   └── rag/               # Module B — grounded Q&A
│       ├── chunker.py
│       ├── embedder.py
│       ├── retriever.py
│       └── answerer.py
│
├── data/                  # Provided data files (read-only)
│   ├── cdci_drug_subset.csv
│   ├── nlem_extract.csv
│   ├── jan_aushadhi_extract.csv
│   ├── pharmacy_stock.csv
│   ├── regulatory_gazette_events.csv
│   ├── severe_interaction_seed.csv
│   ├── seed_prescriptions_template.csv
│   └── local_protocol_acute_fever.md
│
├── corpus/                # STW PDF files
│   └── STW_*.pdf
│
├── scripts/
│   ├── load_all_data.py   # Master data loader
│   ├── run_mini_eval.py   # Module B evaluation harness
│   └── run_e2e_trace.py   # Module C end-to-end trace
│
├── prompts/               # Prompt library (organized, replayable)
│   ├── normalization/
│   ├── fdc_decomposition/
│   └── README.md
│
├── outputs/               # Generated outputs checked in
│   ├── seeded_prescriptions_rail_output.json
│   ├── mini_eval_results.json
│   └── e2e_trace_sample.json
│
└── tests/
    ├── test_drug_master.py
    ├── test_safety_rail.py
    └── test_rag.py
```

---

## Module Summary

### Module A — India Drug Master + Deterministic Safety Rail
- Ingests: CDCI drug subset, NLEM, Jan Aushadhi, pharmacy stock (treated as untrusted)
- Decomposes FDCs to individual salts with confidence scores
- Event-sourced regulatory status (never a boolean)
- Safety checks: duplicate ingredient, prohibited FDC, severe interaction, cumulative exposure
- All ambiguous resolutions → review queue with reason code (never silent)

### Module B — Grounded Clinical Q&A
- Corpus: 13 STW PDFs + local fever protocol
- Chunking: clinically meaningful decision units with full metadata
- Retrieval: hybrid (BM25 lexical + pgvector semantic)
- Answers: claim-level citations; abstention when corpus cannot support

### Module C — End-to-End Trace
- Single endpoint: `POST /api/v1/trace`
- Input: `{ prescription: [...], question: "..." }`
- Output: full JSON with normalization results, safety rail output, grounded answer, all versions

---

## Links

- [DESIGN.md](./DESIGN.md)
- [SCALE.md](./SCALE.md)
- [GAPS_REGISTER.md](./GAPS_REGISTER.md)
- [Prompt Library](./prompts/)
- [Mini-eval Results](./outputs/mini_eval_results.json)
- [Seeded Prescription Rail Outputs](./outputs/seeded_prescriptions_rail_output.json)
- [Part 2 Plan](./PART2_PLAN.md)
