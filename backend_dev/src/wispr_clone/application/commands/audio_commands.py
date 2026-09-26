"""Handlers for input device discovery and temporary microphone tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from typing import Protocol

from wispr_clone.application.api import CommandSpec
from wispr_clone.audio.capture import CaptureChunk
from wispr_clone.audio.devices import InputDevice
from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.contracts.events import EventSink


class CaptureLike(Protocol):
    def start(self) -> None: ...

    def chunks(self) -> AsyncIterator[CaptureChunk]: ...

    def stop(self) -> None: ...

    def cancel(self) -> None: ...


class AudioCommands:
    """Publish live levels during a bounded, non-recording microphone test."""

    def __init__(
        self,
        *,
        list_devices: Callable[[], tuple[InputDevice, ...]],
        new_test_capture: Callable[[int | None], CaptureLike],
        events: EventSink,
        max_test_s: float = 30.0,
    ) -> None:
        self._list_devices = list_devices
        self._new_test_capture = new_test_capture
        self._events = events
        self._max_test_s = max_test_s
        self._capture: CaptureLike | None = None
        self._task: asyncio.Task[None] | None = None

    def specs(self) -> dict[str, CommandSpec]:
        return {
            "mic_list": CommandSpec(self._list, mutating=False),
            "mic_test_start": CommandSpec(self._start, mutating=True),
            "mic_test_stop": CommandSpec(self._stop, mutating=True),
        }

    async def _list(self, _: Mapping[str, object]) -> Mapping[str, object]:
        return {
            "devices": [
                {
                    "device_id": device.device_id,
                    "name": device.name,
                    "is_default": device.is_default,
                }
                for device in self._list_devices()
            ]
        }

    async def _start(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        if self._task is not None and not self._task.done():
            previous_task = self._task
            if self._capture_stopped(self._capture):
                try:
                    await asyncio.wait_for(asyncio.shield(previous_task), timeout=1.0)
                except TimeoutError:
                    raise WisprError(
                        ErrorCode.DEVICE_LEASE_CONFLICT, "audio", "test active"
                    ) from None
                self._clear_finished()
            else:
                raise WisprError(
                    ErrorCode.DEVICE_LEASE_CONFLICT, "audio", "test active"
                )
        else:
            self._clear_finished()
        device_id = payload.get("device_id")
        if device_id is not None and type(device_id) is not int:
            raise WisprError(ErrorCode.VALIDATION, "audio", "device_id")
        capture = self._new_test_capture(device_id)
        try:
            capture.start()
        except Exception:
            try:
                capture.cancel()
            except Exception:
                pass
            raise
        self._capture = capture
        self._task = asyncio.create_task(self._pump(capture))
        return {"started": True}

    async def _stop(self, _: Mapping[str, object]) -> Mapping[str, object]:
        task = self._task
        capture = self._capture
        if task is None or task.done() or capture is None:
            self._clear_finished()
            return {"stopped": False}
        try:
            capture.stop()
        except Exception:
            pass
        await asyncio.gather(task, return_exceptions=True)
        self._clear_finished()
        return {"stopped": True}

    async def _pump(self, capture: CaptureLike) -> None:
        async def consume() -> None:
            async for chunk in capture.chunks():
                self._events.publish(
                    {"name": "audio:level", "run_id": None, "bands": chunk.bands}
                )

        pump = asyncio.create_task(consume())
        timer = asyncio.create_task(asyncio.sleep(self._max_test_s))
        try:
            done, _ = await asyncio.wait(
                {pump, timer}, return_when=asyncio.FIRST_COMPLETED
            )
            if timer in done and not pump.done():
                capture.stop()
                await pump
            elif pump in done:
                await pump
        except Exception:
            try:
                capture.cancel()
            except Exception:
                pass
        finally:
            for task in (pump, timer):
                if not task.done():
                    task.cancel()
            await asyncio.gather(pump, timer, return_exceptions=True)
            if self._capture is capture:
                self._capture = None
                self._task = None

    def _clear_finished(self) -> None:
        if self._task is not None and self._task.done():
            self._task = None
            self._capture = None

    @staticmethod
    def _capture_stopped(capture: CaptureLike | None) -> bool:
        if capture is None:
            return True
        stopped = getattr(capture, "stopped", None)
        if isinstance(stopped, bool):
            return stopped
        event = getattr(capture, "_stopped", None)
        cancelled = getattr(capture, "cancelled", False)
        if not cancelled:
            cancel_event = getattr(capture, "_cancelled", None)
            cancelled = cancel_event is not None and cancel_event.is_set()
        return bool((event is not None and event.is_set()) or cancelled)
