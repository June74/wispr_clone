"""Coordinate capture, transcription, and insertion for retained runs."""

from __future__ import annotations

import array
import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from wispr_clone.audio.capture import CaptureChunk
from wispr_clone.contracts.common import ErrorCode, ThirdPartyError, WisprError
from wispr_clone.contracts.events import EventSink
from wispr_clone.contracts.run import CleanupStatus
from wispr_clone.dictionary.apply import apply_dictionary
from wispr_clone.dictionary.repo import DictionaryRepo
from wispr_clone.history.repo import HistoryRepo, RunRecord
from wispr_clone.insertion.destination import DestinationSnapshot
from wispr_clone.pipeline.insertion_protocol import (
    InsertionProtocol,
    ProtocolOutcome,
    ProtocolResult,
)
from wispr_clone.pipeline.state_machine import (
    RunEvent,
    RunState,
    is_terminal,
    transition,
)
from wispr_clone.stt.base import SttEngine, SttSession


class CaptureLike(Protocol):
    def start(self) -> None: ...

    def chunks(self) -> AsyncIterator[CaptureChunk]: ...

    def stop(self) -> None: ...

    def cancel(self) -> None: ...


class WavLike(Protocol):
    def write(self, samples: Any) -> None: ...

    def close(self) -> None: ...

    @property
    def frames_written(self) -> int: ...


@dataclass(frozen=True, slots=True)
class RunServices:
    history: HistoryRepo
    dictionary: DictionaryRepo
    stt: SttEngine
    insertion: InsertionProtocol
    events: EventSink
    capture_destination: Callable[[], Awaitable[DestinationSnapshot]]
    new_capture: Callable[[], CaptureLike]
    new_wav: Callable[[Path], WavLike]
    new_id: Callable[[], str]
    audio_dir: Path
    config_snapshot: Callable[[], Mapping[str, object]]


def events_for(result: ProtocolResult) -> tuple[RunEvent, ...]:
    """Map protocol outcomes onto the controller-owned state machine events."""
    return {
        ProtocolOutcome.INSERTED: (RunEvent.DISPATCH_BEGIN_AUTO, RunEvent.INSERTED),
        ProtocolOutcome.UNCERTAIN: (
            RunEvent.DISPATCH_BEGIN_AUTO,
            RunEvent.INSERT_UNCERTAIN,
        ),
        ProtocolOutcome.FAILED: (
            RunEvent.DISPATCH_BEGIN_AUTO,
            RunEvent.INSERT_FAILED,
        ),
        ProtocolOutcome.AWAITING: (RunEvent.DESTINATION_AWAY,),
        ProtocolOutcome.HELD: (RunEvent.HOLD,),
        ProtocolOutcome.CANCELLED: (RunEvent.CANCEL,),
        ProtocolOutcome.ABANDONED: (),
        ProtocolOutcome.DUPLICATE: (),
    }[result.outcome]


