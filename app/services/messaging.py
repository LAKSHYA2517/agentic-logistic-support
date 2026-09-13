"""Client for sending outbound WhatsApp text messages via the Meta Graph API.

``app.services.meta.MetaMediaService`` only handles *inbound* media
(resolving and downloading a voice note) -- there was no outbound
sending capability before this module. It reuses the same
configuration (``META_ACCESS_TOKEN``, ``META_GRAPH_API_BASE_URL``,
``META_API_VERSION``, ``META_PHONE_NUMBER_ID``) and the same
credential-safe error handling style as ``MetaMediaService``, rather
than introducing a second configuration surface.

Every send attempt is logged here -- success or failure -- with the
HTTP status code, a redacted response body, the WhatsApp message ID
Meta assigned (on success), and the Meta error code/message (on
failure). This is the one place that talks to the Meta API, so it is
the one place responsible for making what Meta actually returned
visible in development, without ever logging the access token.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Optional

import httpx

if TYPE_CHECKING:
    from app.config import AppSettings

logger = logging.getLogger(__name__)

_MAX_LOGGED_BODY_CHARS = 1000


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
        driver_template_name: Optional[str] = None,
        driver_template_language: str = "en_US",
    ) -> None:
        self._access_token = access_token
        self._base_url = graph_api_base_url.rstrip("/")
        self._version = graph_api_version.strip("/")
        self._phone_number_id = phone_number_id
        self._client = http_client
        self._driver_template_name = driver_template_name
        self._driver_template_language = driver_template_language

    def send_text_message(self, *, to: str, body: str) -> Optional[str]:
        """Send a plain-text WhatsApp message to ``to`` (a WhatsApp number).

        Returns the WhatsApp message ID Meta assigned to the outbound
        message (``messages[0].id`` in Meta's response) when the
        response included one, otherwise ``None``. Raises
        ``MetaMessagingError`` for anything that is not a 2xx response
        -- a caller must never treat this call as having sent the
        message unless it returns normally.
        """

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": body},
        }
        return self._send(to=to, payload=payload)

    def send_driver_assignment(
        self,
        *,
        to: str,
        text_body: str,
        template_parameters: tuple[str, ...],
    ) -> Optional[str]:
        """Send an assignment using a configured template, or an in-window text.

        An approved utility template is required when the driver has not messaged
        the business within the preceding 24 hours. Leaving
        ``META_DRIVER_TEMPLATE_NAME`` unset preserves the free-form service-message
        behavior for an already-open customer-service window.
        """

        if not self._driver_template_name:
            return self.send_text_message(to=to, body=text_body)

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": self._driver_template_name,
                "language": {"code": self._driver_template_language},
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": value}
                            for value in template_parameters
                        ],
                    }
                ],
            },
        }
        return self._send(to=to, payload=payload)

    def _send(self, *, to: str, payload: dict[str, object]) -> Optional[str]:
        """Submit one already-built Messages API payload."""

        if not self._access_token:
            raise MetaMessagingError("META_ACCESS_TOKEN is not configured.")
        if not self._phone_number_id:
            raise MetaMessagingError("META_PHONE_NUMBER_ID is not configured.")

        self._warn_if_recipient_format_looks_wrong(to)
        url = f"{self._base_url}/{self._version}/{self._phone_number_id}/messages"

        try:
            response = self._client.post(
                url,
                headers={"Authorization": f"Bearer {self._access_token}"},
                json=payload,
            )
        except httpx.RequestError as exc:
            logger.error(
                "meta_outbound_message_request_failed to=%s sender_phone_number_id=%s "
                "error_type=%s",
                to,
                self._phone_number_id,
                type(exc).__name__,
            )
            raise MetaMessagingError("Meta outbound message request failed.") from exc

        safe_body = self._redact(response.text)

        if not response.is_success:
            logger.error(
                "meta_outbound_message_rejected status=%s to=%s sender_phone_number_id=%s "
                "body=%s",
                response.status_code,
                to,
                self._phone_number_id,
                safe_body,
            )
            raise self._http_error(response, safe_body)

        message_id = self._extract_message_id(response)
        logger.info(
            "meta_outbound_message_accepted status=%s to=%s sender_phone_number_id=%s "
            "whatsapp_message_id=%s body=%s",
            response.status_code,
            to,
            self._phone_number_id,
            message_id,
            safe_body,
        )
        return message_id

    def _warn_if_recipient_format_looks_wrong(self, to: str) -> None:
        """Flag (never block) a ``to`` value that doesn't look like a full WhatsApp number.

        The WhatsApp Cloud API's ``to`` field must be the recipient's
        complete number in international format -- digits only, no
        leading ``+``, no leading zeros, *including* the country code
        (e.g. ``919317708038`` for an Indian number, not
        ``9317708038``). A bare 10-digit number is the single most
        common way this silently fails to deliver: Meta can still
        accept the API call (2xx) while the message never reaches a
        device, because the number as sent doesn't identify a real
        WhatsApp account. This only warns -- the configured value is
        still sent as-is -- so the logs explain a delivery failure
        without this module guessing at (and possibly getting wrong)
        what country code to add.
        """

        digits = to.strip()
        if not digits.isdigit():
            logger.warning(
                "meta_outbound_recipient_format_suspect to=%r "
                "reason=contains_non_digit_characters",
                to,
            )
            return
        if len(digits) <= 10:
            logger.warning(
                "meta_outbound_recipient_format_suspect to=%s digit_count=%d "
                "reason=looks_like_missing_country_code -- WhatsApp requires the full "
                "number including country code (e.g. 91XXXXXXXXXX for India), not a "
                "bare local number",
                digits,
                len(digits),
            )

    @staticmethod
    def _extract_message_id(response: httpx.Response) -> Optional[str]:
        try:
            data = response.json()
        except ValueError:
            return None
        messages = data.get("messages") if isinstance(data, dict) else None
        if isinstance(messages, list) and messages and isinstance(messages[0], dict):
            message_id = messages[0].get("id")
            if isinstance(message_id, str):
                return message_id
        return None

    def _redact(self, text: str) -> str:
        safe = " ".join(text.split())
        if self._access_token:
            safe = safe.replace(self._access_token, "<redacted>")
        safe = re.sub(r"https?://\S+", "<url>", safe)
        return safe[:_MAX_LOGGED_BODY_CHARS]

    def _http_error(self, response: httpx.Response, safe_body: str) -> MetaMessagingError:
        base_message = f"Meta outbound message failed with HTTP {response.status_code}"

        try:
            response_data = response.json()
        except ValueError:
            return MetaMessagingError(f"{base_message}: {safe_body}")

        error = response_data.get("error") if isinstance(response_data, dict) else None
        if not isinstance(error, dict):
            return MetaMessagingError(f"{base_message}: {safe_body}")

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

        return MetaMessagingError(f"{base_message}: {self._redact(raw_message)}")


def send_whatsapp_text(settings: AppSettings, *, to: str, body: str) -> Optional[str]:
    """Send one workflow text with the application's existing Meta configuration."""

    with httpx.Client(timeout=settings.meta_request_timeout_seconds) as http_client:
        service = MetaMessagingService(
            access_token=settings.meta_access_token,
            graph_api_base_url=settings.meta_graph_api_base_url,
            graph_api_version=settings.meta_api_version,
            phone_number_id=settings.meta_phone_number_id,
            http_client=http_client,
        )
        return service.send_text_message(to=to, body=body)
