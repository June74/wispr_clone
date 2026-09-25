"""In-process Voxtral streaming adapter backed by transcribe.cpp."""

from __future__ import annotations

import array
import asyncio
import importlib
import wave
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock
from types import ModuleType
from typing import TYPE_CHECKING, Any, cast

from wispr_clone.contracts.common import ErrorCode, ThirdPartyError, WisprError

from .base import CHUNK_SAMPLES, SAMPLE_RATE, SttSession, TextCallback

if TYPE_CHECKING:
    import transcribe_cpp  # type: ignore[import-not-found]  # noqa: F401


class _ActiveSession:
    def __init__(
        self,
        owner: VoxtralTranscribeCpp,
        loop: asyncio.AbstractEventLoop,
        callback: TextCallback | None,
    ) -> None:
        self.owner = owner
        self.loop = loop
        self.callback = callback
        self.enabled = Event()
        self.enabled.set()
        self.cancelled = False
        self.closed = False
        self.lock = Lock()
        self.error: ThirdPartyError | None = None
        self.native: Future[tuple[Any, Any]] = owner._executor.submit(self._open_native)
        self.tail: Future[Any] = self.native

    def _open_native(self) -> tuple[Any, Any]:
        model = self.owner._model
        if model is None:
            raise RuntimeError("model unavailable")
        session = model.session()
        stream = session.stream()
        return session, stream

    def push_audio(self, samples: array.array[float]) -> None:
        if not isinstance(samples, array.array) or samples.typecode != "f":
            raise TypeError('samples must be array.array with typecode "f"')
        with self.lock:
            if self.error is not None:
                error = self.error
                self.closed = True
                self.owner._release(self)
                raise error
            if self.closed or self.cancelled:
                raise WisprError(ErrorCode.STT_STREAM_CLOSED, "stt", "closed")
            pcm = array.array("f", samples)
            previous = self.tail
            future = self.owner._executor.submit(self._feed_after, previous, pcm)
            self.tail = future

    def _feed_after(self, previous: Future[Any], pcm: array.array[float]) -> None:
        try:
            previous.result()
            if self.error is not None:
                return
            session, stream = self.native.result()
            if self.cancelled:
                return
            stream.feed(pcm)
            value = stream.text()
        except BaseException as exc:
            if self.cancelled and self.owner._is_aborted(exc):
                return
            error = self.owner._session_error("feed", exc)
            with self.lock:
                self.error = error
                self.closed = True
            self.owner._release(self)
            return
        callback = self.callback
        if callback is not None:
            self.loop.call_soon_threadsafe(self._deliver, callback, value)

    def _deliver(self, callback: TextCallback, value: Any) -> None:
        if self.enabled.is_set() and not self.cancelled and not self.closed:
            callback(value.committed, value.tentative)

    async def finish(self) -> str:
        with self.lock:
            if self.cancelled:
                raise WisprError(ErrorCode.STT_STREAM_CLOSED, "stt", "cancelled")
            if self.closed:
                if self.error is not None:
                    raise self.error
                raise WisprError(ErrorCode.STT_STREAM_CLOSED, "stt", "closed")
            self.enabled.clear()
            self.closed = True
            prior_error = self.error
            pending = self.tail
        if prior_error is not None:
            self.owner._release(self)
            raise prior_error
        try:
            result = cast(
                str,
                await asyncio.wrap_future(
                    self.owner._executor.submit(
                        self._finalize_after, pending, self.native
                    )
                ),
            )
        finally:
            self.owner._release(self)
        return result

    def _finalize_after(self, pending: Future[Any], native: Future[Any]) -> str:
        session: Any | None = None
        stream: Any | None = None
        try:
            pending.result()
            if self.error is not None:
                raise self.error
            session, stream = native.result()
            stream.finalize()
            committed = stream.text().committed
            stream.close()
            session.close()
            return cast(str, committed)
        except BaseException as exc:
            if self.cancelled and self.owner._is_aborted(exc):
                raise WisprError(ErrorCode.STT_STREAM_CLOSED, "stt", "cancelled")
            if isinstance(exc, ThirdPartyError):
                raise
            raise self.owner._session_error("finalize", exc) from None
        finally:
            for resource in (stream, session):
                if resource is not None:
                    try:
                        resource.close()
                    except Exception:
                        pass

    def cancel(self) -> None:
        with self.lock:
            if self.cancelled or self.closed:
                return
            self.cancelled = True
            self.closed = True
            self.enabled.clear()
            native = self.native
        if not native.cancelled():
            try:
                session, _stream = native.result()
                session.cancel()
            except Exception:
                pass
        self.owner._release(self)
        self.owner._executor.submit(self._close_after_cancel, native)

    def _close_after_cancel(self, native: Future[Any]) -> None:
        try:
            session, stream = native.result()
        except BaseException:
            return
        try:
            stream.close()
        finally:
            session.close()


