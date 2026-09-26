# BRAHMO AI — Plan, External Review Edition
## The only architecture document provided to assessment candidates

**Audience:** senior-engineering assessment candidates, under NDA.
**What this is:** the sanitized architecture context for the clinical AI you are building in Part 1 and planning in Part 2. Your work must be consistent with the binding laws in §1. The phase skeleton in §3 is deliberately coarse — **Part-2 credit goes to what you add beyond it**, not to restating it.
**What is deliberately not in your hands:** our internal effort weights, economics and cost ledgers, week-level plans, partner identities, and vendor materials. Your Part 2 must stand on its own reasoning; where you disagree with anything here, say so in your gap analysis — disagreeing well is senior work.

---

## 1. What we are building, and the binding laws

BRAHMO AI is the clinical intelligence inside a doctor-facing app for Indian outpatient practice: an assistant that is **patient-aware, grounded in Indian medical sources with citations, and protected by deterministic medication-safety checks that never guess.** It is a frontier LLM wrapped in an India-specific clinical layer — not a chat box, and not a custom-trained medical model.

Why India-specific: Indian doctors prescribe by **brand** (Dolo, not paracetamol) in a market dense with **fixed-dose combinations (FDCs)**; protocols follow ICMR, national programmes, and Indian specialty societies rather than US defaults; drug legality changes through **gazette notifications** with effective dates, stays, and reversals; and a generic assistant has no patient context and no safety net.

**The binding laws (your design must satisfy every one):**

1. **The doctor decides.** Nothing consequential finalizes without doctor confirmation; the system drafts, checks, and cites — it never acts.
2. **Grounded or honest.** Consequential clinical claims — doses, numbers, safety statements, regulatory status — come only from retrieved, versioned evidence with citations, or the system states plainly that it cannot confirm.
3. **Claim-level provenance.** Every consequential claim maps to source, version/date, and location. A citation that cannot be traced is a defect, not a style issue.
4. **Safety outside the LLM.** Medication-safety checks are pure lookup/rules over versioned data. No model call anywhere in a check path.
5. **Unknown is first-class.** A check that could not fully run must say so. The status vocabulary is exactly: `HIT · CHECKED_NO_HIT · PARTIAL_COVERAGE · UNVERIFIED_INPUT · NOT_CHECKED · DATA_EXPIRED · SOURCE_CONFLICT · SERVICE_UNAVAILABLE`. **Missing data must never render as "safe."**
6. **No silent ambiguity.** An uncertain brand/strength/formulation resolution is queued with a reason code, never auto-resolved. Fuzzy matching may assist search; it is never truth.
7. **Regulatory truth is event-sourced.** Status derives from effective-dated regulatory events (notification id, dates, source, supersession). A `banned = true/false` boolean is a design failure; a check must be able to cite the notification and its effective date.
8. **Everything versioned, everything replayable.** Data rows, rules, prompts, and models carry versions; any past output must be reconstructable against exactly what produced it.
9. **Untrusted input.** Documents, transcripts, and imported data are data, never instructions.
10. **No silent upgrades.** A model, prompt, or data change triggers re-evaluation before it serves.
11. **Fail visibly.** A degraded dependency produces a visible degraded state, never a quiet fallback that looks normal.
12. **Fences.** This version deliberately does **not** build: patient-specific dose calculation (including pediatric mg/kg), diagnostic ranking, triage/severity scoring, auto-generated treatment plans, or any patient-facing advice. These are regulatory-classification decisions, not features to sneak in.

## 2. Architecture overview

