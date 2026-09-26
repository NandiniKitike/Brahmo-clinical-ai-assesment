# PART 2 — The Production Plan

**Goal:** A production clinical AI that 100 doctors can use simultaneously, running ≥1,000 real clinical questions each, with satisfaction measured against ChatGPT/Claude.

**Timeline:** 4 Weeks (Aggressive AI-assisted schedule)

## 1. Completion Architecture (Target)
**What exists after Part 1:**
- Relational drug master with exact-match normalization.
- Event-sourced regulatory checking.
- Deterministic 8-state safety rail.
- In-memory hybrid RAG over 13 STW PDFs.

**What is missing & required for Target:**
- Asynchronous LLM-based normalization pipeline for messy clinic stock data.
- Tenant separation (100 doctors = 100 isolated contexts).
- Postgres-native Full Text Search (FTS) to replace in-memory BM25.
- Real-time caching (Redis) for regulatory status lookups.
- Upstream "Scribe" integration to convert voice/text into structured draft prescriptions.
- Patient-context integration (Phase C) so safety rails can check against patient allergies and existing meds.

## 2. Week-by-Week Plan (4 Weeks)
**Team Shape:** 2 Senior Engineers (using AI pairs), 1 Clinical Data Reviewer.

| Week | Phase | AI Dev | Human Dev/Review | Gate (Pass/Fail) |
|---|---|---|---|---|
| **W1** | **Scale & Tenants** | Migrate BM25 to Postgres FTS. Implement Multi-tenant DB schema with Row Level Security (RLS). Build Redis caching for regulatory status. | Write integration tests. Code review of RLS constraints. | 1M messy pharmacy rows ingest in < 1hr. Latency for 100 concurrent RAG queries < 2s. |
| **W2** | **Patient Context** | Build Phase C (Patient Context snapshot integration). Expand Safety Rail to check allergies (cross-referenced with ingredient graph). | Clinical mapping of allergy classes. Review of safety rail allergy outputs. | Safety rail correctly flags 100% of known-bad allergy interactions. |
| **W3** | **Scribe & Pipeline** | Build async LLM worker to clear `ReviewQueue`. Build API endpoints to receive upstream Scribe transcript/structured drafts. | Build the evaluation harness to compare answers against ChatGPT. | End-to-end trace works from raw text input through to final JSON output. |
| **W4** | **Quality & Pilot** | Implement UI rendering logic for the 8 check states. Final load testing. | Final clinical sign-off on rail behavior. Onboard pilot doctors. | System handles 100 simulated concurrent users with zero 5xx errors. Go/No-Go decision. |

## 3. Sources and Data Strategy
To support real clinical practice beyond the 13 STW PDFs, we need:
- **Corpus (Free):** Full ICMR STW library, NCDC guidelines, Ministry of Health (MoHFW) national programmes (e.g., NTEP for TB, NVBDCP for Malaria).
- **Safety/Interactions (Must-be-built/Licensed):** The provided 15-pair seed is a toy. We must license a professional interaction database (e.g., Lexicomp or Micromedex via API) OR dedicate clinical teams to curate an Indian-specific interaction graph based on CDSCO data. 
- **Regulatory (Must-be-built):** CDSCO gazette notifications are published as unstructured PDFs. We must build an automated scraper + LLM extraction pipeline to turn them into `RegulatoryEvent` rows (The "Freshness Watcher").

## 4. Gap Analysis (Risks in provided materials)
1. **The CDCI subset is static and incomplete.** *Action:* We cannot rely on CDCI alone. We must cross-reference it with CIMS India or a commercial equivalent to handle real-world local brands and aliases.
2. **"Local vs National" conflict rule is too simplistic.** In reality, a local clinic protocol often *overrides* the national workflow for operational reasons (e.g., drug availability). *Action:* Implement a tenant-level config allowing a clinic to prioritize local protocols over national ones in the fusion ranker.
3. **No handling of renal/hepatic dosing.** The materials explicitly fence off dose calculation, but doctors *will* ask "Is Dolo 650 safe in CKD?". *Action:* The RAG system must be specifically tuned to retrieve renal/hepatic contraindications and surface them as grounded facts, even if it abstains from calculating the GFR-adjusted dose.

## 5. The Doctor's Reality
- **Trust:** Doctors don't trust black boxes. *Handling:* Every safety check surfaces exactly *why* it flagged (e.g., "Cumulative paracetamol = 1300mg"). Every answer cites a specific page.
- **Speed:** Outpatient consults are 3 minutes long. *Handling:* Sub-2-second latency. No spinning loaders.
- **Alert Fatigue:** If every prescription triggers a "PARTIAL_COVERAGE" warning because of missing data, doctors will turn it off. *Handling:* UI design must clearly differentiate between a "HIT" (Red, severe danger) and "PARTIAL_COVERAGE" (Grey, info only).

## 6. The Quality System
For the 100-doctor test:
- **Operational Excellence:** p95 latency < 2s. 99.9% uptime during clinic hours (9AM-9PM IST).
- **Measuring Satisfaction:** The UI will present the BRAHMO answer alongside a baseline LLM answer (blinded A/B test). The doctor clicks which is more helpful.
- **QA at Scale (100,000 answers):** We cannot manually review. We will use an LLM-as-a-Judge pipeline (using a stronger model like GPT-4o) running async to evaluate answers against the 3 binding laws (grounded, cited, no synthesis). Any answer flagged by the judge is sent to human review to refine the RAG pipeline.

## 7. Dependencies and Critical Path
What actually gates the timeline:
1. **Clinical sign-off on the expanded interaction seed list.** (Cannot launch without a verified safety net).
2. **Legal review of the multi-tenant RLS schema.** (Data privacy constraint).
3. **Upstream Scribe integration.** (If the Scribe can't reliably extract `doses_per_day`, the cumulative rail fails).

## 8. Fences (What we will NOT build)
- **NO patient-specific dose calculation.** (Requires device-grade certification).
- **NO diagnostic suggestions.** (We are a reference tool, not a diagnostic engine).
- **NO automated chart updates.** (The doctor must always be the one to confirm and commit).

## 9. Top Risks & Mitigations
| Risk | Mitigation | Cost Impact |
|---|---|---|
| Gazette scraping pipeline breaks on new PDF formats | Human-in-the-loop review queue for all new gazette ingestions | Low (Internal clinical ops time) |
| Multi-tenant data bleed | Enforce Row Level Security (RLS) at the Postgres level, bypassing application logic | Medium (Dev time) |
| Unpredictable LLM latency (Gemini/Claude) | Fallback to a secondary provider (Azure OpenAI) automatically | High (Redundant API costs) |
| Poor Scribe extraction of brands | Robust fuzzy matching in the normalizer + easy UI for doctor to correct | High (Dev + UI iteration) |
