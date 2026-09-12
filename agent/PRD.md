# Sauda AI — Phase 2: Intelligence Engine

## 1. Objective

Transform inbound logistics voice notes into trustworthy structured shipment data.

**Input:** `.ogg` voice note  
**Output:** validated logistics extraction + shipment state transition

Primary pipeline:

`OGG → Sarvam Saaras v4 → normalized transcript → Qwen3 via Groq → Pydantic validation → confidence/validation gate → SQLite`

Claude is **not** the production extraction model in this design. The existing Phase 2 notes conflict: the PRD says Claude 3.5 while the Blueprint says Qwen3 via Groq. This specification resolves that conflict by making **Qwen3/Groq the production extractor** and Claude an optional evaluation/fallback model.

## 2. Phase Breakdown

### Phase 2A — Media Intake & Validation
- Accept local `.ogg` path from Phase 1.
- Validate existence, MIME/extension, size, and duration where available.
- Reject empty/corrupt files.
- Create an idempotency key from `shipment_id + media hash`.

**Done when:** invalid media never reaches an external AI API.

### Phase 2B — Speech-to-Text
- Send audio to Sarvam `/speech-to-text`.
- Use `model="saaras:v4"`.
- Use `mode="codemix"` for Hinglish/code-mixed output.
- Prefer automatic language detection unless the upstream message already contains a reliable language hint.
- Preserve the raw transcript for auditability.
- Optionally supply logistics keyterms such as known party names, cities, vehicle prefixes, and depot names.

REST is appropriate for short voice notes; Sarvam documents a 30-second REST limit. Longer media should move to Batch rather than being silently truncated.

### Phase 2C — Transcript Normalization
Normalize only deterministic artifacts:
- whitespace
- obvious punctuation
- Unicode normalization
- vehicle-number separators
- currency formatting

Do **not** invent missing values.
Keep both `raw_transcript` and `normalized_transcript`.

### Phase 2D — Entity Extraction
- Send the transcript to Qwen3 through Groq.
- Use a strict JSON Schema / structured-output path where supported.
- Extract:
  - `party_name`
  - `truck_number`
  - `advance_paid`
  - `balance_due`
- Return `null` for a field that is not explicitly recoverable.
- Never infer financial amounts from unstated assumptions.

### Phase 2E — Deterministic Validation
Validate with Pydantic plus domain rules:
- truck number normalization
- integer/non-negative money
- `advance_paid <= balance_due + advance_paid` when both values represent parts of a total
- reject malformed vehicle numbers rather than silently correcting them
- preserve original extracted text for disputed fields

### Phase 2F — Confidence & Review Gate
Calculate field-level confidence from evidence rather than allowing the LLM to arbitrarily declare certainty.

Suggested states:
- `ACCEPTED`
- `NEEDS_REVIEW`
- `FAILED`

Examples:
- Explicit truck number + strong regex match → accepted.
- Ambiguous spoken number → review.
- Missing party name → accepted only if the product allows partial extraction; otherwise review.
- Contradictory amounts → review.

### Phase 2G — State Update
Only after validation:
- update the Phase 1 `Shipment` row
- persist extraction JSON and transcript/audit metadata
- set status to `IN_TRANSIT` only when the minimum required shipment fields pass the gate
- commit atomically

If extraction fails, do not mark the shipment `IN_TRANSIT`.

### Phase 2H — Observability & Evaluation
Log:
- request IDs
- model names/versions
- latency
- API errors
- transcript
- structured output
- validation failures
- final decision

Build a small golden dataset of real Hinglish examples and measure:
- transcription accuracy
- truck-number exact match
- money exact match
- party-name accuracy
- complete-record accuracy
- false acceptance rate

## 3. Functional Requirements

### FR-1
`process_audio(shipment_id, file_path)` must orchestrate the entire pipeline.

### FR-2
The pipeline must be idempotent.

### FR-3
No field may be fabricated when absent from the transcript.

### FR-4
Every externally generated value must be traceable to the transcript.

### FR-5
Pydantic validation must occur before the database state transition.

### FR-6
Failures must be represented explicitly rather than converted into fake defaults.

## 4. Non-Functional Requirements

- Async service interface.
- External I/O must have timeouts.
- Retry only transient failures, with bounded exponential backoff.
- Never retry malformed requests indefinitely.
- Secrets must come from environment variables.
- No API key may be written to logs.
- SQLite update must be transactional.
- Raw media should have a defined retention policy.

## 5. Canonical Schema

```python
from pydantic import BaseModel, Field
from typing import Optional

class LogisticsExtraction(BaseModel):
    party_name: Optional[str] = None
    truck_number: Optional[str] = None
    advance_paid: Optional[int] = Field(default=None, ge=0)
    balance_due: Optional[int] = Field(default=None, ge=0)
```

Use optional fields because absence is different from zero.

## 6. Acceptance Criteria

A valid test case such as:

> "Ramesh ko 150 peti bhejna hai, truck RJ14-GB-1122, advance das hazaar diya hai, balance bees hazaar."

should produce a structured record equivalent to:

```json
{
  "party_name": "Ramesh",
  "truck_number": "RJ14GB1122",
  "advance_paid": 10000,
  "balance_due": 20000
}
```

The exact transcript wording may differ, but the extracted values must be grounded in the transcript.

## 7. Error States

`MEDIA_INVALID → STT_FAILED → EXTRACTION_FAILED → VALIDATION_FAILED → NEEDS_REVIEW → ACCEPTED`

Only `ACCEPTED` can trigger the `IN_TRANSIT` transition.
