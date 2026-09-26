# AI-First Development Conventions for BRAHMO Clinical AI

This file serves as the core instruction set for any LLM/Coding Agent working on this repository. 
When building or modifying this codebase, you MUST adhere to these rules:

## 1. Safety and Abstractions
- **No LLM in safety paths:** Never place an LLM API call in the path of a safety check (`app/drug_master/safety_rail.py`). Safety checks must be purely deterministic, relying on database lookups.
- **Strict output constraints:** The safety rail must only return one of the 8 states defined in `CheckState` (`app/models.py`). Do not invent new states. Missing data is never "safe"—it is `UNVERIFIED_INPUT` or `NOT_CHECKED`.
- **Event-sourcing over booleans:** Do not add a `banned` or `is_safe` boolean column to the `DrugProduct` table. Regulatory status must be derived from `RegulatoryEvent` history.

## 2. Provenance and Versioning
- **Full traceability:** Every database row must contain `source`, `source_version`, and `load_batch` columns. 
- **No silent ambiguity:** If a data pipeline is uncertain about a resolution (e.g., matching a messy string to a drug brand), it must queue the item in the `ReviewQueue` with an `AmbiguityReasonCode`. Do not guess silently.

## 3. RAG and Grounding (Module B)
- **Zero-temperature generation:** When calling the LLM to generate answers (`app/rag/answerer.py`), temperature must be set to `0.0`.
- **No synthesis:** If the corpus provides two conflicting recommendations, surface both with their effective dates. Do not attempt to merge them or pick the "correct" one.
- **Claim-level citations:** Answers must append citations pointing back to the specific chunk ID or page anchor.
- **Abstention:** If the answer is not found in the retrieved context, the prompt must instruct the model to explicitly abstain rather than hallucinate based on its training data.

## 4. Code Quality
- **No hardcoded constants:** Thresholds, file paths, and model names must reside in `app/config.py` and load from the `.env` file.
- **Type hinting:** Use strict Python type hints throughout the codebase.
- **Fail visibly:** If an upstream service (like the DB or the embedding API) fails, bubble the exception up and return a `SERVICE_UNAVAILABLE` or HTTP 500 error. Do not swallow exceptions and return empty arrays.
