"""Bounded microphone capture with consumer-side audio processing."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from queue import Empty, Full, Queue
from threading import Event
from types import ModuleType
from typing import Any

import numpy as np

from wispr_clone.contracts.common import ErrorCode, ThirdPartyError, WisprError

from .device_lease import DeviceLease, LeaseOwner, LeaseToken
from .level_meter import band_levels
from .resample import streaming_resampler

SAMPLE_RATE = 16_000
CHUNK_SAMPLES = 1_280


@dataclass(frozen=True, slots=True)
class CaptureChunk:
    """One STT-sized audio block and its waveform levels."""

    samples: np.ndarray
    bands: list[float]


class AudioCapture:
    """Capture input frames into a bounded queue and process them asynchronously."""

    def __init__(
        self,
        lease: DeviceLease,
        *,
        device_id: int | None = None,
        queue_max_blocks: int = 500,
        block_ms: int = 80,
        module: ModuleType | None = None,
        owner: LeaseOwner = "capture",
    ) -> None:
        if queue_max_blocks < 1 or block_ms < 1:
            raise ValueError("queue_max_blocks and block_ms must be positive")
        self._lease = lease
        self._device_id = device_id
        self._queue: Queue[np.ndarray] = Queue(maxsize=queue_max_blocks)
        self._block_ms = block_ms
        self._module = module
        self._owner = owner
        self._token: LeaseToken | None = None
        self._stream: Any | None = None
        self._accepting = Event()
        self._stopped = Event()
        self._cancelled = Event()
        self._overflow = Event()
        self._device_error: str | None = None
        self._stream_finished = Event()
        self._consumer_started = False
        self._sample_rate = SAMPLE_RATE

    def start(self) -> None:
        """Acquire the device and start its callback stream."""
        token = self._lease.acquire(self._owner)
        self._token = token
        try:
            if self._module is None:
                import sounddevice as sd  # type: ignore[import-untyped]
            else:
                sd = self._module
            device = self._device_id
            rate = SAMPLE_RATE
            if device is None:
                device = sd.default.device[0]
            if device is not None and device >= 0:
                details = sd.query_devices(device, kind="input")
                rate = int(float(details["default_samplerate"]))
            self._sample_rate = rate
            blocksize = max(1, round(rate * self._block_ms / 1000))
            self._accepting.set()

            def callback(
                indata: np.ndarray,
                frames: int,
                time_info: object,
                status: object,
            ) -> None:
                del frames, time_info
                if not self._accepting.is_set():
                    return
                if bool(getattr(status, "input_overflow", False)):
                    self._overflow.set()
                    self._accepting.clear()
                    return
                # PortAudio status flags such as input_underflow are informational.
                # A textual backend/device failure is still surfaced for the fake and
                # backends that report a concrete error this way.
                detail = str(status) if status else ""
                if detail and not detail.startswith("input "):
                    self._device_error = type(status).__name__
                    self._accepting.clear()
                    return
                copied = indata.copy()
                try:
                    self._queue.put_nowait(copied)
                except Full:
                    self._overflow.set()
                    self._accepting.clear()

            def finished_callback() -> None:
                if not self._stopped.is_set() and not self._cancelled.is_set():
                    self._device_error = "stream finished"
                    self._stream_finished.set()

            self._stream = sd.InputStream(
                device=self._device_id,
                channels=1,
                dtype="float32",
                samplerate=rate,
                blocksize=blocksize,
                callback=callback,
                finished_callback=finished_callback,
            )
            self._stream.start()
        except Exception as exc:
            self._accepting.clear()
            self._stopped.set()
            self._close_stream()
            self._release_lease()
            raise ThirdPartyError(
                "sounddevice",
                "open",
                type(exc).__name__,
                ErrorCode.MICROPHONE_UNAVAILABLE,
            ) from exc

    async def chunks(self) -> AsyncIterator[CaptureChunk]:
        """Drain queued audio, process it off the callback, and yield STT chunks."""
        if self._consumer_started:
            raise RuntimeError("capture chunks can only be consumed once")
        self._consumer_started = True
        pending = np.empty(0, dtype=np.float32)
        loop = asyncio.get_running_loop()
        resampler = (
            streaming_resampler(self._source_rate())
            if self._source_rate() != SAMPLE_RATE
            else None
        )
        try:
            while True:
                if self._cancelled.is_set():
                    return
                try:
                    block = await loop.run_in_executor(
                        None, self._queue.get, True, 0.05
                    )
                except Empty:
                    if self._terminal():
                        break
                    continue
                processed = (
                    np.asarray(
                        resampler.resample_chunk(block, last=False), dtype=np.float32
                    ).reshape(-1)
                    if resampler is not None
                    else block.reshape(-1).astype(np.float32, copy=False)
                )
                if processed.size:
                    pending = np.concatenate((pending, processed))
                while pending.size >= CHUNK_SAMPLES:
                    result = np.ascontiguousarray(pending[:CHUNK_SAMPLES])
                    pending = pending[CHUNK_SAMPLES:]
                    yield CaptureChunk(result, band_levels(result, SAMPLE_RATE))
                if self._terminal() and self._queue.empty():
                    break
            if self._cancelled.is_set():
                return
            if resampler is not None:
                tail = np.asarray(
                    resampler.resample_chunk(np.empty(0, dtype=np.float32), last=True),
                    dtype=np.float32,
                ).reshape(-1)
                if tail.size:
                    pending = np.concatenate((pending, tail))
                    while pending.size >= CHUNK_SAMPLES:
                        result = np.ascontiguousarray(pending[:CHUNK_SAMPLES])
                        pending = pending[CHUNK_SAMPLES:]
                        yield CaptureChunk(result, band_levels(result, SAMPLE_RATE))
            if pending.size:
                result = np.ascontiguousarray(pending)
                yield CaptureChunk(result, band_levels(result, SAMPLE_RATE))
            if self._device_error is not None:
                raise ThirdPartyError(
                    "sounddevice",
                    "stream",
                    self._device_error,
                    ErrorCode.MICROPHONE_DISCONNECTED,
                )
            if self._overflow.is_set():
                raise WisprError(
                    ErrorCode.AUDIO_QUEUE_OVERFLOW, "audio", "queue overflow"
                )
        except BaseException:
            self.stop()
            raise
        finally:
            if self._terminal():
                self._release_lease()

    def stop(self) -> None:
        """Stop input and allow already queued blocks to drain."""
        if self._cancelled.is_set():
            return
        self._accepting.clear()
        self._stopped.set()
        self._close_stream()
        self._release_lease()

    def cancel(self) -> None:
        """Stop input, discard queued blocks, and end the consumer immediately."""
        self._cancelled.set()
        self._accepting.clear()
        self._stopped.set()
        self._close_stream()
        while True:
            try:
                self._queue.get_nowait()
            except Empty:
                break
        self._release_lease()

    def _source_rate(self) -> int:
        return self._sample_rate

    def _terminal(self) -> bool:
        return (
            self._stopped.is_set()
            or self._cancelled.is_set()
            or self._overflow.is_set()
            or self._device_error is not None
            or self._stream_finished.is_set()
        )

    def _close_stream(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is None:
            return
        try:
            stream.stop()
        except Exception:
            pass
        try:
            stream.close()
        except Exception:
            pass

    def _release_lease(self) -> None:
        token = self._token
        self._token = None
        if token is not None:
            self._lease.release(token)
