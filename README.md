# Agentic Logistic Support

One FastAPI application that combines WhatsApp voice-note ingestion with the Phase 2 logistics intelligence pipeline.

```text
Meta POST /meta-webhook
  -> persist User + RECEIVED Shipment and raw payload
  -> acknowledge Meta
  -> FastAPI background task
       -> resolve/download audio/ogg with the Meta media ID
       -> save Shipment.media_path
       -> process_audio(shipment_id)
            -> validate media
            -> Sarvam Saaras v3 STT
            -> normalize transcript
            -> Groq/Qwen3 extraction
            -> deterministic validation and decision
            -> update the same Shipment row
```

Document perception is also available as an independent intelligence capability using Sarvam Vision's asynchronous Document AI flow. It is not part of the voice-note webhook path.

## Setup

Python 3.11 or newer is required.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.

## Configuration

`.env` is loaded with `python-dotenv`, is ignored by Git, and must never be committed. Environment variables supplied by the deployment take precedence.

| Variable | Required | Default / purpose |
| --- | --- | --- |
| `DATABASE_URL` | No | `sqlite:///./app.db` |
| `META_WEBHOOK_VERIFY_TOKEN` | For Meta setup | Secret value chosen for webhook verification |
| `META_ACCESS_TOKEN` | For media | Meta Graph API bearer token |
| `META_WABA_ID` | Account setup | WABA context; never substituted for a webhook media ID |
| `META_PHONE_NUMBER_ID` | Recommended | Sent as media lookup context |
| `META_DRIVER_TEMPLATE_NAME` | For proactive driver messages | Approved utility-template name; omit only when the driver has an open 24-hour service window |
| `META_DRIVER_TEMPLATE_LANGUAGE` | No | `en_US`; must match the approved template language |
| `META_API_VERSION` | No | `v25.0` |
| `META_GRAPH_API_BASE_URL` | No | `https://graph.facebook.com` |
| `META_REQUEST_TIMEOUT_SECONDS` | No | `20` |
| `MEDIA_DOWNLOAD_DIR` | No | `/tmp` |
| `MEDIA_MAX_BYTES` | No | `16777216` |
| `INTELLIGENCE_ENABLED` | No | `true`; set `false` to demo ingestion only |
| `SARVAM_API_KEY` | For Sarvam features | Shared Sarvam STT and Vision credential |
| `SARVAM_STT_URL` | No | Sarvam speech-to-text endpoint |
| `GROQ_API_KEY` | For voice intelligence | Groq credential |
| `GROQ_CHAT_COMPLETIONS_URL` | No | Groq OpenAI-compatible endpoint |
| `SARVAM_VISION_LANGUAGE` | No | `hi-IN`; document language hint |
| `SARVAM_VISION_OUTPUT_FORMAT` | No | `md`; `md` or `html` |
| `SARVAM_VISION_CONTENT_TYPE` | No | `mixed`; `printed`, `handwritten`, or `mixed` |
| `SARVAM_VISION_POLL_INTERVAL_SECONDS` | No | `5` |
| `SARVAM_VISION_MAX_WAIT_SECONDS` | No | `120` |
| `APP_HOST`, `APP_PORT` | No | `127.0.0.1`, `8000` |
| `APP_DEBUG`, `APP_RELOAD` | No | `false`, `false` |
| `LOG_LEVEL` | No | `INFO` |

The application never logs configured access tokens, API keys, authorization headers, signed download URLs, or full webhook payloads.

For proactive driver assignments, create and approve a utility template in
WhatsApp Manager with five body variables in this order: party, truck,
destination, advance, and balance. A suitable body is:

```text
New shipment assigned. Party: {{1}}, Truck: {{2}}, Destination: {{3}},
Advance: {{4}}, Balance: {{5}}. Please confirm YES or NO.
```

Set its exact name and language in `META_DRIVER_TEMPLATE_NAME` and
`META_DRIVER_TEMPLATE_LANGUAGE`. If no template is configured, the application
sends free-form text, which Meta only delivers while that driver has an open
24-hour customer-service window.

