"""Client for retrieving WhatsApp media from the Meta Graph API."""

import os
import re
from pathlib import Path
from typing import Optional
from urllib.parse import quote
from uuid import uuid4

import httpx

class MetaMediaError(RuntimeError):
    """A safe-to-store description of a Meta media retrieval failure."""


# Content types a driver's POD (proof of delivery) photo/PDF can arrive
# as, mapped to the file extension Sarvam Vision expects
# (app.intelligence.ocr.SarvamVisionProvider.SUPPORTED_MEDIA_TYPES).
_POD_EXTENSIONS_BY_CONTENT_TYPE = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "application/pdf": ".pdf",
}


class MetaMediaService:
    """Resolve and download media with an injected HTTP client."""

    def __init__(
        self,
        *,
        access_token: Optional[str],
        graph_api_base_url: str,
        graph_api_version: str,
        output_dir: Path,
        max_media_bytes: int,
        http_client: httpx.Client,
        phone_number_id: Optional[str] = None,
    ) -> None:
        self._access_token = access_token
        self._base_url = graph_api_base_url.rstrip("/")
        self._version = graph_api_version.strip("/")
        self._output_dir = output_dir
        self._max_media_bytes = max_media_bytes
        self._client = http_client
        self._phone_number_id = phone_number_id

    def download_audio(self, media_id: str, shipment_id: int) -> Path:
        """Resolve a Meta media ID and save its bytes under a safe `.ogg` name."""

        if not self._access_token:
            raise MetaMediaError("META_ACCESS_TOKEN is not configured.")

        media_url = self._resolve_media_url(media_id)
        return self._download_media(media_url, shipment_id)

    def download_pod_document(self, media_id: str, shipment_id: int) -> Path:
        """Resolve a Meta media ID and save a driver's POD photo/PDF.

        A separate method from ``download_audio`` (rather than
        generalizing it) so the seller voice-note path -- already
        relied on and tested -- is never touched. Reuses
        ``_resolve_media_url``, the one piece that's genuinely
        identical between the two.
        """

        if not self._access_token:
            raise MetaMediaError("META_ACCESS_TOKEN is not configured.")

        media_url = self._resolve_media_url(media_id)
        return self._download_pod_media(media_url, shipment_id)

    def _resolve_media_url(self, media_id: str) -> str:
        lookup_url = f"{self._base_url}/{self._version}/{quote(media_id, safe='')}"
        params = (
            {"phone_number_id": self._phone_number_id}
            if self._phone_number_id
            else None
        )

        try:
            response = self._client.get(
                lookup_url,
                headers=self._authorization_header,
                params=params,
            )
        except httpx.RequestError as exc:
            raise MetaMediaError("Meta media lookup request failed.") from exc

        if not response.is_success:
            raise self._http_error("lookup", response)

        try:
            response_data = response.json()
        except ValueError as exc:
            raise MetaMediaError("Meta media lookup returned invalid JSON.") from exc

        media_url = response_data.get("url") if isinstance(response_data, dict) else None
        if not isinstance(media_url, str) or not media_url.strip():
            raise MetaMediaError("Meta media lookup response did not include a URL.")
        return media_url

    def _download_media(self, media_url: str, shipment_id: int) -> Path:
        final_path = self._output_dir / f"shipment-{shipment_id}-{uuid4().hex}.ogg"
        partial_path = final_path.with_suffix(".part")

        try:
            self._output_dir.mkdir(parents=True, exist_ok=True)
            bytes_written = 0
            ogg_header = bytearray()
            with self._client.stream(
                "GET",
                media_url,
                headers=self._authorization_header,
            ) as response:
                if not response.is_success:
                    raise self._http_error("download", response)
                content_type = response.headers.get("content-type", "").lower()
                if content_type.split(";", maxsplit=1)[0].strip() != "audio/ogg":
                    raise MetaMediaError("Meta media download was not audio/ogg.")

                with partial_path.open("xb") as media_file:
                    for chunk in response.iter_bytes():
                        if len(ogg_header) < 4:
                            bytes_needed = 4 - len(ogg_header)
                            ogg_header.extend(chunk[:bytes_needed])
                        media_file.write(chunk)
                        bytes_written += len(chunk)
                        if bytes_written > self._max_media_bytes:
                            raise MetaMediaError(
                                "Meta media download exceeded the configured size limit."
                            )

            if bytes_written == 0:
                raise MetaMediaError("Meta media download returned an empty file.")
            if bytes(ogg_header) != b"OggS":
                raise MetaMediaError("Meta media download was not a valid Ogg file.")

            partial_path.replace(final_path)
        except MetaMediaError:
            partial_path.unlink(missing_ok=True)
            raise
        except (httpx.RequestError, OSError) as exc:
            partial_path.unlink(missing_ok=True)
            raise MetaMediaError("Meta media download could not be saved.") from exc

        return final_path

    def _download_pod_media(self, media_url: str, shipment_id: int) -> Path:
        """Stream a POD document to disk, validated by content type rather than magic bytes.

        Same shape as ``_download_media`` (stream -> validate -> size-limit
        -> finalize/cleanup), but the extension is only known once the
        response headers arrive, so the temp file is named without one
        until the final rename.
        """

        temp_name = f"pod-{shipment_id}-{uuid4().hex}"
        partial_path = self._output_dir / f"{temp_name}.part"

        try:
            self._output_dir.mkdir(parents=True, exist_ok=True)
            bytes_written = 0
            with self._client.stream(
                "GET",
                media_url,
                headers=self._authorization_header,
            ) as response:
                if not response.is_success:
                    raise self._http_error("download", response)
                content_type = (
                    response.headers.get("content-type", "").split(";", maxsplit=1)[0].strip().lower()
                )
                extension = _POD_EXTENSIONS_BY_CONTENT_TYPE.get(content_type)
                if extension is None:
                    raise MetaMediaError(
                        "Meta POD download had an unsupported content type: "
                        f"{content_type or 'unknown'}."
                    )

                with partial_path.open("xb") as media_file:
                    for chunk in response.iter_bytes():
                        media_file.write(chunk)
                        bytes_written += len(chunk)
                        if bytes_written > self._max_media_bytes:
                            raise MetaMediaError(
                                "Meta media download exceeded the configured size limit."
                            )

            if bytes_written == 0:
                raise MetaMediaError("Meta media download returned an empty file.")

            final_path = self._output_dir / f"{temp_name}{extension}"
            partial_path.replace(final_path)
        except MetaMediaError:
            partial_path.unlink(missing_ok=True)
            raise
        except (httpx.RequestError, OSError) as exc:
            partial_path.unlink(missing_ok=True)
            raise MetaMediaError("Meta media download could not be saved.") from exc

        return final_path

    @property
    def _authorization_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token}"}

    def _http_error(self, stage: str, response: httpx.Response) -> MetaMediaError:
        base_message = f"Meta media {stage} failed with HTTP {response.status_code}"

        try:
            response_data = response.json()
        except ValueError:
            return MetaMediaError(f"{base_message}.")

        error = response_data.get("error") if isinstance(response_data, dict) else None
        if not isinstance(error, dict):
            return MetaMediaError(f"{base_message}.")

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
            return MetaMediaError(f"{base_message}.")

        safe_message = " ".join(raw_message.split())
        if self._access_token:
            safe_message = safe_message.replace(self._access_token, "<redacted>")
        safe_message = re.sub(r"https?://\S+", "<url>", safe_message)[:500]
        return MetaMediaError(f"{base_message}: {safe_message}")


def prepare_media_directory(output_dir: Path) -> None:
    """Create the configured media directory and ensure it is writable."""

    output_dir.mkdir(parents=True, exist_ok=True)
    if not output_dir.is_dir() or not os.access(output_dir, os.W_OK):
        raise RuntimeError(f"Media download directory is not writable: {output_dir}")
