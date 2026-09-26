# BRAHMO — Senior Engineering Assessment: Clinical AI
## 01 · CANDIDATE BRIEF

**Role:** Senior/Staff Engineer — Clinical AI (architecture, RAG, data, safety systems)
**Format:** One-week take-home + 90-minute defense session (interview assessment)
**Confidentiality & IP:** NDA applies. All code, data, prompts, and documents produced are work-for-hire and assigned to BRAHMO. No proprietary or third-party-licensed components may be embedded.
**Window:** 7 calendar days from kit handover, fixed deadline, same for all candidates. Spend as much or as little time within the week as you choose — **quality is preferred over early submission; finishing early earns nothing.** Submission format in §9.

---

## 0. What this is

BRAHMO is building a clinical AI for Indian doctors — patient-aware, grounded in Indian medical sources with citations, and protected by deterministic medication-safety checks that never guess. You have been given the same starter materials we prepared for an external build team, and more. We are not hiring implementers alone: we are hiring the person who can **design, architect, identify gaps, choose sources, anticipate what doctors will actually face, and turn all of it into a plan that pure AI-first development can execute.**

The assessment has two parts with separate weightage, plus a defense session:

| Part | What | Weight |
|---|---|---|
| **Part 1** | Implementation of the build spec (§3) from the provided inputs | 45 |
| **Part 2** | Your end-to-end plan to a production clinical AI (§6) | 35 |
| **Defense** | 90-minute live session (§8) | 20 |

A week is enough to complete the mandatory core well. Depth of Part 2, the stretch items, and the quality of your judgment are where candidates separate. Wherever you do cut scope, an honest gaps register — what's missing and why you chose so — is scored, never penalized for honesty.

## 1. Ground rules

- **AI-first development is strongly recommended — it is how this company builds.** Use whatever coding agent or assistant you prefer, and two tools in combination is perfectly fine. If you use AI tools (we expect you will), **the prompts/instructions you actually used are a deliverable.** Manual coding is permitted; your working style will be discussed at the defense either way.
- A **held-back evaluation set exists.** After submission we will run your system against questions and drug cases you have not seen. Scoring on that set: correct = +1 · correctly refused/flagged as unknown = 0 · **confidently wrong = −1.** A system that admits what it doesn't know outscores one that guesses. Design accordingly.
- **Create a fresh private Git repository of your own** for this build — the clinical AI is an independent codebase by design. Repository structure, conventions, and stack are your choices; record the reasoning in `DESIGN.md`. Grant us read access at submission and preserve full commit history — we read it.
- All provided data is synthetic or public. Do not use real patient data from anywhere.
- **Clarification budget:** one written Q&A round, submitted by end of Day 2. Ask anything. The questions you ask are part of the evaluation.
- **LLM usage runs on your own accounts and tools.** If API spend is a genuine constraint, say so in the Day-2 Q&A and we will provision a capped key — cost is never a reason to skip evaluation runs.

## 2. Day-0 kit (provided at start)

1. **Architecture context:** `BRAHMO_AI_Plan_External_Review_Edition.md` — read it first; your work must be consistent with its binding laws.
2. Data pack (individual files — see `00_PACKET_INDEX.md`): national drug code extract (CDCI subset), NLEM extract, Jan Aushadhi extract, banned-FDC gazette event set, a clinic pharmacy stock file, a severe-interaction seed list (ingredient-level), the Standard Treatment Workflow one-pager pack (PDF) for the launch specialties, and the sample question set.
3. `TEMPLATES.md` — the SUBMISSION, DESIGN, GAPS-REGISTER, and Q&A skeletons in one file; copy each into its own file in your repo.

*(Note: the data pack is prepared for this assessment. Treat every file as real-world input — messy, possibly imperfect. Handling its imperfections correctly is part of the work.)*

## 3. PART 1 — The build spec

### Module A — India Drug Master + Deterministic Safety Rail *(core, mandatory)*

Build the foundation layer that lets clinical safety checks run at the salt/ingredient level while doctors work with Indian brand names.

