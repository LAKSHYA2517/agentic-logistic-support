# Sauda AI — Phase 2 Workflow

## End-to-End Workflow

```text
1. Phase 1 receives WhatsApp voice note
        ↓
2. Media stored as /tmp/<id>.ogg
        ↓
3. Phase 2 receives shipment_id + file_path
        ↓
4. Validate file
        ↓
5. Compute media hash / idempotency key
        ↓
6. Call Sarvam Saaras v4
        │
        └── mode=codemix
        ↓
7. Save raw transcript
        ↓
8. Normalize deterministic formatting
        ↓
9. Send transcript to Qwen3 via Groq
        ↓
10. Receive structured JSON
        ↓
11. Pydantic validation
        ↓
12. Domain validation
        │
        ├── PASS → ACCEPTED
        │            ↓
        │        update Shipment
        │        ↓
        │        IN_TRANSIT
        │
        └── FAIL → NEEDS_REVIEW / FAILED
```

## Detailed Decision Flow

### Step 1 — Media

Check:
- file exists
- extension/MIME is supported
- file is non-empty
- file is not already processed

If invalid:

```json
{
  "status": "MEDIA_INVALID",
  "shipment_id": 123
}
```

### Step 2 — STT

Send:

```text
model = saaras:v4
mode = codemix
```

Example result:

```text
Ramesh ko 150 peti bhejni hai, truck RJ14-GB-1122,
advance das hazaar diya hai aur balance bees hazaar hai.
```

Store:
- raw transcript
- detected language
- Sarvam request ID
- model
- latency

### Step 3 — Normalization

Do deterministic cleanup only:

```text
RJ14-GB-1122
        ↓
RJ14GB1122
```

Do not rewrite semantic content.

### Step 4 — Extraction

Prompt Qwen3 to extract only facts explicitly present in the transcript.

Rules:
1. Never guess.
2. Missing = null.
3. Normalize truck numbers.
4. Convert spoken monetary values to integers.
5. Return only the schema.

### Step 5 — Validation

Run:
- Pydantic validation
- truck regex
- money constraints
- contradiction checks
- transcript evidence checks

### Step 6 — Confidence Gate

Suggested logic:

```text
all required fields valid + evidence found
        → ACCEPTED

some fields ambiguous
        → NEEDS_REVIEW

model response invalid after bounded retry
        → EXTRACTION_FAILED

transcript unusable
        → STT_FAILED
```

### Step 7 — Database

For `ACCEPTED`:

```sql
BEGIN;

UPDATE shipment
SET
    party_name = ?,
    truck_number = ?,
    advance_paid = ?,
    balance_due = ?,
    status = 'IN_TRANSIT'
WHERE id = ?;

COMMIT;
```

For review:

```text
Keep status unchanged.
Persist review payload.
Do not mark IN_TRANSIT.
```

## Error Handling

```text
Sarvam 429/5xx → retry with backoff
Sarvam 401/403 → fail fast
Groq transient error → bounded retry
Groq invalid schema → one repair/retry
Pydantic failure → validation failure
Contradiction → human/review queue
DB failure → transaction rollback
```

## Idempotency

Use:

```text
idempotency_key =
sha256(shipment_id + media_sha256)
```

Before processing:
- if already `ACCEPTED`, return previous result
- if processing is in progress, avoid duplicate execution
- if previous attempt failed transiently, allow retry

## Observability

Every run should have:

```json
{
  "trace_id": "...",
  "shipment_id": 123,
  "stt_model": "saaras:v4",
  "extractor_model": "qwen...",
  "stt_latency_ms": 1200,
  "llm_latency_ms": 900,
  "status": "ACCEPTED"
}
```

Never log API keys.

## Test Workflow

Test at minimum:

1. Pure Hindi voice note.
2. Hinglish voice note.
3. English logistics voice note.
4. Spoken truck number.
5. Hyphenated truck number.
6. Spoken money amounts.
7. Missing amount.
8. Missing truck number.
9. Contradictory amounts.
10. Noisy audio.
11. Empty/corrupt audio.
12. Duplicate media.
13. Sarvam timeout.
14. Groq timeout.
15. Database failure.
