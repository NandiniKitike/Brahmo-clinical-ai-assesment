# DESIGN.md

## 0. The system in my own words
BRAHMO Clinical AI is a doctor-facing clinical intelligence layer for Indian outpatient practice. It provides two distinct capabilities that must never bleed into each other: (1) a deterministic, LLM-free safety rail that decomposes Indian brand names into active ingredients to check for duplicate exposures, prohibited FDCs, and severe interactions; and (2) a grounded RAG system that answers clinical narrative questions based strictly on provided Indian STW protocols. This Part-1 build proves the core boundaries of the architecture: safety rules are lookup-based and event-sourced, ambiguity is explicitly queued rather than guessed, and clinical claims are tied to chunk-level citations.

## 0.1 The three riskiest assumptions I see in the provided materials
1. **The CDCI data is complete and accurate enough for exact-matching.** We are trusting that `ingredient_1`, `strength_1_mg`, etc., are correctly parsed from the original text. If this source data has parsing errors, our exact-match FDC decomposition inherits them silently.
2. **The "local protocol" vs "national workflow" conflict rule is sustainable at scale.** We assume doctors want to see both when they conflict, but in a high-stress clinical environment, showing conflicting recommendations without a clear hierarchy might increase cognitive load and alert fatigue.
3. **Doctors will provide enough dosage context in unstructured text.** The cumulative exposure check relies on knowing `doses_per_day` to calculate total mg/day. If the Scribe upstream fails to extract this reliably, the safety rail degrades to `PARTIAL_COVERAGE` frequently, training doctors to ignore it.

## Decisions

### D-001 — PostgreSQL + pgvector as the single data store
- **Decision:** Use PostgreSQL for both the relational drug master and the vector store (via `pgvector`).
- **Why:** Keeps the architecture simple (one DB). The drug master requires strong relational integrity (provenance, foreign keys, event sourcing), and `pgvector` is more than capable for a 100-doctor scale corpus.
- **Rejected alternative(s) and why not:** 
  - *Dedicated vector DB (Pinecone, Qdrant):* Adds unnecessary network hops and infrastructure complexity for a corpus that easily fits in memory.
  - *SQLite:* Lacks robust vector search and concurrency needed for the production plan.
- **Implication / what this constrains later:** We are bound to Postgres for vector search, which might require tuning `ivfflat` or `hnsw` indexes at massive scale, though it's fine for the foreseeable future.

### D-002 — Normalization: Exact match first, review queue fallback
- **Decision:** CDCI ingestion uses exact matching on pre-parsed columns (confidence 1.0). Pharmacy stock ingestion uses exact matching on cleaned strings; if a match is ambiguous or missing, it goes to the `ReviewQueue` (confidence 0.0). LLM assistance is a secondary async pass (not implemented in this core, but architecturally designed for).
- **Why:** Satisfies binding law §6 (No silent ambiguity). We never want the system to guess that "Dolo 650" is "Dolo 500" if "Dolo 650" isn't in the DB.
- **Rejected alternative(s) and why not:** 
  - *Fuzzy matching on everything:* Leads to silent false positives (e.g. matching a pediatric suspension to an adult tablet).
- **Implication / what this constrains later:** A human-in-the-loop (or high-confidence LLM) review tool must be built to clear the `ReviewQueue`.

### D-003 — Event-sourced regulatory status via `RegulatoryEvent` table
- **Decision:** Status is calculated at query time (or cached) by walking backward through a chain of `RegulatoryEvent` rows (effective date, action, supersedes).
- **Why:** Satisfies binding law §7. Allows the system to cite the exact gazette notification and explain complex legal states (like `STAY_GRANTED`).
- **Rejected alternative(s) and why not:** 
  - *Adding a `banned` boolean to the drug product:* Explicitly forbidden by the prompt. Fails to capture effective dates or legal stays.
- **Implication / what this constrains later:** Checking status requires joining/querying events. We implemented `ProductRegulatoryEvent` to link FDC pattern bans to specific products at ingestion time to keep the check fast.

### D-004 — RAG Chunking: Semantic boundaries over token slices
- **Decision:** The STW PDFs are chunked heuristically by paragraph/heading boundaries (e.g. `[Treatment]`, `[Red Flags]`), resulting in distinct "decision units" rather than arbitrary 500-token blocks.
- **Why:** Satisfies binding law §1 ("clinically meaningful decision units"). If a dose recommendation is split across a token boundary, the LLM might hallucinate the missing context.
- **Rejected alternative(s) and why not:** 
  - *LangChain RecursiveCharacterTextSplitter:* Blind to medical context; often splits a condition from its treatment.
- **Implication / what this constrains later:** Adding new, differently formatted PDFs to the corpus requires writing custom parsing heuristics for that format.

### D-005 — Hybrid Retrieval (pgvector + BM25) with RRF
- **Decision:** Retrieval uses both semantic similarity (`text-embedding-004` + `pgvector`) and lexical matching (BM25Okapi), combined using Reciprocal Rank Fusion (RRF).
- **Why:** Medical queries often contain highly specific jargon, acronyms, or drug names that embeddings sometimes blur together but BM25 nails perfectly.
- **Rejected alternative(s) and why not:** 
  - *Semantic search only:* Misses exact keyword matches for obscure diseases or acronyms.
- **Implication / what this constrains later:** BM25 requires tokenizing the corpus. Currently done in-memory, but at scale requires Postgres Full Text Search (FTS).

### D-006 — LLM Answers: Strict zero-temperature generation
- **Decision:** Gemini 1.5 Flash is used for Module B with `temperature=0.0` and a strict system prompt enforcing abstention and citation formats.
- **Why:** We need deterministic, reproducible adherence to the text. Hallucination is an auto-fail.
- **Rejected alternative(s) and why not:** 
  - *Higher temperature (0.7) for "natural" sounding answers:* Increases risk of the LLM synthesizing outside knowledge or combining conflicting sources.
- **Implication / what this constrains later:** The answers will sound dry and formulaic, which is exactly what we want for a clinical reference tool.
