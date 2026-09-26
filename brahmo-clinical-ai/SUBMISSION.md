# BRAHMO Clinical AI — Submission

## Quick Links
- **How to Run**: See [README.md](./README.md) for full fresh-machine reproduction steps.
- **Design Decisions**: See [DESIGN.md](./DESIGN.md) (includes restatement and 3 riskiest assumptions).
- **Gaps & Honesty**: See [GAPS_REGISTER.md](./GAPS_REGISTER.md) for what was cut or found missing.
- **Prompt Library**: See [prompts/](./prompts/) and [CLAUDE.md](./CLAUDE.md).
- **Evaluation Results**: See [outputs/mini_eval_results.json](./outputs/mini_eval_results.json).
- **Scale Plan**: See [SCALE.md](./SCALE.md).
- **Part 2 Plan**: See [PART2_PLAN.md](./PART2_PLAN.md).

## What's Completed
- [x] Module A (Drug Master + Safety Rail)
- [x] Module B (Grounded Q&A)
- [x] Module C (E2E Trace)
- [x] Required Documents

## Unfinished / Prioritization Reasoning
- **Multi-tenant separation sketch**: Decided to omit for time, as this was a stretch goal and focus was placed on getting the core Modules A and B solid, specifically the event-sourced regulatory status and determinism in the safety rail.
- **Stretch Goals**: Focused entirely on the mandatory core gates (G1-G7) as required before stretching.

All data provenance and citations are fully implemented as requested.
