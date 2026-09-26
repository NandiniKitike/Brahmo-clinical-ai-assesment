# SCALE.md

## Where this strains at 100× data volume and 100 concurrent users

The current Part-1 design is a robust proof of concept for the architecture boundaries, but it will strain under production load in three specific areas:

### 1. The Review Queue Bottleneck (Data Ingestion)
**The Strain:** At 100x data volume (ingesting millions of messy pharmacy stock strings from 100 different clinics), the exact-match normalizer will fail on a huge percentage. The `ReviewQueue` will grow by tens of thousands of items daily. 
**The Break:** Human reviewers cannot clear this queue fast enough. Binding law §6 (no silent ambiguity) means unresolved items trigger `UNVERIFIED_INPUT` on safety checks, degrading the doctor's experience to the point of abandonment.
**First Change:** Implement an async, LLM-driven normalization worker. It pulls from the `ReviewQueue`, uses few-shot prompting to resolve variants to canonical DB IDs, and assigns a confidence score. If `confidence > 0.85`, it auto-resolves. Only edge cases drop to human review.

### 2. Hybrid Retrieval Latency (RAG)
**The Strain:** The current hybrid retrieval runs BM25 (lexical) in memory via `rank_bm25` and semantic search via `pgvector`. At 100x corpus size (thousands of STWs, society guidelines, textbooks) and 100 concurrent doctors asking questions, the in-memory BM25 index will consume too much RAM, and the Python loop for Reciprocal Rank Fusion (RRF) will block the event loop, driving p95 latency above acceptable limits (doctors expect < 3s).
**The Break:** The FastAPI application becomes CPU-bound, causing connection timeouts during peak clinic hours.
**First Change:** Push both search modalities and the RRF fusion directly into PostgreSQL. Use `pgvector` with HNSW indexes for semantic, and Postgres native Full Text Search (`to_tsvector`) for lexical. Write a single SQL query that executes both and fuses them on the database server.

### 3. Regulatory Status Event-Sourcing (Database Load)
**The Strain:** The deterministic safety rail calculates regulatory status dynamically by querying `RegulatoryEvent` and walking the supersession chain backward for every product in every prescription, on every check. At 100 concurrent users generating prescriptions every few minutes, this generates immense read-load and complex JOINs against the database.
**The Break:** Database CPU exhaustion. Checking a 5-drug prescription takes seconds instead of milliseconds.
**First Change:** Implement a materialized view or a Redis cache layer for "Current Regulatory Status". When a new gazette notification is ingested (Phase P freshness watcher), it triggers a re-calculation of the cached status for affected products. The safety rail then performs a simple O(1) key-value lookup against the cache, ensuring the check path remains lightning fast while preserving the event-sourced truth in the underlying DB.