## Database and statuses

Startup creates missing tables and performs an additive SQLite compatibility upgrade. Existing `app.db` rows are retained; the migration only adds known missing columns and the message-ID unique index. For production-grade schema history, replace this MVP migration with Alembic.

There is one canonical `Shipment` model. Phase 2 stores:

- `transcript`
- `extracted_data` JSON (`party_name`, `truck_number`, `advance_paid`, `balance_due`)
- `processing_error`
- `processing_started_at` and `processing_completed_at`

Status mapping:

```text
RECEIVED -> TRANSCRIBING -> COMPLETED       accepted extraction
                         -> PARSED          human review needed
                         -> FAILED          media/provider/pipeline failure
```

Existing `CONFIRMED` and `PROCESSING` values remain available for later business workflow phases. `IN_TRANSIT` is intentionally not introduced during this integration.

## Run and test

```bash
uvicorn app.main:app --reload
curl --fail http://127.0.0.1:8000/health
pytest -q
```

Expected health response:

```json
{"status":"ok"}
```

## Meta webhook setup

Verification request:

```bash
curl --get http://127.0.0.1:8000/meta-webhook \
  --data-urlencode 'hub.mode=subscribe' \
  --data-urlencode 'hub.verify_token=YOUR_VERIFY_TOKEN' \
  --data-urlencode 'hub.challenge=demo-challenge'
```

Example audio payload:

```json
{
  "object": "whatsapp_business_account",
  "entry": [{
    "changes": [{
      "field": "messages",
      "value": {
        "contacts": [{"wa_id": "15551234567"}],
        "messages": [{
          "from": "15551234567",
          "id": "wamid.example",
          "type": "audio",
          "audio": {"id": "META_MEDIA_ID", "mime_type": "audio/ogg", "voice": true}
        }]
      }
    }]
  }]
}
```

Immediate acknowledgement:

```json
{
  "status": "accepted",
  "shipments_created": 1,
  "duplicates": 0,
  "processing_queued": 1,
  "media_downloaded": 0,
  "failed": 0
}
```

`media_downloaded` is retained for response compatibility but is `0` because download now happens after acknowledgement. Inspect the Shipment row or logs for the background outcome. Missing media IDs are failed during ingestion; provider failures are recorded later in `media_error` or `processing_error`. A repeated stable Meta message ID returns `duplicates: 1` and schedules no work.

## ngrok demo

With Uvicorn running on port 8000:

```bash
ngrok config add-authtoken YOUR_NGROK_AUTHTOKEN
ngrok http 8000
```

In **Meta App Dashboard → WhatsApp → Configuration → Webhooks** set:

- Callback URL: `https://YOUR-NGROK-DOMAIN/meta-webhook`
- Verify token: exactly the value in `META_WEBHOOK_VERIFY_TOKEN`
- Subscription field: `messages`

Free ngrok URLs usually change after restart, so update Meta when the forwarding URL changes.

## Operational notes and limitations

- FastAPI `BackgroundTasks` is intentionally used for the hackathon MVP. Work is in-process and is not durable across a server crash or restart.
- SQLite is suitable for the demo, not high write concurrency.
- Downloaded files in `/tmp` are ephemeral and have no automatic retention job. Generated filenames prevent path traversal; failed partial files are removed.
- Only `audio/ogg` with an Ogg container header is accepted. There is no transcoding.
- Meta POST signature verification is not yet implemented.
- Failed jobs do not have an automatic retry endpoint.
- Document perception accepts PDF, PNG, JPEG, and ZIP inputs. It polls Sarvam's asynchronous Document AI job in-process for at most `SARVAM_VISION_MAX_WAIT_SECONDS`; callers should move this to durable background work if document volume grows.
- Live Sarvam Vision use requires a valid `SARVAM_API_KEY` with access to the Document AI service.
- Unit and integration tests mock all external APIs and do not require live credentials.
