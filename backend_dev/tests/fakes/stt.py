"""Recording STT engine and session implementing the public protocols."""

from __future__ import annotations

import array
import sys
import wave
from pathlib import Path

from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.stt.base import (
    CHUNK_SAMPLES,
    SAMPLE_RATE,
    SttEngine,
    SttSession,
    TextCallback,
)


class FakeSttSession:
    def __init__(self, final_text: str, on_text: TextCallback | None = None) -> None:
        self.final_text = final_text
        self.on_text = on_text
        self.pushed: list[array.array[float]] = []
        self.finished = False
        self.cancelled = False

    def push_audio(self, samples: array.array[float]) -> None:
        if samples.typecode != "f":
            raise TypeError("STT requires an array with typecode f")
        if self.finished or self.cancelled:
            raise WisprError(ErrorCode.STT_STREAM_CLOSED, "stt", "closed")
        self.pushed.append(array.array("f", samples))

    async def finish(self) -> str:
        if self.cancelled or self.finished:
            raise WisprError(ErrorCode.STT_STREAM_CLOSED, "stt", "closed")
        self.finished = True
        return self.final_text

    def cancel(self) -> None:
        if self.finished or self.cancelled:
            return
        self.cancelled = True

    def emit_text(self, committed: str, tentative: str = "") -> None:
        """Deliver a scripted callback while the session is active."""
        if self.on_text is not None and not (self.finished or self.cancelled):
            self.on_text(committed, tentative)


class FakeSttEngine:
    def __init__(self, final_text: str) -> None:
        self.final_text = final_text
        self.sessions: list[FakeSttSession] = []
        self.started = False
        self.closed = False
        self.available = True
        self.transcribed: list[Path] = []

    @property
    def ready(self) -> bool:
        return self.available and not self.closed

    async def start(self) -> None:
        self.started = True

    def start_session(self, on_text: TextCallback | None = None) -> FakeSttSession:
        if self.sessions and not (
            self.sessions[-1].finished or self.sessions[-1].cancelled
        ):
            raise WisprError(ErrorCode.STT_UNAVAILABLE, "stt", "session active")
        session = FakeSttSession(self.final_text, on_text)
        self.sessions.append(session)
        return session

    async def transcribe_file(self, path: Path) -> str:
        self.transcribed.append(path)
        try:
            with wave.open(str(path), "rb") as reader:
                if (
                    reader.getframerate() != SAMPLE_RATE
                    or reader.getnchannels() != 1
                    or reader.getsampwidth() != 2
                    or reader.getcomptype() != "NONE"
                ):
                    raise WisprError(ErrorCode.VALIDATION, "stt", "wav format")
                raw = reader.readframes(reader.getnframes())
        except (wave.Error, EOFError):
            raise WisprError(ErrorCode.VALIDATION, "stt", "wav format") from None
        samples = array.array("h")
        samples.frombytes(raw)
        if sys.byteorder != "little":
            samples.byteswap()
        session = self.start_session()
        for offset in range(0, len(samples), CHUNK_SAMPLES):
            session.push_audio(
                array.array(
                    "f",
                    (
                        sample / 32768.0
                        for sample in samples[offset : offset + CHUNK_SAMPLES]
                    ),
                )
            )
        return await session.finish()

    async def close(self) -> None:
        self.closed = True


_session_protocol_check: SttSession = FakeSttSession("")
_engine_protocol_check: SttEngine = FakeSttEngine("")
