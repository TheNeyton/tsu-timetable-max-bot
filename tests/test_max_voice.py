import asyncio

import httpx
import pytest
from maxapi.types.attachments.audio import Audio

from tsu_max_bot.max_bot.voice import SpeechKit

_AUDIO_URL = "https://audio.okcdn.ru/voice?id=secret"
_OGG_OPUS = b"OggS" + b"\x00" * 22 + b"\x01\x13OpusHead\x01\x01" + b"\x00" * 9


def _audio(url=_AUDIO_URL):
    return Audio.model_validate({"type": "audio", "payload": {"url": url, "token": "max-token"}})


def test_speechkit_reads_max_audio_without_credentials_and_transcribes_it():
    def transport(request):
        if request.method == "GET":
            assert str(request.url) == _AUDIO_URL
            assert "Authorization" not in request.headers
            assert "Cookie" not in request.headers
            return httpx.Response(200, content=_OGG_OPUS)

        assert request.method == "POST"
        assert request.url.host == "stt.api.cloud.yandex.net"
        assert request.url.path == "/speech/v1/stt:recognize"
        assert dict(request.url.params) == {"lang": "ru-RU", "format": "oggopus"}
        assert request.headers["Authorization"] == "Api-Key speechkit-secret"
        assert request.headers["X-Data-Logging-Enabled"] == "false"
        assert "Cookie" not in request.headers
        assert request.content == _OGG_OPUS
        return httpx.Response(200, json={"result": "  какие пары завтра  "})

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(transport),
            headers={"Authorization": "wrong-token"},
            cookies={"private": "cookie"},
        ) as http:
            assert await SpeechKit(http, api_key="speechkit-secret").transcribe(_audio()) == (
                "какие пары завтра"
            )

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "url",
    [
        "http://audio.okcdn.ru/voice",
        "https://audio.okcdn.ru.evil.example/voice",
        "https://notokcdn.ru/voice",
        "https://audio.okcdn.ru@evil.example/voice",
        "https://account:password@audio.okcdn.ru/voice",
        "https://audio.okcdn.ru:8443/voice",
        "https://127.0.0.1/voice",
        "/voice",
    ],
)
def test_speechkit_does_not_fetch_unapproved_audio_urls(url):
    def transport(request):
        pytest.fail("Unapproved URL was requested")

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            assert await SpeechKit(http, api_key="test-key").transcribe(_audio(url)) is None

    asyncio.run(scenario())


@pytest.mark.parametrize("redirect", ["https://evil.example/voice", "http://audio.oneme.ru/voice"])
def test_speechkit_checks_download_redirects_even_if_client_follows_them(redirect):
    def transport(request):
        assert str(request.url) == _AUDIO_URL
        return httpx.Response(302, headers={"Location": redirect})

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(transport), follow_redirects=True
        ) as http:
            assert await SpeechKit(http, api_key="test-key").transcribe(_audio()) is None

    asyncio.run(scenario())


def test_speechkit_supports_redirects_between_max_cdn_hosts():
    def transport(request):
        if str(request.url) == _AUDIO_URL:
            return httpx.Response(302, headers={"Location": "https://audio.oneme.ru/path.ogg"})
        if request.url.host == "audio.oneme.ru":
            return httpx.Response(200, content=_OGG_OPUS)
        return httpx.Response(200, json={"result": "расписание"})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            assert await SpeechKit(http, api_key="test-key").transcribe(_audio()) == "расписание"

    asyncio.run(scenario())


def test_speechkit_stops_reading_oversized_audio_even_without_content_length():
    class AudioStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield _OGG_OPUS
            for _ in range(17):
                yield b"\x00" * 65536
            pytest.fail("Audio stream was read past the upload limit")

    def transport(request):
        assert request.method == "GET"
        return httpx.Response(200, stream=AudioStream())

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            assert await SpeechKit(http, api_key="test-key").transcribe(_audio()) is None

    asyncio.run(scenario())


@pytest.mark.parametrize("data", [b"ID3 other audio", _OGG_OPUS[:37] + b"\x02" + _OGG_OPUS[38:]])
def test_speechkit_does_not_send_unsupported_audio(data):
    def transport(request):
        assert request.method == "GET"
        return httpx.Response(200, content=data)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            assert await SpeechKit(http, api_key="test-key").transcribe(_audio()) is None

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("status", "body"),
    [(429, b"{}"), (200, b"invalid JSON"), (200, b"[]"), (200, b'{"result": "   "}')],
)
def test_speechkit_falls_back_when_recognition_produces_no_text(status, body):
    def transport(request):
        if request.method == "GET":
            return httpx.Response(200, content=_OGG_OPUS)
        return httpx.Response(status, content=body)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            assert await SpeechKit(http, api_key="test-key").transcribe(_audio()) is None

    asyncio.run(scenario())
