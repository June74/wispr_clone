"""Offline acceptance tests for the OpenRouter Whisper adapter."""

import array
import base64
import io
import json
import math
import struct
import wave
from pathlib import Path

import httpx
import pytest

from wispr_clone.contracts.common import ErrorCode, ThirdPartyError, WisprError

FAKE_KEY = "sk-or-v1-test-cloud-stt-key"
MODEL = "openai/whisper-large-v3-turbo"


def make_engine(handler, *, key=FAKE_KEY, **options):
    from wispr_clone.stt.openrouter_whisper import OpenRouterWhisper

    return OpenRouterWhisper(
        api_key=lambda: key, transport=httpx.MockTransport(handler), **options
    )


def samples() -> array.array[float]:
    """0.5 s silence, 1 s of a 440 Hz tone (stands in for speech), 0.5 s silence."""
    silence = [0.0] * 8_000
    tone = [0.5 * math.sin(2 * math.pi * 440 * i / 16_000) for i in range(16_000)]
    return array.array("f", silence + tone + silence)


def speech_pcm() -> bytes:
    return b"".join(
        struct.pack("<h", max(-32768, min(32767, round(v * 32768)))) for v in samples()
    )


# Speech-gate trim: 1 s of tone plus 0.3 s before and 0.4 s after it.
TRIMMED_FRAMES = 16_000 + 4_800 + 6_400