class RunController:
    def __init__(self, services: RunServices) -> None:
        self._services = services
        self._active_run_id: str | None = None
        self._slot_reserved = False
        self._captures: dict[str, CaptureLike] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._snapshots: dict[str, DestinationSnapshot | None] = {}
        self._task_errors_pending: set[str] = set()
        self._cancel_flags: dict[str, bool] = {}
        self._sessions: dict[str, SttSession] = {}
        self._wavs: dict[str, WavLike] = {}

    @property
    def active_run_id(self) -> str | None:
        return self._active_run_id

    async def start(self, *, start_request_id: str) -> str:
        if self._slot_reserved:
            raise WisprError(ErrorCode.DEVICE_LEASE_CONFLICT, "run", "busy")
        self._slot_reserved = True
        try:
            try:
                snapshot = await self._services.capture_destination()
            except WisprError as error:
                if error.error_code != ErrorCode.DESTINATION_UNVERIFIABLE:
                    raise
                snapshot = None
            run_id = self._services.new_id()
            path = self._services.audio_dir / f"{run_id}.wav"
            record = await self._services.history.create_run(
                run_id=run_id,
                start_request_id=start_request_id,
                config=self._services.config_snapshot(),
                destination=snapshot.to_json() if snapshot is not None else None,
                audio_path=str(path),
            )
            self._publish_state(record)
            capture: CaptureLike | None = None
            capture_started = False
            session: SttSession | None = None
            try:
                capture = self._services.new_capture()
                capture.start()
                capture_started = True
                session = self._services.stt.start_session()
                wav = self._services.new_wav(path)
            except Exception as error:
                if capture is not None and capture_started:
                    capture.cancel()
                if session is not None:
                    session.cancel()
                error_code = _error_code(error)
                failed = transition(
                    RunState(record.status, record.version), RunEvent.FAIL
                )
                updated = await self._services.history.update_run(
                    run_id,
                    expected_version=record.version,
                    status=failed.status,
                    error_code=error_code.value,
                )
                self._publish_state(updated)
                raise
            assert capture is not None and session is not None
            self._active_run_id = run_id
            self._captures[run_id] = capture
            self._snapshots[run_id] = snapshot
            self._cancel_flags[run_id] = False
            self._sessions[run_id] = session
            self._wavs[run_id] = wav
            task = asyncio.create_task(self._process(run_id, capture, session, wav))
            self._tasks[run_id] = task
            task.add_done_callback(_consume_task_exception)
            self._task_errors_pending.add(run_id)
            return run_id
        except BaseException:
            self._slot_reserved = False
            self._active_run_id = None
            raise

    async def stop(self, run_id: str) -> None:
        capture = self._captures.get(run_id)
        if capture is None:
            return
        capture.stop()
        if self._active_run_id == run_id:
            self._active_run_id = None
            self._slot_reserved = False

    async def cancel(self, run_id: str) -> None:
        task = self._tasks.get(run_id)
        if task is None or task.done() or run_id not in self._cancel_flags:
            return
        self._cancel_flags[run_id] = True
        capture = self._captures.get(run_id)
        if capture is not None:
            capture.cancel()
        if self._active_run_id == run_id:
            self._active_run_id = None
            self._slot_reserved = False
        task_session = self._sessions.get(run_id)
        if task_session is not None:
            task_session.cancel()
        task_wav = self._wavs.get(run_id)
        if task_wav is not None:
            task_wav.close()

    async def cancel_current(self) -> str | None:
        run_id = self._active_run_id
        if run_id is None:
            run_id = next(
                (key for key in reversed(self._tasks) if not self._tasks[key].done()),
                None,
            )
        if run_id is None:
            return None
        task = self._tasks.get(run_id)
        if task is None or task.done():
            return None
        await self.cancel(run_id)
        return run_id if self._cancel_flags.get(run_id) else None

    async def settled(self, run_id: str) -> RunRecord:
        task = self._tasks.get(run_id)
        error: BaseException | None = None
        if task is not None:
            await asyncio.wait({task})
            if run_id in self._task_errors_pending:
                self._task_errors_pending.discard(run_id)
                error = task.exception()
        record = await self._services.history.get(run_id)
        if error is not None:
            raise error
        return record

    async def _process(
        self, run_id: str, capture: CaptureLike, session: SttSession, wav: WavLike
    ) -> None:
        try:
            async for chunk in capture.chunks():
                if self._cancel_flags.get(run_id, False):
                    break
                session.push_audio(array.array("f", chunk.samples))
                wav.write(chunk.samples)
                if not self._cancel_flags.get(run_id, False):
                    self._services.events.publish(
                        {"name": "audio:level", "run_id": run_id, "bands": chunk.bands}
                    )
            if self._cancel_flags.get(run_id, False):
                await self._transition(run_id, RunEvent.CANCEL)
                return
            wav.close()
            record = await self._transition(run_id, RunEvent.STOP)
            if self._cancel_flags.get(run_id, False):
                await self._transition(run_id, RunEvent.CANCEL)
                return
            text = await session.finish()
            if self._cancel_flags.get(run_id, False):
                await self._transition(run_id, RunEvent.CANCEL)
                return
            if text.strip() == "":
                record = await self._services.history.update_run(
                    run_id,
                    expected_version=record.version,
                    original_text="",
                )
                failed = transition(
                    RunState(record.status, record.version), RunEvent.FAIL
                )
                updated = await self._services.history.update_run(
                    run_id,
                    expected_version=record.version,
                    status=failed.status,
                    error_code=ErrorCode.NO_SPEECH_DETECTED.value,
                )
                self._publish_state(updated)
                return
            entries = await self._services.dictionary.entries()
            if self._cancel_flags.get(run_id, False):
                await self._transition(run_id, RunEvent.CANCEL)
                return
            adjusted = apply_dictionary(text, entries)
            record = await self._services.history.update_run(
                run_id,
                expected_version=record.version,
                original_text=text,
                adjusted_text=adjusted,
                output_selection="adjusted",
                cleanup_status=CleanupStatus.OFF,
                audio_duration=wav.frames_written / 16000,
            )
            if self._cancel_flags.get(run_id, False):
                await self._transition(run_id, RunEvent.CANCEL)
                return
            snapshot = self._snapshots[run_id]
            if snapshot is None:
                held = ProtocolResult(
                    ProtocolOutcome.HELD, None, "destination unavailable"
                )
                await self._apply_result(record, held)
                return
            result = await self._services.insertion.attempt(
                run_id,
                adjusted,
                snapshot,
                request_id=self._services.new_id(),
                kind="automatic",
                is_cancelled=lambda: self._cancel_flags.get(run_id, False),
            )
            if result.outcome == ProtocolOutcome.CANCELLED:
                if not self._cancel_flags.get(run_id, False):
                    self._cancel_flags[run_id] = True
            await self._apply_result(record, result)
        except asyncio.CancelledError:
            for cleanup in (session.cancel, capture.cancel, wav.close):
                try:
                    cleanup()
                except Exception:
                    pass
            raise
        except BaseException as error:
            if self._cancel_flags.get(run_id, False):
                try:
                    record = await self._services.history.get(run_id)
                    if not is_terminal(RunState(record.status, record.version)):
                        await self._transition(run_id, RunEvent.CANCEL)
                finally:
                    for cleanup in (session.cancel, capture.cancel, wav.close):
                        try:
                            cleanup()
                        except Exception:
                            pass
                return
            for cleanup in (session.cancel, capture.cancel, wav.close):
                try:
                    cleanup()
                except Exception:
                    pass
            try:
                record = await self._services.history.get(run_id)
                state = RunState(record.status, record.version)
                if not is_terminal(state):
                    failed = transition(state, RunEvent.FAIL)
                    updated = await self._services.history.update_run(
                        run_id,
                        expected_version=record.version,
                        status=failed.status,
                        error_code=_error_code(error).value,
                    )
                    self._publish_state(updated)
            except Exception:
                pass
            raise
        finally:
            self._captures.pop(run_id, None)
            self._snapshots.pop(run_id, None)
            self._cancel_flags.pop(run_id, None)
            self._sessions.pop(run_id, None)
            self._wavs.pop(run_id, None)
            if self._active_run_id == run_id:
                self._active_run_id = None
                self._slot_reserved = False

    async def _transition(self, run_id: str, event: RunEvent) -> RunRecord:
        record = await self._services.history.get(run_id)
        state = transition(RunState(record.status, record.version), event)
        updated = await self._services.history.update_run(
            run_id, expected_version=record.version, status=state.status
        )
        self._publish_state(updated)
        return updated

    async def _apply_result(self, record: RunRecord, result: ProtocolResult) -> None:
        state = RunState(record.status, record.version)
        for event in events_for(result):
            state = transition(state, event)
        if not events_for(result) or state.status == record.status:
            return
        updated = await self._services.history.update_run(
            record.id, expected_version=record.version, status=state.status
        )
        self._publish_state(updated)

    def _publish_state(self, record: RunRecord) -> None:
        self._services.events.publish(
            {
                "name": "run:state",
                "run_id": record.id,
                "version": record.version,
                "status": record.status.value,
            }
        )


def _error_code(error: BaseException) -> ErrorCode:
    if isinstance(error, (ThirdPartyError, WisprError)):
        return error.error_code
    return ErrorCode.STORAGE_ERROR


def _consume_task_exception(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()
