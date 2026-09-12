"""Client for sending outbound WhatsApp text messages via the Meta Graph API.

``app.services.meta.MetaMediaService`` only handles *inbound* media
(resolving and downloading a voice note) -- there was no outbound
sending capability before this module. It reuses the same
configuration (``META_ACCESS_TOKEN``, ``META_GRAPH_API_BASE_URL``,
``META_API_VERSION``, ``META_PHONE_NUMBER_ID``) and the same
credential-safe error handling style as ``MetaMediaService``, rather
than introducing a second configuration surface.
"""

from __future__ import annotations

import re
from typing import Optional

import httpx


class MetaMessagingError(RuntimeError):
    """A safe-to-store description of a Meta outbound-messaging failure."""


class MetaMessagingService:
    """Send a WhatsApp text message with an injected HTTP client."""

    def __init__(
        self,
        *,
        access_token: Optional[str],
        graph_api_base_url: str,
        graph_api_version: str,
        phone_number_id: Optional[str],
        http_client: httpx.Client,
    ) -> None:
        self._access_token = access_token
        self._base_url = graph_api_base_url.rstrip("/")
        self._version = graph_api_version.strip("/")
        self._phone_number_id = phone_number_id
        self._client = http_client

    def send_text_message(self, *, to: str, body: str) -> None:
        """Send a plain-text WhatsApp message to ``to`` (a WhatsApp number)."""

        if not self._access_token:
            raise MetaMessagingError("META_ACCESS_TOKEN is not configured.")
        if not self._phone_number_id:
            raise MetaMessagingError("META_PHONE_NUMBER_ID is not configured.")

        url = f"{self._base_url}/{self._version}/{self._phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": body},
        }

        try:
            response = self._client.post(
                url,
                headers={"Authorization": f"Bearer {self._access_token}"},
                json=payload,
            )
        except httpx.RequestError as exc:
            raise MetaMessagingError("Meta outbound message request failed.") from exc

        if not response.is_success:
            raise self._http_error(response)

    def _http_error(self, response: httpx.Response) -> MetaMessagingError:
        base_message = f"Meta outbound message failed with HTTP {response.status_code}"

        try:
            response_data = response.json()
        except ValueError:
            return MetaMessagingError(f"{base_message}.")

        error = response_data.get("error") if isinstance(response_data, dict) else None
        if not isinstance(error, dict):
            return MetaMessagingError(f"{base_message}.")

        identifiers = []
        code = error.get("code")
        subcode = error.get("error_subcode")
        if isinstance(code, int):
            identifiers.append(f"code={code}")
        if isinstance(subcode, int):
            identifiers.append(f"subcode={subcode}")
        if identifiers:
            base_message += f" ({', '.join(identifiers)})"

        raw_message = error.get("message")
        if not isinstance(raw_message, str) or not raw_message.strip():
            return MetaMessagingError(f"{base_message}.")

        safe_message = " ".join(raw_message.split())
        if self._access_token:
            safe_message = safe_message.replace(self._access_token, "<redacted>")
        safe_message = re.sub(r"https?://\S+", "<url>", safe_message)[:500]
        return MetaMessagingError(f"{base_message}: {safe_message}")