@pytest.mark.unit
@pytest.mark.asyncio
async def test_T_STT_020_request_shape_and_wav() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"text": "  dictated words  "})

    engine = make_engine(respond)
    assert engine.ready is True
    await engine.start()
    session = engine.start_session()
    session.push_audio(samples())
    assert await session.finish() == "dictated words"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://openrouter.ai/api/v1/audio/transcriptions"
    assert request.headers["authorization"] == f"Bearer {FAKE_KEY}"
    assert request.headers["content-type"] == "application/json"
    body = json.loads(request.content)
    assert set(body) == {"model", "input_audio", "provider"}
    assert body["model"] == MODEL
    assert body["provider"] == {"only": ["deepinfra"], "allow_fallbacks": False}
    assert set(body["input_audio"]) == {"data", "format"}
    assert body["input_audio"]["format"] == "wav"
    wav_bytes = base64.b64decode(body["input_audio"]["data"], validate=True)
    with wave.open(io.BytesIO(wav_bytes), "rb") as reader:
        assert (
            reader.getnchannels(),
            reader.getsampwidth(),
            reader.getframerate(),
        ) == (
            1,
            2,
            16_000,
        )
        assert reader.getnframes() == TRIMMED_FRAMES
        frames = reader.readframes(TRIMMED_FRAMES)
    start = (8_000 - 4_800) * 2
    assert frames == speech_pcm()[start : start + TRIMMED_FRAMES * 2]
    await engine.close()


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,code",
    [
        ("401", "api_key_invalid"),
        ("403", "api_key_invalid"),
        ("402", "stt_unavailable"),
        ("429", "stt_unavailable"),
        ("500", "stt_unavailable"),
        ("bad-json", "stt_unavailable"),
        ("missing-text", "stt_unavailable"),
        ("non-string-text", "stt_unavailable"),
        ("timeout", "stt_timeout"),
        ("connect", "stt_unavailable"),
    ],
)
async def test_T_STT_021_status_mapping_and_no_retry(kind: str, code: str) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if kind == "timeout":
            raise httpx.ReadTimeout("private response", request=request)
        if kind == "connect":
            raise httpx.ConnectError("private response", request=request)
        if kind == "bad-json":
            return httpx.Response(200, text="private response")
        if kind == "missing-text":
            return httpx.Response(200, json={"private": "response"})
        if kind == "non-string-text":
            return httpx.Response(200, json={"text": 7})
        return httpx.Response(int(kind), text="private response")

    engine = make_engine(respond)
    session = engine.start_session()
    session.push_audio(samples())
    with pytest.raises(ThirdPartyError) as caught:
        await session.finish()
    assert caught.value.error_code.value == code
    assert len(requests) == 1
    assert "private response" not in str(caught.value)
    assert "private response" not in caught.value.detail
    await engine.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_T_STT_022_key_empty_cancel_and_single_session() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"text": ""})

    engine = make_engine(respond, key=None)
    assert engine.ready is False
    session = engine.start_session()
    session.push_audio(samples())
    with pytest.raises(ThirdPartyError) as caught:
        await session.finish()
    assert caught.value.error_code.value == "api_key_missing"
    assert requests == []
    await engine.close()

    engine = make_engine(respond)
    assert await engine.start_session().finish() == ""
    assert requests == []
    active = engine.start_session()
    with pytest.raises(WisprError) as caught:
        engine.start_session()
    assert caught.value.error_code == ErrorCode.STT_UNAVAILABLE
    active.cancel()
    with pytest.raises(WisprError) as caught:
        await active.finish()
    assert caught.value.error_code == ErrorCode.STT_STREAM_CLOSED
    assert requests == []
    await engine.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_T_STT_023_secrets_absent_from_errors_and_logs(caplog) -> None:
    encoded = base64.b64encode(b"secret audio sentinel").decode()

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text=f"{FAKE_KEY} {encoded}")

    engine = make_engine(respond)
    session = engine.start_session()
    session.push_audio(samples())
    with pytest.raises(ThirdPartyError) as caught:
        await session.finish()
    exposed = " ".join(
        (str(caught.value), caught.value.detail, caplog.text, repr(engine))
    )
    assert FAKE_KEY not in exposed
    assert encoded not in exposed
    await engine.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_T_STT_024_replay_validation_https_and_no_redirect(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            302, headers={"location": "https://example.test/elsewhere"}
        )

    engine = make_engine(respond)
    valid = tmp_path / "valid.wav"
    with wave.open(str(valid), "wb") as writer:
        writer.setparams((1, 2, 16_000, 0, "NONE", "not compressed"))
        writer.writeframes(speech_pcm())
    with pytest.raises(ThirdPartyError):
        await engine.transcribe_file(valid)
    assert len(requests) == 1
    sent = base64.b64decode(json.loads(requests[0].content)["input_audio"]["data"])
    with wave.open(io.BytesIO(sent), "rb") as reader:
        assert reader.getnframes() == TRIMMED_FRAMES
    for channels, width, rate in ((2, 2, 16_000), (1, 1, 16_000), (1, 2, 8_000)):
        invalid = tmp_path / f"invalid-{channels}-{width}-{rate}.wav"
        with wave.open(str(invalid), "wb") as writer:
            writer.setparams((channels, width, rate, 0, "NONE", "not compressed"))
            writer.writeframes(b"\x00" * (channels * width * 4))
        with pytest.raises(WisprError) as caught:
            await engine.transcribe_file(invalid)
        assert caught.value.error_code == ErrorCode.VALIDATION
    assert len(requests) == 1
    await engine.close()
    with pytest.raises(WisprError) as caught:
        make_engine(respond, base_url="http://openrouter.ai/api/v1")
    assert caught.value.error_code == ErrorCode.VALIDATION


@pytest.mark.asyncio
async def test_T_STT_020_switching_model_changes_provider_routing() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"text": "hello"})

    engine = make_engine(handler)
    engine.use_model("deepgram/nova-3")
    assert engine.model == "deepgram/nova-3"
    await engine._send(b"RIFF")
    engine.use_model(MODEL)
    await engine._send(b"RIFF")
    assert [(b["model"], b["provider"]) for b in bodies] == [
        ("deepgram/nova-3", {"data_collection": "deny"}),
        (MODEL, {"only": ["deepinfra"], "allow_fallbacks": False}),
    ]
    await engine.close()


@pytest.mark.asyncio
async def test_T_STT_032_silent_recording_is_not_sent() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"text": "Thank you."})

    engine = make_engine(respond)
    session = engine.start_session()
    session.push_audio(array.array("f", [0.0] * 32_000))
    assert await session.finish() == ""
    assert requests == []
    await engine.close()
