import asyncio
import logging
from collections.abc import Callable

import httpx
from maxapi.types.attachments.audio import Audio

from tsu_max_bot.max_bot.local_voice import MAX_LOCAL_AUDIO_BYTES

_RECOGNITION_URL = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"
_MAX_CDN_DOMAINS = ("okcdn.ru", "oneme.ru")
_SPEECHKIT_AUDIO_BYTES = 1_000_000
_MAX_REDIRECTS = 3
_TOTAL_TIMEOUT = 15.0

logger = logging.getLogger(__name__)


def _is_max_cdn(url: httpx.URL) -> bool:
    host = url.host
    return (
        url.scheme == "https"
        and url.port in (None, 443)
        and not url.userinfo
        and any(host == domain or host.endswith(f".{domain}") for domain in _MAX_CDN_DOMAINS)
    )


def _is_mono_ogg_opus(data: bytes) -> bool:
    if len(data) < 28 or not data.startswith(b"OggS"):
        return False
    # The first Ogg packet starts after the page header and its segment table.
    start = 27 + data[26]
    return (
        len(data) >= start + 19 and data[start : start + 8] == b"OpusHead" and data[start + 9] == 1
    )


class MaxVoice:
    """Download a MAX voice attachment and recognize it using the configured providers."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        speechkit_api_key: str | None = None,
        recognize_local: Callable[[bytes], str | None] | None = None,
    ) -> None:
        self._http = http
        self._api_key = speechkit_api_key
        self._recognize_local = recognize_local
        self._local_slot = asyncio.Semaphore(1)

    async def transcribe(self, audio: Audio) -> str | None:
        url = getattr(audio.payload, "url", None)
        if not url:
            return None
        byte_limit = MAX_LOCAL_AUDIO_BYTES if self._recognize_local else _SPEECHKIT_AUDIO_BYTES
        data = None
        try:
            async with asyncio.timeout(_TOTAL_TIMEOUT):
                data = await self._download(httpx.URL(url), byte_limit)
                if (
                    data
                    and self._api_key
                    and len(data) <= _SPEECHKIT_AUDIO_BYTES
                    and _is_mono_ogg_opus(data)
                ):
                    text = await self._speechkit(data, self._api_key)
                    if text:
                        return text
        except TimeoutError:
            logger.warning("Истекло время загрузки или облачного распознавания записи MAX.")
        except (httpx.HTTPError, httpx.InvalidURL, ValueError) as error:
            logger.warning("Не удалось загрузить запись MAX (%s).", type(error).__name__)
            return None
        if data and self._recognize_local is not None:
            async with self._local_slot:
                return await asyncio.to_thread(self._recognize_local, data)
        return None

    async def _speechkit(self, data: bytes, api_key: str) -> str | None:
        request = httpx.Request(
            "POST",
            _RECOGNITION_URL,
            params={"lang": "ru-RU", "format": "oggopus"},
            content=data,
            headers={
                "Authorization": f"Api-Key {api_key}",
                "Content-Type": "audio/ogg",
                "X-Data-Logging-Enabled": "false",
            },
        )
        try:
            response = await self._http.send(request, auth=None, follow_redirects=False)
            response.raise_for_status()
            decoded = response.json()
        except (httpx.HTTPError, ValueError, RecursionError) as error:
            logger.warning(
                "Не удалось распознать запись через SpeechKit (%s).", type(error).__name__
            )
            return None
        result = decoded.get("result") if isinstance(decoded, dict) else None
        return (result.strip() or None) if isinstance(result, str) else None

    async def _download(self, url: httpx.URL, byte_limit: int) -> bytes | None:
        for _ in range(_MAX_REDIRECTS + 1):
            if not _is_max_cdn(url):
                logger.debug("Пропущена запись MAX с адресом вне разрешённых доменов.")
                return None
            # Build requests directly to keep the client's default credentials and cookies out.
            request = httpx.Request("GET", url, headers={"Accept-Encoding": "identity"})
            response = await self._http.send(
                request, stream=True, auth=None, follow_redirects=False
            )
            try:
                if response.has_redirect_location:
                    url = url.join(response.headers["location"])
                    continue
                response.raise_for_status()
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    return None
                if int(response.headers.get("content-length", "0")) > byte_limit:
                    return None
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(data) + len(chunk) > byte_limit:
                        return None
                    data.extend(chunk)
                return bytes(data)
            finally:
                await response.aclose()
        return None