1. **Drug master schema** — brand/SKU → formulation → strength → active ingredient(s), with FDC (fixed-dose combination) decomposition into individual salts + strengths. Versioned: every row carries source, source version/date, and load batch, so any check is reproducible against the exact data version used. Schema ships as numbered migrations.
2. **Normalization pipeline** — ingests the provided datasets. AI/LLM-assisted mapping is expected and encouraged, with verification built in: every mapping carries a confidence score and method tag.
3. **Ambiguity handling** — uncertain brand/formulation/strength resolutions are **never silently auto-resolved.** They land in a review-queue structure with reason codes. Silent guessing is a gate failure.
4. **FDC decomposition set** — at least 100 real FDC products decomposed to salt + strength with confidence scores. (We verify a sample against a held-out clinician-checked key after submission.)
5. **Regulatory status, event-sourced** — status derives from effective-dated regulatory events (notification id, dates, source, supersession). A plain `banned = true/false` boolean is a design failure. Your check output must be able to cite the notification and its effective date.
6. **Deterministic safety rail** — given a draft prescription (brand-level products): decompose to salts and check (a) duplicate active ingredient across products, (b) prohibited/restricted FDC per the event-sourced status, (c) severe interactions against the seed list, and (d) **cumulative same-ingredient exposure across the whole prescription** — total each shared active ingredient across all items into a per-ingredient daily figure (e.g., total paracetamol/day when several products contain it); a duplicate-ingredient HIT must carry this aggregate as its evidence. **Pure lookup logic — no LLM anywhere in the check path.** Every check returns exactly one of: `HIT · CHECKED_NO_HIT · PARTIAL_COVERAGE · UNVERIFIED_INPUT · NOT_CHECKED · DATA_EXPIRED · SOURCE_CONFLICT · SERVICE_UNAVAILABLE` — with severity, evidence, and rule + data versions. **Missing data must never render as "safe."**
7. **Seeded demonstration** — 10 test prescriptions (template provided; you complete): known-bad cases and clean cases, rail output shown for each. Include at least one case where the danger is only visible through FDC decomposition **plus** the cumulative total — two different brands sharing a salt, neither individually over-dose.

### Module B — Grounded clinical Q&A slice (mini-RAG) *(core, mandatory)*

Using the provided STW one-pager pack (in `corpus/`) **plus** `data/local_protocol_acute_fever.md` — and nothing else:

1. **Chunking** into clinically meaningful decision units (a recommendation, a workflow step, a contraindication) — never blind token slices. Each unit carries: source, page anchor, specialty, condition, publication/effective dates, version.
2. **Retrieval** — hybrid (lexical + semantic) with metadata filtering; structured facts (drug identity, regulatory status) answer from Module A directly, never from retrieval.
3. **Grounded answering** — for the provided sample question set (11 questions): answers cite at the claim level (source, page). **Consequential clinical numbers come only from retrieved text or the system abstains** stating why and what's missing. Questions your corpus cannot support must produce a clean abstention, not an attempt. If two sources conflict, show both with dates — never synthesize a third recommendation. Dose questions: retrieve and cite the text as written — **never calculate a dose for a patient.** The local protocol is organization-level knowledge: answers drawn from it must be labeled as the clinic's own protocol, and a question about national guidance must return the national workflow even where the local protocol diverges — divergence is shown, never hidden.
4. **Mini-eval** — a small runnable harness scoring your own system on the sample questions (correct / abstained / wrong), so quality is measured, not claimed.

### Module C — One end-to-end trace *(core, thin)*

One script or endpoint that takes {a draft prescription + one clinical question} and returns a single JSON trace: normalization results (including anything unresolved), all safety-check results in the §A.6 contract, the grounded answer with citations or abstention, and the versions of every dataset/prompt/model used. This is the integration proof — it should be thin, not polished.

### Stretch (optional, only after core is solid)

Any of: alias handling for local/colloquial brand spellings · a freshness mechanism (what happens when a new gazette notification arrives) · a simple doctor-facing rendering of check states · multi-tenant separation sketch. Stretch work earns credit only if the core gates pass.

## 4. Working method (required, not optional)