class VoxtralTranscribeCpp:
    """Load, warm and stream Voxtral using one dedicated native-call thread."""

    def __init__(
        self,
        model_path: Path,
        *,
        device_name: str = "CUDA0",
        module: ModuleType | None = None,
    ) -> None:
        self._model_path = model_path
        self._device_name = device_name
        self._module = module
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt")
        self._model: Any | None = None
        self._ready = False
        self._active: _ActiveSession | None = None
        self._lock = Lock()
        self._closed = False
        self._start_lock = asyncio.Lock()

    @property
    def ready(self) -> bool:
        return self._ready

    async def start(self) -> None:
        async with self._start_lock:
            if self._ready:
                return
            if self._closed:
                raise WisprError(ErrorCode.STT_UNAVAILABLE, "stt", "closed")
            try:
                if self._module is None:
                    try:
                        self._module = importlib.import_module("transcribe_cpp")
                    except ImportError as exc:
                        raise ThirdPartyError(
                            "transcribe-cpp",
                            "import",
                            type(exc).__name__,
                            ErrorCode.STT_UNAVAILABLE,
                        ) from None
                await asyncio.wrap_future(self._executor.submit(self._load_and_warm))
            except ThirdPartyError:
                raise
            except BaseException as exc:
                raise ThirdPartyError(
                    "transcribe-cpp",
                    "load",
                    type(exc).__name__,
                    ErrorCode.MODEL_LOAD_FAILED,
                ) from None
            self._ready = True

    def _load_and_warm(self) -> None:
        module = self._module
        if module is None:
            raise RuntimeError("module unavailable")
        devices = module.backends()
        device = next(
            (item for item in devices if item.name == self._device_name), None
        )
        if device is None:
            raise ThirdPartyError(
                "transcribe-cpp",
                "load",
                "device not found",
                ErrorCode.MODEL_LOAD_FAILED,
            )
        model = module.Model(self._model_path, device=device)
        self._model = model
        try:
            with model.session() as session:
                session.run(array.array("f", [0.0]) * SAMPLE_RATE)
        except BaseException:
            model.close()
            self._model = None
            raise

    def start_session(self, on_text: TextCallback | None = None) -> SttSession:
        if not self._ready:
            raise WisprError(ErrorCode.STT_UNAVAILABLE, "stt", "not ready")
        loop = asyncio.get_running_loop()
        with self._lock:
            if self._closed:
                raise WisprError(ErrorCode.STT_UNAVAILABLE, "stt", "closed")
            if self._active is not None:
                raise WisprError(ErrorCode.STT_UNAVAILABLE, "stt", "session active")
            active = _ActiveSession(self, loop, on_text)
            self._active = active
            return active

    def _release(self, session: _ActiveSession) -> None:
        with self._lock:
            if self._active is session:
                self._active = None

    def _session_error(self, operation: str, exc: BaseException) -> ThirdPartyError:
        return ThirdPartyError(
            "transcribe-cpp", operation, type(exc).__name__, ErrorCode.STT_UNAVAILABLE
        )

    def _is_aborted(self, exc: BaseException) -> bool:
        module = self._module
        return bool(module is not None and isinstance(exc, module.Aborted))

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
                raw = reader.readframes(reader.getnframes())
        except (wave.Error, EOFError):
            raise WisprError(ErrorCode.VALIDATION, "stt", "wav format") from None
        samples = array.array("h")
        samples.frombytes(raw)
        if __import__("sys").byteorder != "little":
            samples.byteswap()
        session = self.start_session()
        for offset in range(0, len(samples), CHUNK_SAMPLES):
            chunk = array.array(
                "f",
                (
                    sample / 32768.0
                    for sample in samples[offset : offset + CHUNK_SAMPLES]
                ),
            )
            session.push_audio(chunk)
        return await session.finish()

    async def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            active = self._active
        if active is not None:
            active.cancel()
        if self._model is not None:
            await asyncio.wrap_future(self._executor.submit(self._close_model))
        self._executor.shutdown(wait=True, cancel_futures=False)

    def _close_model(self) -> None:
        model = self._model
        if model is not None:
            model.close()
            self._model = None
