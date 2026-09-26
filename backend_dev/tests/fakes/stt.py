"""Recording STT engine and session implementing the public protocols."""

from __future__ import annotations

import array
from pathlib import Path

from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.stt.base import SttEngine, SttSession, TextCallback


class FakeSttSession:
    def __init__(self, final_text: str) -> None:
        self.final_text = final_text
        self.pushed: list[array.array[float]] = []
        self.finished = False
        self.cancelled = False

    def push_audio(self, samples: array.array[float]) -> None:
        if samples.typecode != "f":
            raise TypeError("STT requires an array with typecode f")
        self.pushed.append(array.array("f", samples))

    async def finish(self) -> str:
        self.finished = True
        return self.final_text

    def cancel(self) -> None:
        self.cancelled = True


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
        del on_text
        if self.sessions and not (
            self.sessions[-1].finished or self.sessions[-1].cancelled
        ):
            raise WisprError(ErrorCode.STT_UNAVAILABLE, "stt", "session active")
        session = FakeSttSession(self.final_text)
        self.sessions.append(session)
        return session

    async def transcribe_file(self, path: Path) -> str:
        self.transcribed.append(path)
        return self.final_text

    async def close(self) -> None:
        self.closed = True


_session_protocol_check: SttSession = FakeSttSession("")
_engine_protocol_check: SttEngine = FakeSttEngine("")