- The prompt library actually used (organized, replayable) + a `CLAUDE.md`-style conventions file are deliverables.
- `DESIGN.md` **opens with** a one-paragraph restatement of the system in your own words and the **three assumptions in our materials you consider riskiest** — then records every significant decision as: decision → why → rejected alternative(s) → implication. We are explicitly buying your judgment; make it legible.
- No hardcoded constants: thresholds, list locations, config values load from config.
- Every data row and every check result traceable to source + version.
- Tests included; a fresh-machine reproduction from your README must take under 1 hour.
- A short `SCALE.md`: where your Part-1 design strains at 100× data volume and 100 concurrent users, and what you would change first. One page maximum — it feeds your Part 2.

## 5. Part 1 acceptance gates (binary)

- **G1.** Fresh-machine reproduction from README < 1 hour.
- **G2.** Decomposition accuracy ≥ 95% on our held-out verification sample.
- **G3.** Zero silent resolutions — every ambiguous mapping appears in the review queue with a reason code.
- **G4.** Rail demonstration: all known-bad seeded prescriptions flagged; zero false negatives; unknowns rendered as unknowns.
- **G5.** 100% provenance on data rows and check results.
- **G6.** No uncited consequential clinical number anywhere in Module B output.
- **G7.** `DESIGN.md` decisions each carry a why and at least one rejected alternative.

## 6. PART 2 — Your plan to the finished clinical AI

**The goal you are planning to:** a **production** clinical AI that **100 doctors can use simultaneously**, each running **at least 1,000 real clinical questions** — the questions they currently take to ChatGPT or Claude — against our system, with their **satisfaction measured and compared** against those general assistants. Your plan ends when that test can run and succeed.

You choose the duration — **anywhere from 3 to 6 weeks** — and you must defend the choice. The plan must be executable by a small team using **pure AI-first development**, starting from your Part 1 codebase. Required contents:

1. **Completion architecture** — what exists after Part 1, what's missing, and the full target architecture (grounding corpus at scale, safety coverage, patient-context integration, orchestration, freshness, audit, multi-tenancy, concurrency for 100 simultaneous users).
2. **Week-by-week plan** with binary gates per week — deliverables and pass/fail conditions, not activities. State your team shape and what AI development covers vs what humans must do.
3. **Sources and data strategy** — which Indian sources you would use for corpus and safety content, what is free vs licensed vs must-be-built, rights considerations, and rough costs.
4. **Gap analysis** — at least **three concrete weaknesses, risks, or missing pieces** you found in the materials we gave you, and what you'd do about them. Disagreeing well is senior work.
5. **The doctor's reality** — the problems doctors will actually face using this (trust, speed, alert fatigue, unanswerable questions, language, workflow interruption...) and how your plan handles each.
6. **The quality system** — define "excellent" operationally for the 100-doctor test: what you measure, the gates a release must pass, how the satisfaction comparison against ChatGPT/Claude is designed so it's fair and meaningful, and how 100,000 answers get quality-assured without 100,000 manual reviews.
7. **Dependencies and critical path** — what actually gates your timeline (name the things that are not code).
8. **Fences** — what you deliberately will NOT build for this version, and why.
9. **Top 10 risks** with mitigations, and a rough cost picture (infra, data, model usage, people).

Format: one markdown document, as long as it needs to be and no longer. Diagrams welcome.

## 7. Auto-fail conditions (either part)

Any silent resolution of an ambiguous drug · a fabricated or misattributed citation · a patient-specific dose calculator · missing provenance · rendering an unchecked/unknown state as safe · claiming accuracy you did not measure · undisclosed plagiarism of the plan from public sources.

## 8. Defense session (90 minutes, after submission)

Live walkthrough of your system and plan; we will change one requirement live and ask you to walk through what happens in your architecture; we will ask you to extend the design verbally; and we will ask what your AI coding tools got wrong and how you caught them. Bring nothing new — defend what you submitted.

## 9. Submission

Grant repository access and push your final commit before the deadline; place `SUBMISSION.md` at repo root linking: how to run, `DESIGN.md`, gaps register, prompt library, mini-eval results, the Part 2 plan, and anything unfinished with your prioritization reasoning. Late submissions are scored on what was pushed at the deadline.

*Ambiguity you surface in the Day-2 Q&A costs nothing; ambiguity discovered on Day 6 costs the submission. Good luck — we're looking forward to reading how you think.*
