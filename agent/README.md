# Phase 2 Intelligence Pack

This package splits the original Phase 2 into implementation-ready sub-phases and resolves an inconsistency in the original specification.

## Decision

Production path:

`Sarvam Saaras v4 → Qwen3 via Groq → Pydantic/domain validation → SQLite`

Claude is specified as an **evaluation/fallback path**, not the primary extractor.

The original references Claude 3.5 Sonnet, but that model generation is retired as of the current September 2026 documentation. Use current Claude models only for benchmarking or fallback.

## Files

- `PRD.md` — product requirements and acceptance criteria
- `Blueprint.md` — implementation/technical blueprint
- `workflow.md` — operational workflow and error handling
- `architecture.md` — system architecture and anti-hallucination boundaries

## Recommended implementation order

1. Media validator
2. Sarvam STT adapter
3. Transcript persistence
4. Qwen3 structured extractor
5. Pydantic/domain validation
6. Confidence/review gate
7. SQLite transaction
8. Tests + golden dataset
9. Claude benchmark
10. Observability
