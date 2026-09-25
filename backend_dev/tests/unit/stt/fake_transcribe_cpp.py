"""Small injectable transcribe_cpp 0.2.3 stand-in with observable native calls."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any


class TranscribeError(RuntimeError):
    pass


class Aborted(TranscribeError):
    pass


class ModelFileNotFound(TranscribeError):
    pass


class ModelLoadError(TranscribeError):
    pass


class OutOfMemory(TranscribeError):
    pass


class BackendError(TranscribeError):
    pass


class InvalidArgument(TranscribeError):
    pass


class InputTooLong(TranscribeError):
    pass


@dataclass(frozen=True)
class BackendDevice:
    name: str
    device_type: str = "CUDA"
    description: str = "fake"
    memory_free: int = 1_000_000


@dataclass(frozen=True)
class Result:
    text: str


@dataclass(frozen=True)
class StreamText:
    full: str
    committed: str
    tentative: str


@dataclass(frozen=True)
class StreamUpdate:
    text: str = ""


@dataclass
class Control:
    calls: list[tuple[str, int]] = field(default_factory=list)
    run_pcm: list[list[float]] = field(default_factory=list)
    chunks: list[list[float]] = field(default_factory=list)
    devices: list[BackendDevice | None] = field(default_factory=list)
    updates: list[StreamText] = field(default_factory=list)
    final: StreamText = field(
        default_factory=lambda: StreamText("full", "committed", "tentative")
    )
    load_error: Exception | None = None
    feed_error: Exception | None = None
    finalize_error: Exception | None = None
    run_entered: threading.Event = field(default_factory=threading.Event)
    run_release: threading.Event = field(default_factory=threading.Event)
    feed_entered: threading.Event = field(default_factory=threading.Event)
    feed_release: threading.Event = field(default_factory=threading.Event)
    block_run: bool = False
    block_feed: bool = False
    sessions: list[Any] = field(default_factory=list)

    def record(self, name: str) -> None:
        self.calls.append((name, threading.get_ident()))


def make_fake() -> ModuleType:
    """Create a fresh module and controls for each test."""
    module = ModuleType("transcribe_cpp")
    control = Control()

    class Stream:
        def __init__(self, session: Session):
            self.session = session
            self.current = StreamText("", "", "")

        def __enter__(self) -> Stream:
            return self

        def __exit__(self, *_args: object) -> None:
            self.close()

        def feed(self, pcm: Any) -> StreamUpdate:
            control.record("feed")
            control.chunks.append(list(pcm))
            control.feed_entered.set()
            if control.block_feed:
                if not control.feed_release.wait(10):
                    raise TimeoutError("fake feed release timed out")
            if self.session.was_aborted:
                raise Aborted("cancelled")
            if control.feed_error:
                raise control.feed_error
            index = len(control.chunks) - 1
            self.current = (
                control.updates[index]
                if index < len(control.updates)
                else control.final
            )
            return StreamUpdate(self.current.full)

        def text(self) -> StreamText:
            control.record("text")
            return self.current

        def finalize(self) -> StreamUpdate:
            control.record("finalize")
            if control.finalize_error:
                raise control.finalize_error
            self.current = control.final
            return StreamUpdate(self.current.full)

        def reset(self) -> None:
            control.record("reset")
            self.current = StreamText("", "", "")

        def close(self) -> None:
            control.record("stream.close")

    class Session:
        def __init__(self) -> None:
            self.was_aborted = False
            control.sessions.append(self)

        def __enter__(self) -> Session:
            return self

        def __exit__(self, *_args: object) -> None:
            self.close()

        def run(self, pcm: Any) -> Result:
            control.record("run")
            control.run_pcm.append(list(pcm))
            control.run_entered.set()
            if control.block_run and not control.run_release.wait(10):
                raise TimeoutError("fake run release timed out")
            return Result("warm")

        def stream(self, **_options: Any) -> Stream:
            control.record("stream")
            return Stream(self)

        def cancel(self) -> None:
            control.record("cancel")
            self.was_aborted = True
            control.feed_release.set()

        def close(self) -> None:
            control.record("session.close")

    class Model:
        def __init__(
            self,
            path: Any,
            *,
            backend: str = "auto",
            device: BackendDevice | None = None,
        ):
            control.record("Model")
            control.devices.append(device)
            if control.load_error:
                raise control.load_error

        def __enter__(self) -> Model:
            return self

        def __exit__(self, *_args: object) -> None:
            self.close()

        def session(self) -> Session:
            control.record("session")
            return Session()

        def close(self) -> None:
            control.record("model.close")

    def backends() -> list[BackendDevice]:
        control.record("backends")
        return [BackendDevice("CUDA0"), BackendDevice("CPU", "CPU")]

    for name, value in {
        "__version__": "0.2.3",
        "control": control,
        "backends": backends,
        "BackendDevice": BackendDevice,
        "Model": Model,
        "Session": Session,
        "Stream": Stream,
        "StreamText": StreamText,
        "StreamUpdate": StreamUpdate,
        "Result": Result,
        "TranscribeError": TranscribeError,
        "Aborted": Aborted,
        "ModelFileNotFound": ModelFileNotFound,
        "ModelLoadError": ModelLoadError,
        "OutOfMemory": OutOfMemory,
        "BackendError": BackendError,
        "InvalidArgument": InvalidArgument,
        "InputTooLong": InputTooLong,
    }.items():
        setattr(module, name, value)
    errors = ModuleType("transcribe_cpp.errors")
    for name in (
        "TranscribeError",
        "Aborted",
        "ModelFileNotFound",
        "ModelLoadError",
        "OutOfMemory",
        "BackendError",
        "InvalidArgument",
        "InputTooLong",
    ):
        setattr(errors, name, getattr(module, name))
    module.errors = errors
    return module
