# Sauda AI — Phase 2 Architecture

## Logical Architecture

```text
                         ┌─────────────────────┐
                         │   WhatsApp / Phase 1│
                         └──────────┬──────────┘
                                    │
                             shipment_id
                             + .ogg path
                                    │
                                    ▼
                    ┌──────────────────────────────┐
                    │    Intelligence Service     │
                    │                              │
                    │  process_audio()             │
                    └──────────────┬───────────────┘
                                   │
             ┌─────────────────────┼─────────────────────┐
             │                     │                     │
             ▼                     ▼                     ▼
     ┌──────────────┐      ┌──────────────┐      ┌──────────────┐
     │Media         │      │Transcript    │      │State /       │
     │Validator     │      │Store         │      │Observability │
     └──────┬───────┘      └──────────────┘      └──────────────┘
            │
            ▼
     ┌──────────────────┐
     │ Sarvam Saaras v4 │
     │ mode=codemix     │
     └────────┬─────────┘
              │
              ▼
     ┌──────────────────┐
     │ Raw Transcript   │
     └────────┬─────────┘
              │
              ▼
     ┌──────────────────┐
     │ Deterministic    │
     │ Normalizer       │
     └────────┬─────────┘
              │
              ▼
     ┌──────────────────┐
     │ Qwen3 via Groq   │
     │ JSON Schema      │
     └────────┬─────────┘
              │
              ▼
     ┌──────────────────┐
     │ Pydantic         │
     │ Validation       │
     └────────┬─────────┘
              │
        ┌─────┴─────┐
        │           │
        ▼           ▼
   ACCEPTED     REVIEW/FAIL
        │
        ▼
┌────────────────────────┐
│ SQLite Shipment        │
│ status = IN_TRANSIT    │
└────────────────────────┘
```

## Component Responsibilities

### Media Validator
Responsible only for media integrity and idempotency.

### Sarvam Adapter
Responsible only for converting audio to text.

Configuration:

```text
model=saaras:v4
mode=codemix
```

Do not mix business extraction logic into the STT adapter.

### Normalizer
Performs deterministic cleanup. It should not call an LLM.

### Extraction Adapter
Converts transcript into structured logistics data.

Production:

```text
Qwen3 → Groq → JSON Schema
```

Evaluation:

```text
Groq Qwen 3 32B Model
```


### Validation Layer
This is the primary anti-hallucination boundary.

The LLM is not trusted merely because it returned valid JSON.

Validation must ask:

```text
Was this value actually supported by the transcript?
Is the value syntactically valid?
Is the value within domain constraints?
Does it conflict with another extracted value?
```

### Database Layer
Only the validated result can mutate shipment state.

## Anti-Hallucination Architecture

```text
Transcript
    │
    ▼
LLM extraction
    │
    ▼
Schema constraint
    │
    ▼
Pydantic
    │
    ▼
Regex / deterministic rules
    │
    ▼
Evidence check against transcript
    │
    ▼
Confidence gate
    │
 ┌──┴───┐
 ▼      ▼
write   review
```

The most important principle:

> **Structured output prevents malformed output; it does not prove factual correctness.**

## Why Not Put Everything in the LLM?

Truck numbers and money are high-value logistics fields. They should have deterministic post-processing.

Example:

```text
Model:
"RJ14-GB-1122"

Normalizer:
"RJ14GB1122"

Validator:
matches Indian vehicle-number pattern → pass
```

The same approach applies to money.

## Optional Claude Evaluation Architecture

Claude should initially be used as a benchmark rather than a second production LLM on every request.

```text
Golden dataset
      │
 ┌────┴─────────┐
 ▼              ▼
Qwen3/Groq    Claude Sonnet 5
 ▼              ▼
Results        Results
 └──────┬───────┘
        ▼
 Field-level comparison
        ▼
 Select production configuration
```

Use Claude Opus 5 only for hard examples or adjudication. This controls cost and avoids unnecessary latency.

## State Machine

```text
RECEIVED
   │
   ▼
PROCESSING
   │
   ├── STT_FAILED
   │
   ├── EXTRACTION_FAILED
   │
   ├── NEEDS_REVIEW
   │
   └── VALIDATED
          │
          ▼
      IN_TRANSIT
```

## Deployment Boundary

The Phase 2 service should expose a small internal API:

```text
POST /v1/intelligence/process-audio
GET  /v1/intelligence/jobs/{job_id}
GET  /v1/shipments/{shipment_id}/extraction
```

For the initial synchronous hackathon implementation, `POST /process-audio` can block until completion. The service interface should still be async internally so the implementation can later move to a queue.

## Security

- API keys only in environment variables/secrets manager.
- Do not log raw authorization headers.
- Apply retention policy to raw audio.
- Treat transcripts as sensitive business data.
- Use least-privilege database access.
