# BRAHMO — Senior Engineering Assessment · PACKET INDEX
**You read exactly three documents: this index → `01_CANDIDATE_BRIEF.md` → the External Review Edition. Everything else is input data or a template — open it when the brief tells you to.**
Everything ships as individual files (no archive). NDA + IP assignment are signed before you receive this packet. You build in a fresh **private repository you create**; grant us read access at submission. One written Q&A round is due by end of Day 2 (`TEMPLATE_QA_FORM.md`).

| File | What it is | You use it for |
|---|---|---|
| `00_PACKET_INDEX.md` | This packing list | Confirming you have every file |
| `01_CANDIDATE_BRIEF.md` | The assessment itself: Part 1 build spec, Part 2 plan spec, gates, auto-fails, defense format, submission rules | Your single source of requirements |
| `02_BRAHMO_AI_Plan_External_Review_Edition.md` | The only architecture document you receive: what we're building, the 12 binding laws, architecture overview, coarse phase skeleton, regulatory posture, glossary | Part 1 must be consistent with its laws; Part 2 is credited for what you add beyond its §3 skeleton |
| `data/cdci_drug_subset.csv` | National drug-code style extract: ~2,000 products incl. 160 fixed-dose combinations — brand, manufacturer, form, ingredients, strengths, source/version | Module A: drug master, normalization, FDC decomposition |
| `data/nlem_extract.csv` | Essential-medicines extract (salt level, care levels) | Cross-referencing and validation signal |
| `data/jan_aushadhi_extract.csv` | Public generic-scheme catalog extract (generic, strength, pack, MRP) | Cross-referencing; affordability context |
| `data/regulatory_gazette_events.csv` | 12 regulatory events with notification ids, published & effective dates, actions, and supersession links | Module A: event-sourced regulatory status (a boolean is a design failure) |
| `data/pharmacy_stock.csv` | A clinic pharmacy stock file, ~800 rows, real-world messy (billing strings, pack tokens, imperfections) | Module A ingestion; treat every row as untrusted real-world input |
| `data/severe_interaction_seed.csv` | 15 severe ingredient-level interaction pairs | Module A rail check (c) |
| `data/seed_prescriptions_template.csv` | 10 draft prescriptions (18 lines) with empty output columns you complete | Module A.7 seeded rail demonstration |
| `data/sample_questions.md` | The 11 Module-B questions | Module B grounded answering + your mini-eval |
| `corpus/STW_*.pdf` — 13 files | Standard Treatment Workflow one-pagers across GP, Pediatrics, Gynaecology, Orthopaedics. Treat each page's code, version, effective date, and supersession metadata as first-class data | Module B corpus (chunking, retrieval, citation, abstention) |
| `TEMPLATES.md` | All four required skeletons (SUBMISSION · DESIGN with the restatement + 3-riskiest-assumptions opener · GAPS REGISTER · Day-2 Q&A form) in one file | Copy each section into its own file in your repo |
| `data/local_protocol_acute_fever.md` | One clinic's own fever protocol — organization-level knowledge | Module B corpus; label it as the clinic's protocol, never as national guidance |

Two reminders from the brief that decide outcomes: **missing data must never render as "safe,"** and a held-back set will be run against your system after submission where **a confident wrong answer scores below no answer.** Read the data before you read your assumptions into it.