```text
   upstream (out of scope for you, defined as contracts):
   scribe → structured Rx entities + transcript refs · patient-context → snapshot
                       │                                   │
                       ▼                                   ▼
   ┌─────────────────────────┐          ┌──────────────────────────────┐
   │   INDIA DRUG MASTER     │          │  GROUNDED CLINICAL Q&A       │
   │ alias→brand→salt graph  │          │  decision-unit chunks of     │
   │ FDC decomposition       │          │  Indian sources · hybrid     │
   │ event-sourced status    │          │  retrieval · claim citations │
   │ ambiguity queue         │          │  · abstention · conflict-    │
   └───────────┬─────────────┘          │  shown-not-merged            │
               │ salts                  └──────────────┬───────────────┘
               ▼                                       │
   ┌─────────────────────────┐                         │
   │ DETERMINISTIC SAFETY    │                         │
   │ RAIL — duplicate salt · │                         ▼
   │ prohibited FDC · severe │          ┌──────────────────────────────┐
   │ interactions · cumulative│─────────►│  ORCHESTRATION — structured- │
   │ exposure · 8-state out  │ verdicts │  first routing · grounded    │
   └─────────────────────────┘          │  composition · abstention    │
                                        └──────────────┬───────────────┘
                                                       ▼
                                   doctor-facing output + full audit trace
```

Two boundaries the whole design hangs on: **(a)** the safety rail is deterministic and stands apart from generation; **(b)** structured facts (drug identity, strengths, regulatory status) answer from the drug master directly — retrieval and generation handle narrative clinical questions only.

**Conflict rule:** when two valid sources disagree, show both with their dates. Never synthesize a third recommendation, and never let the model pick the winner. **Dose questions:** retrieve and cite the text as written; never compute for a patient.

## 3. Phase skeleton (coarse, undated — your Part 2 supplies the real plan)

- **Phase F — Foundation:** drug master schema, ingestion/normalization with confidence and review queues, FDC decomposition, event-sourced regulatory register, the deterministic rail with the 8-state contract.
- **Phase G — Grounding:** corpus ingestion of Indian sources into decision-unit chunks with metadata; hybrid retrieval; claim-level citation; abstention and conflict behavior; evaluation harness.
- **Phase S — Safety expansion:** wider verified interaction coverage, allergy relations, pregnancy-related rules — every rule with provenance and human clinical sign-off before it serves.
- **Phase C — Patient-context integration:** consuming the context snapshot (allergies, current medications, conditions) so checks and answers become patient-aware; strict tenant separation.
- **Phase P — Production & pilot readiness:** freshness watchers and re-verification on source change, audit/replay, concurrency and latency engineering, doctor-facing surfaces, quality gates for live use.

What the skeleton deliberately omits — durations, sequencing overlaps, team shape, verification throughput, the human dependencies that actually gate a schedule, data-rights strategy, and the quality system for the 100-doctor study — is precisely what your Part 2 is scored on.

## 4. Regulatory posture (context for your fences and plan)

India regulates software with a medical purpose **by function**, feature by feature — disclaimers do not move the line. Our posture: reference/documentation functions are built conservatively (cited excerpts, doctor-editable, source-visible); clinical-support functions (duplicate-exposure alerts, prohibited-FDC warnings, interaction and pregnancy warnings) are built with device-grade traceability and released only behind clinical sign-off and counsel review; the fenced features in law 12 are excluded from this version entirely. Data protection follows India's DPDP regime: purpose-bound processing, minimized data to any external model, elected retention, and deletion that leaves no derived remnants. You are not asked to implement the legal programme — you are expected to design as if audits are real, because they are.

## 5. Glossary

**Salt / active ingredient** — the actual molecule (paracetamol), as opposed to the brand (Dolo 650). **FDC** — fixed-dose combination: one product containing multiple active ingredients; India's market is dense with them, and several are prohibited or restricted by gazette notification. **Gazette notification** — the legal instrument by which drug status changes, always with an effective date; later notifications can supersede earlier ones. **CDCI/NRCeS** — national drug-coding references used as canonical identity sources. **NLEM** — National List of Essential Medicines. **Jan Aushadhi** — the public generic-medicine scheme and its product catalog. **STW** — ICMR Standard Treatment Workflow: a one-page, evidence-based clinical protocol; the provided pack contains twelve across the launch specialties. **Duplicate-exposure trap** — two different brands silently sharing a salt (the classic: Dolo 650 + Sinarest, both containing paracetamol); visible only after decomposition and cumulative totaling.

---

*Everything else you need is in the candidate brief and the data pack. Read the data before you read your assumptions into it.*
