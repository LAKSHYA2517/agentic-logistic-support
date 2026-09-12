# Sauda AI — Phase 2 Technical Blueprint

## 1. System Boundary

```text
WhatsApp / Phase 1
       │
       ▼
Shipment ID + local .ogg
       │
       ▼
┌──────────────────────────────┐
│ Phase 2 Intelligence Service │
└──────────────────────────────┘
       │
       ├── 1. Media Validator
       │
       ├── 2. Sarvam STT
       │       └── Saaras v4 + codemix
       │
       ├── 3. Transcript Normalizer
       │
       ├── 4. Qwen3 / Groq
       │       └── Structured JSON Schema
       │
       ├── 5. Pydantic + domain validation
       │
       ├── 6. Confidence / review gate
       │
       └── 7. SQLite transaction
               └── Shipment → IN_TRANSIT
```

## 2. Recommended Model Strategy

### Production extraction
**Qwen3 via Groq**

Use the Groq structured-output interface when the selected Qwen3 model supports strict JSON Schema. Groq currently documents strict structured outputs for supported Qwen 3.8 models; tool use and strict structured outputs are separate mechanisms, so prefer `response_format` JSON Schema for extraction rather than relying on tool calling alone.

Recommended evaluation/fallback matrix:

| Task | Model | Thinking |
|---|---|---|
| Normal extraction benchmark | Claude Sonnet 5 | low/medium effort |
| Ambiguous Hinglish / conflicting entities | Claude Sonnet 5 | medium/high effort |
| Difficult adjudication / evaluation set | Claude Opus 5 | high effort |
| Cheap secondary validator | Claude Haiku 4.5 | no configurable effort; keep prompt deterministic |

For a hackathon, **Sonnet 5 at low/medium effort** is the sensible Claude benchmark. Do not spend Opus on every WhatsApp voice note.

Claude Sonnet 5 uses adaptive thinking and effort rather than the old manual `budget_tokens` approach. Claude 3.5 Sonnet should not be used for a new build.

## 3. Sarvam Contract

Endpoint:

`POST https://api.sarvam.ai/speech-to-text`

Headers:

```text
api-subscription-key: $SARVAM_API_KEY
```

Multipart:

```text
file=<audio>
model=saaras:v4
mode=codemix
```

Optional:

```text
language_code=unknown
keyterms=[...]
```

Important: current Sarvam documentation says Saaras v4 is the latest model and supports codemix, but the REST endpoint is limited to short audio (documented as up to 30 seconds). Use Batch for longer files.

## 4. Internal Interfaces

```python
async def validate_media(file_path: str) -> MediaMetadata: ...

async def sarvam_stt(file_path: str, keyterms: list[str] | None = None) -> STTResult: ...

async def normalize_transcript(text: str) -> str: ...

async def extract_logistics_data(transcript: str) -> LogisticsExtraction: ...

def validate_logistics(data: LogisticsExtraction,
                       transcript: str) -> ValidationResult: ...

async def process_audio(shipment_id: int,
                        file_path: str) -> ProcessingResult: ...
```

## 5. Pydantic Models

```python
class LogisticsExtraction(BaseModel):
    party_name: str | None = None
    truck_number: str | None = None
    advance_paid: int | None = Field(default=None, ge=0)
    balance_due: int | None = Field(default=None, ge=0)
```

Do not make all fields mandatory unless the product guarantees that every voice note contains them.

## 6. Truck Normalization

Canonical form:

`RJ14GB1122`

Accepted input examples:

- `RJ14-GB-1122`
- `RJ 14 GB 1122`
- `RJ14 GB1122`

Do not use the LLM as the only normalizer. Apply deterministic normalization after extraction and retain the original model value.

## 7. Money Handling

Represent rupees as integer paise only if the broader Phase 1 schema already uses paise. Otherwise use integer rupees consistently.

Examples:
- `das hazaar` → `10000`
- `10k` → `10000`
- `₹10,000` → `10000`

If the transcript says only "advance de diya" with no amount, return `null`.

## 8. Database Transaction

Pseudo-flow:

```python
shipment = get_shipment(shipment_id)

result = await process_ai_pipeline(file_path)

validated = validate_logistics(result.extraction, result.transcript)

if validated.status == "ACCEPTED":
    update_shipment(...)
    shipment.status = "IN_TRANSIT"
    commit()
else:
    persist_review_state()
    rollback_or_commit_review_state()
```

Never update the shipment to `IN_TRANSIT` before validation.

## 9. Retry Policy

Retry:
- HTTP 429
- transient 5xx
- network timeout

Do not retry:
- invalid API key
- invalid file
- malformed schema
- deterministic validation failure

Use bounded exponential backoff and an idempotency key.

## 10. Suggested Project Layout

```text
app/
├── intelligence/
│   ├── __init__.py
│   ├── stt.py
│   ├── extraction.py
│   ├── normalization.py
│   ├── validation.py
│   ├── service.py
│   └── models.py
├── db/
│   ├── models.py
│   └── session.py
├── api/
│   └── routes.py
└── tests/
    ├── test_stt.py
    ├── test_extraction.py
    ├── test_validation.py
    └── test_pipeline.py
```
