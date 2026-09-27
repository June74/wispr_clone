"""OpenRouter audio transcription adapter pinned to DeepInfra."""

from __future__ import annotations

import array
import base64
import io
import sys
import wave
from collections.abc import Callable
from pathlib import Path
from threading import Lock

import httpx

from wispr_clone.contracts.common import ErrorCode, ThirdPartyError, WisprError

from .base import SAMPLE_RATE, SttSession, TextCallback


class OpenRouterWhisper:
    def __init__(
        self,
        *,
        api_key: Callable[[], str | None],
        base_url: str = "https://openrouter.ai/api/v1",
        model: str = "openai/whisper-large-v3-turbo",
        provider_only: tuple[str, ...] = ("deepinfra",),
        timeout_s: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
        language: str | None = None,
    ) -> None:
        if not base_url.startswith("https://"):
            raise WisprError(ErrorCode.VALIDATION, "stt", "base_url")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._provider_only = provider_only
        self._timeout_s = timeout_s
        self._transport = transport
        self._language = language
        self._client: httpx.AsyncClient | None = None
        self._active: _BufferSession | None = None
        self._lock = Lock()

    @property
    def ready(self) -> bool:
        return bool(self._api_key())

    async def start(self) -> None:
        return

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_s,
                transport=self._transport,
                follow_redirects=False,
            )
        return self._client

    async def _send(self, wav_data: bytes) -> str:
        key = self._api_key()
        if not key:
            raise ThirdPartyError(
                "openrouter", "transcribe", "missing key", ErrorCode.API_KEY_MISSING
            )
        body: dict[str, object] = {
            "model": self._model,
            "input_audio": {
                "data": base64.b64encode(wav_data).decode("ascii"),
                "format": "wav",
            },
            "provider": {"only": list(self._provider_only), "allow_fallbacks": False},
        }
        if self._language:
            body["language"] = self._language
        request_error: ErrorCode | None = None
        try:
            response = await self._http().post(
                "/audio/transcriptions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
        except httpx.HTTPError as exc:
            request_error = (
                ErrorCode.STT_TIMEOUT
                if isinstance(exc, httpx.TimeoutException)
                else ErrorCode.STT_UNAVAILABLE
            )
        if request_error is not None:
            raise ThirdPartyError(
                "openrouter",
                "transcribe",
                "timeout"
                if request_error == ErrorCode.STT_TIMEOUT
                else "request failed",
                request_error,
            ) from None
        if response.status_code in (401, 403):
            raise ThirdPartyError(
                "openrouter",
                "transcribe",
                "credentials rejected",
                ErrorCode.API_KEY_INVALID,
            )
        if (
            response.status_code in (402, 429)
            or response.status_code >= 500
            or response.status_code != 200
        ):
            raise ThirdPartyError(
                "openrouter",
                "transcribe",
                "service unavailable",
                ErrorCode.STT_UNAVAILABLE,
            )
        try:
            result = response.json()
        except (ValueError, UnicodeError):
            result = None
        if result is None:
            raise ThirdPartyError(
                "openrouter",
                "transcribe",
                "invalid response",
                ErrorCode.STT_UNAVAILABLE,
            ) from None
        if not isinstance(result, dict) or not isinstance(result.get("text"), str):
            raise ThirdPartyError(
                "openrouter",
                "transcribe",
                "invalid response",
                ErrorCode.STT_UNAVAILABLE,
            )
        text = result.get("text")
        assert isinstance(text, str)
        return text.strip()

    async def _transcribe_wav(self, data: bytes) -> str:
        return await self._send(data)

    def start_session(self, on_text: TextCallback | None = None) -> SttSession:
        del on_text
        with self._lock:
            if self._active is not None:
                raise WisprError(ErrorCode.STT_UNAVAILABLE, "stt", "session active")
            session = _BufferSession(self)
            self._active = session
            return session

    def _release(self, session: _BufferSession) -> None:
        with self._lock:
            if self._active is session:
                self._active = None

    async def transcribe_file(self, path: Path) -> str:
        try:
            with wave.open(str(path), "rb") as reader:
                if (
                    reader.getframerate() != SAMPLE_RATE
                    or reader.getnchannels() != 1
                    or reader.getsampwidth() != 2
                    or reader.getcomptype() != "NONE"
                ):
                    raise WisprError(ErrorCode.VALIDATION, "stt", "wav format")
                data = reader.readframes(reader.getnframes())
        except (wave.Error, EOFError, OSError):
            invalid_wav = True
        else:
            invalid_wav = False
        if invalid_wav:
            raise WisprError(ErrorCode.VALIDATION, "stt", "wav format") from None
        return await self._transcribe_wav(_wav_bytes(data))

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def _wav_bytes(pcm: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(SAMPLE_RATE)
        writer.writeframes(pcm)
    return buffer.getvalue()


class _BufferSession:
    def __init__(self, owner: OpenRouterWhisper) -> None:
        self.owner = owner
        self.samples = array.array("h")
        self.closed = False
        self.cancelled = False

    def push_audio(self, samples: array.array[float]) -> None:
        if self.closed or self.cancelled:
            raise WisprError(ErrorCode.STT_STREAM_CLOSED, "stt", "closed")
        if not isinstance(samples, array.array) or samples.typecode != "f":
            raise TypeError('samples must be array.array with typecode "f"')
        for value in samples:
            self.samples.append(max(-32768, min(32767, round(value * 32768))))

    async def finish(self) -> str:
        if self.cancelled or self.closed:
            raise WisprError(ErrorCode.STT_STREAM_CLOSED, "stt", "closed")
        self.closed = True
        if not self.samples:
            self.owner._release(self)
            return ""
        samples = self.samples
        if sys.byteorder != "little":
            samples.byteswap()
        try:
            return await self.owner._transcribe_wav(_wav_bytes(samples.tobytes()))
        finally:
            self.owner._release(self)

    def cancel(self) -> None:
        self.samples = array.array("h")
        self.cancelled = True
        self.closed = True
        self.owner._release(self)
