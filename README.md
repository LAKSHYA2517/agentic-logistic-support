# Agentic Logistic Support

Hackathon-ready FastAPI backend for receiving Meta WhatsApp audio webhooks, preserving the original event in SQLite, and downloading voice media to local temporary storage.

## Phase 1 flow

```text
Meta POST /meta-webhook
  -> defensively parse audio messages
  -> create or reuse User
  -> create RECEIVED Shipment
  -> resolve the media ID through Meta Graph API
  -> download authenticated audio/ogg bytes
  -> save /tmp/shipment-<id>-<random>.ogg
  -> update Shipment.media_path
```

Failed media retrieval leaves the raw event intact, sets the shipment to `FAILED`, and stores a sanitized error. A repeated Meta message ID is acknowledged without creating or downloading another shipment.

## Local setup

Python 3.10 or newer is recommended.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

On Windows PowerShell, activate the environment with:

```powershell
.venv\Scripts\Activate.ps1
```

## Environment variables

Edit `.env` before connecting Meta. `.env` is ignored by Git and must not be committed.

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `META_ACCESS_TOKEN` | Yes for downloads | Empty | Meta Graph API bearer token |
| `META_WEBHOOK_VERIFY_TOKEN` | Yes for Meta setup | Empty | Private value chosen by you and entered in Meta |
| `META_WABA_ID` | Recommended for account setup | Empty | WhatsApp Business Account context; never used as a media ID |
| `META_PHONE_NUMBER_ID` | Recommended | Empty | Restricts media lookup to the configured WhatsApp number |
| `META_API_VERSION` | No | `v25.0` | Graph API version; confirm it is supported by your Meta app |
| `DATABASE_URL` | No | `sqlite:///./app.db` | SQLAlchemy database URL |
| `MEDIA_DOWNLOAD_DIR` | No | `/tmp` | Writable media destination |
| `MEDIA_MAX_BYTES` | No | `16777216` | Maximum accepted download size |
| `META_REQUEST_TIMEOUT_SECONDS` | No | `20` | Meta lookup/download timeout |
| `LOG_LEVEL` | No | `INFO` | Application log level |
| `APP_HOST` / `APP_PORT` | No | `127.0.0.1` / `8000` | Direct Python entry-point bind settings |
| `APP_DEBUG` / `APP_RELOAD` | No | `false` / `false` | Development switches |

Use a random verification token, for example:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Do not paste access tokens into source code, shell history, logs, screenshots, or bug reports.

## Database

The application creates `users` and `shipments` automatically when it starts. The default SQLite file is `app.db`. A small compatibility upgrade adds Phase 1 columns to SQLite databases created by earlier iterations.

For a completely fresh local database, stop the server and move the old `app.db` somewhere safe before restarting. Production schema evolution should use a migration tool rather than automatic table creation.

## Run the API

```bash
uvicorn app.main:app --reload
```

Check the server:

```bash
curl --fail http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok"}
```

## Meta webhook verification

Meta verifies the callback with a `GET` request. The application returns `hub.challenge` as plain text only when `hub.mode=subscribe` and `hub.verify_token` matches `META_WEBHOOK_VERIFY_TOKEN`.

Local verification example:

```bash
curl --get http://127.0.0.1:8000/meta-webhook \
  --data-urlencode 'hub.mode=subscribe' \
  --data-urlencode 'hub.verify_token=YOUR_VERIFY_TOKEN' \
  --data-urlencode 'hub.challenge=demo-challenge'
```

## Expose the API with ngrok

Install the [ngrok agent](https://ngrok.com/docs/getting-started/), sign in, and configure its authtoken. With FastAPI running on port 8000, open a second terminal:

```bash
ngrok config add-authtoken YOUR_NGROK_AUTHTOKEN
ngrok http 8000
```

Copy the HTTPS forwarding address shown by ngrok, such as `https://example-subdomain.ngrok.app`.

In **Meta App Dashboard → WhatsApp → Configuration → Webhooks**:

1. Set the callback URL to `https://YOUR-NGROK-DOMAIN/meta-webhook`.
2. Enter exactly the same value configured as `META_WEBHOOK_VERIFY_TOKEN`.
3. Click **Verify and save**.
4. Subscribe the webhook to the `messages` field.

Free ngrok URLs can change when the agent restarts. If yours changes, update the callback URL in Meta.

## Example webhook

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
          "audio": {
            "id": "META_MEDIA_ID",
            "mime_type": "audio/ogg; codecs=opus",
            "voice": true
          }
        }]
      }
    }]
  }]
}
```

A successful ingestion/download returns:

```json
{
  "status": "accepted",
  "shipments_created": 1,
  "duplicates": 0,
  "media_downloaded": 1,
  "failed": 0
}
```

Malformed, status-only, and non-audio payloads return `status: ignored`. Media failures still return HTTP 200 with `failed: 1` after recording the shipment as `FAILED`; this prevents repeated webhook delivery from creating a retry storm.

## Tests

```bash
pytest
```

The suite uses isolated SQLite files and mocked Meta HTTP calls. It does not require real credentials or internet access.

## Logs and media cleanup

Application logs contain event names, message/media IDs, internal user/shipment IDs, and sanitized failure reasons. They intentionally omit tokens, authentication headers, signed download URLs, and full payloads.

Downloads use generated filenames, stream through `.part` files, validate both the `audio/ogg` content type and Ogg container header, enforce the configured size limit, and remove partial/orphan files after failure. Completed files are not automatically deleted because later phases still need them. For a demo, clear only known `shipment-*.ogg` files after they are no longer needed.

## Current limitations

- Media download is synchronous and adds latency to the webhook response.
- Failed downloads require a future manual retry mechanism.
- Completed files in `/tmp` are ephemeral and have no retention job.
- POST webhook signature verification using the Meta app secret is not implemented yet.
- Audio is accepted only when Meta returns `audio/ogg`; no transcoding is performed.
- AI, transcription, background workers, and production migrations are outside Phase 1.
