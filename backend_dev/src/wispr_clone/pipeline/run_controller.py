"""Coordinate capture, transcription, and insertion for retained runs."""

from __future__ import annotations

import array
import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from wispr_clone.audio.capture import CaptureChunk
from wispr_clone.cleanup.base import CleanupEngine, CleanupRequest
from wispr_clone.cleanup.guard import check as check_cleanup
from wispr_clone.contracts.common import ErrorCode, ThirdPartyError, WisprError
from wispr_clone.contracts.events import EventSink
from wispr_clone.contracts.run import CleanupStatus, RecoveryAction
from wispr_clone.dictionary.apply import apply_dictionary
from wispr_clone.dictionary.repo import DictionaryRepo
from wispr_clone.history.repo import HistoryRepo, RunRecord
from wispr_clone.insertion.destination import DestinationSnapshot
from wispr_clone.pipeline.insertion_protocol import (
    InsertionProtocol,
    ProtocolOutcome,
    ProtocolResult,
    WaitingRun,
)
from wispr_clone.pipeline.state_machine import (
    RunEvent,
    RunState,
    allowed_recovery_actions,
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
    cleanup: CleanupEngine | None = None
    clock: Callable[[], float] = time.time


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
        self._waiting: list[WaitingRun] = []
        self._insertion_gate = asyncio.Lock()
        self._inserting_run_ids: set[str] = set()

    @property
    def active_run_id(self) -> str | None:
        return self._active_run_id

    @property
    def waiting_run_ids(self) -> tuple[str, ...]:
        return tuple(
            entry.run_id
            for entry in sorted(self._waiting, key=lambda item: item.awaiting_since)
        )

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
                    **_terminal_changes(
                        record, RunEvent.FAIL, failed.status, error_code.value
                    ),
                )
                self._publish_updated(updated)
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
        # Cancellation must be visible to a protocol call even while it owns the gate.
        self._cancel_flags[run_id] = True
        self._waiting = [entry for entry in self._waiting if entry.run_id != run_id]
        task = self._tasks.get(run_id)
        if task is None or task.done():
            async with self._insertion_gate:
                try:
                    record = await self._services.history.get(run_id)
                except WisprError:
                    self._cancel_flags.pop(run_id, None)
                    return
                state = RunState(record.status, record.version)
                try:
                    cancelled = transition(state, RunEvent.CANCEL)
                except Exception:
                    self._cancel_flags.pop(run_id, None)
                    return
                updated = await self._services.history.update_run(
                    run_id,
                    expected_version=record.version,
                    **_terminal_changes(record, RunEvent.CANCEL, cancelled.status),
                )
                self._publish_updated(updated)
                self._cancel_flags.pop(run_id, None)
            return
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

    async def recover(
        self,
        run_id: str,
        action: RecoveryAction,
        *,
        expected_version: int,
        acknowledge_uncertain: bool = False,
        destination: DestinationSnapshot | None = None,
    ) -> None:
        record = await self._services.history.get(run_id)
        if record.version != expected_version:
            raise WisprError(ErrorCode.STALE_VERSION, "run", "version")
        state = RunState(record.status, record.version)
        if action not in allowed_recovery_actions(state):
            raise WisprError(ErrorCode.VALIDATION, "run", "action")
        if action == RecoveryAction.COPY:
            raise WisprError(ErrorCode.VALIDATION, "run", "use copy_text")
        if action == RecoveryAction.INSERT:
            # A second recovery request for the same run is already covered by the
            # operation holding the gate; returning avoids waiting on its completion.
            if run_id in self._inserting_run_ids:
                return
            async with self._insertion_gate:
                self._inserting_run_ids.add(run_id)
                try:
                    await self._recover_insert(
                        run_id,
                        record,
                        expected_version,
                        acknowledge_uncertain,
                        destination,
                    )
                finally:
                    self._inserting_run_ids.discard(run_id)
            return
        if action not in {RecoveryAction.RETRY_CLEANUP, RecoveryAction.USE_ORIGINAL}:
            raise WisprError(ErrorCode.VALIDATION, "run", "action")
        event = (
            RunEvent.RETRY_CLEANUP
            if action == RecoveryAction.RETRY_CLEANUP
            else RunEvent.USE_ORIGINAL
        )
        next_state = transition(state, event)
        record = await self._services.history.update_run(
            run_id, expected_version=record.version, status=next_state.status
        )
        self._publish_updated(record)
        self._cancel_flags[run_id] = False
        task = asyncio.create_task(self._recover_task(run_id, action))
        self._tasks[run_id] = task
        task.add_done_callback(_consume_task_exception)
        self._task_errors_pending.add(run_id)

    async def _recover_insert(
        self,
        run_id: str,
        record: RunRecord,
        expected_version: int,
        acknowledge_uncertain: bool,
        destination: DestinationSnapshot | None,
    ) -> None:
        # Re-read under the gate: a preceding insertion may have completed.
        record = await self._services.history.get(run_id)
        attempts = await self._services.history.attempts(run_id)
        outcomes = {attempt.outcome.value for attempt in attempts}
        if "inserted" in outcomes:
            raise WisprError(ErrorCode.VALIDATION, "run", "already inserted")
        if "in_flight" in outcomes:
            raise WisprError(ErrorCode.DUPLICATE_REQUEST, "run", "in flight")
        if "uncertain" in outcomes and not acknowledge_uncertain:
            raise WisprError(ErrorCode.VALIDATION, "run", "acknowledge")
        if record.version != expected_version:
            raise WisprError(ErrorCode.STALE_VERSION, "run", "version")
        state = RunState(record.status, record.version)
        if RecoveryAction.INSERT not in allowed_recovery_actions(state):
            raise WisprError(ErrorCode.VALIDATION, "run", "action")
        stored_snapshot = (
            DestinationSnapshot.from_json(record.destination)
            if record.destination is not None
            else None
        )
        snapshot = destination or stored_snapshot
        if snapshot is None:
            raise WisprError(ErrorCode.DESTINATION_UNVERIFIABLE, "run", "destination")
        waiting_entry = next(
            (entry for entry in self._waiting if entry.run_id == run_id), None
        )
        self._waiting = [entry for entry in self._waiting if entry.run_id != run_id]
        self._cancel_flags[run_id] = False
        text = _selected_text(record)
        result = await self._services.insertion.attempt(
            run_id,
            text,
            snapshot,
            request_id=self._services.new_id(),
            kind="explicit",
            is_cancelled=lambda: self._cancel_flags.get(run_id, False),
        )
        if result.outcome in {
            ProtocolOutcome.INSERTED,
            ProtocolOutcome.UNCERTAIN,
            ProtocolOutcome.FAILED,
        }:
            events = {
                ProtocolOutcome.INSERTED: (
                    RunEvent.DISPATCH_BEGIN_EXPLICIT,
                    RunEvent.INSERTED,
                ),
                ProtocolOutcome.UNCERTAIN: (
                    RunEvent.DISPATCH_BEGIN_EXPLICIT,
                    RunEvent.INSERT_UNCERTAIN,
                ),
                ProtocolOutcome.FAILED: (
                    RunEvent.DISPATCH_BEGIN_EXPLICIT,
                    RunEvent.INSERT_FAILED,
                ),
            }[result.outcome]
            await self._apply_events(record, events)
            self._cancel_flags.pop(run_id, None)
            return
        if waiting_entry is not None and result.outcome != ProtocolOutcome.CANCELLED:
            self._waiting.append(waiting_entry)
        if result.outcome == ProtocolOutcome.AWAITING:
            raise WisprError(
                ErrorCode.DESTINATION_UNVERIFIABLE,
                "run",
                "not in destination",
            )
        if result.outcome == ProtocolOutcome.HELD:
            code = (
                ErrorCode.DESTINATION_CLOSED
                if result.reason == "window closed"
                else ErrorCode.DESTINATION_UNVERIFIABLE
            )
            raise WisprError(code, "run", result.reason)
        if result.outcome == ProtocolOutcome.DUPLICATE:
            raise WisprError(ErrorCode.DUPLICATE_REQUEST, "run", "in flight")
        if result.outcome == ProtocolOutcome.ABANDONED:
            raise WisprError(ErrorCode.RUN_EXPIRED, "run", "expired")
        final_record: RunRecord | None
        try:
            final_record = await self._services.history.get(run_id)
        except WisprError:
            final_record = None
        if final_record is None or is_terminal(
            RunState(final_record.status, final_record.version)
        ):
            self._cancel_flags.pop(run_id, None)

    async def copy_text(self, run_id: str) -> str:
        record = await self._services.history.get(run_id)
        try:
            return _selected_text(record)
        except ValueError:
            if record.original_text is not None:
                return record.original_text
            raise WisprError(ErrorCode.VALIDATION, "run", "no text") from None

    async def delivery_tick(self) -> None:
        if not self._waiting:
            return
        try:
            async with self._insertion_gate:
                if not self._waiting:
                    return
                chosen = min(self._waiting, key=lambda item: item.awaiting_since)
                record = await self._services.history.get(chosen.run_id)
                if record.status.value != "awaiting_destination":
                    self._waiting = [
                        e for e in self._waiting if e.run_id != chosen.run_id
                    ]
                    return
                waiting = tuple(self._waiting)
                delivered = await self._services.insertion.deliver_next(
                    waiting,
                    is_cancelled=lambda rid: (
                        self._cancel_flags.get(rid, False)
                        or not any(entry.run_id == rid for entry in self._waiting)
                    ),
                )
                if delivered is None:
                    return
                run_id, result = delivered
                if result.outcome == ProtocolOutcome.AWAITING:
                    return
                if result.outcome in {
                    ProtocolOutcome.ABANDONED,
                    ProtocolOutcome.DUPLICATE,
                }:
                    self._waiting = [
                        entry for entry in self._waiting if entry.run_id != run_id
                    ]
                    return
                record = await self._services.history.get(run_id)
                await self._apply_events(record, events_for(result), awaiting=True)
                self._waiting = [
                    entry for entry in self._waiting if entry.run_id != run_id
                ]
        except WisprError as error:
            if error.error_code in {ErrorCode.RUN_EXPIRED, ErrorCode.RUN_NOT_FOUND}:
                self._waiting = [e for e in self._waiting if e.run_id != chosen.run_id]
                return
            return
        except Exception:
            # A later app tick retries the retained waiting entry.
            return

    async def _recover_task(self, run_id: str, action: RecoveryAction) -> None:
        try:
            record = await self._services.history.get(run_id)
            if action == RecoveryAction.USE_ORIGINAL:
                record = await self._services.history.update_run(
                    run_id,
                    expected_version=record.version,
                    output_selection="original",
                )
                await self._insert_selected(record, record.original_text or "")
            else:
                await self._cleanup_and_select(record, retry=True)
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            record = await self._services.history.get(run_id)
            state = RunState(record.status, record.version)
            if not is_terminal(state):
                failed = transition(state, RunEvent.FAIL)
                error_code = _error_code(error).value
                changes: dict[str, object] = {
                    "status": failed.status,
                    "error_code": error_code,
                }
                if record.cleanup_status == CleanupStatus.PENDING:
                    changes.update(
                        cleanup_status=CleanupStatus.FAILED,
                        cleanup_reason=error_code,
                    )
                updated = await self._services.history.update_run(
                    run_id, expected_version=record.version, **changes
                )
                self._publish_updated(updated)
            raise
        finally:
            self._cancel_flags.pop(run_id, None)

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
                    **_terminal_changes(
                        record,
                        RunEvent.FAIL,
                        failed.status,
                        ErrorCode.NO_SPEECH_DETECTED.value,
                    ),
                )
                self._publish_updated(updated)
                return
            entries = await self._services.dictionary.entries()
            if self._cancel_flags.get(run_id, False):
                await self._transition(run_id, RunEvent.CANCEL)
                return
            adjusted = apply_dictionary(text, entries)
            cleanup_enabled = record.config.get("cleanup_enabled") is True
            record = await self._services.history.update_run(
                run_id,
                expected_version=record.version,
                original_text=text,
                adjusted_text=adjusted,
                audio_duration=wav.frames_written / 16000,
                **(
                    {"cleanup_status": CleanupStatus.PENDING} if cleanup_enabled else {}
                ),
            )
            if self._cancel_flags.get(run_id, False):
                await self._transition(run_id, RunEvent.CANCEL)
                return
            if not await self._cleanup_and_select(record, retry=False):
                return
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
                        **_terminal_changes(
                            record,
                            RunEvent.FAIL,
                            failed.status,
                            _error_code(error).value,
                        ),
                    )
                    self._publish_updated(updated)
            except Exception:
                pass
            raise
        finally:
            self._captures.pop(run_id, None)
            self._snapshots.pop(run_id, None)
            final_record: RunRecord | None
            try:
                final_record = await self._services.history.get(run_id)
            except WisprError:
                final_record = None
            if final_record is None or is_terminal(
                RunState(final_record.status, final_record.version)
            ):
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
            run_id,
            expected_version=record.version,
            **(
                _terminal_changes(record, event, state.status)
                if event == RunEvent.CANCEL
                else {"status": state.status}
            ),
        )
        self._publish_updated(updated)
        return updated

    async def _cleanup_and_select(self, record: RunRecord, *, retry: bool) -> bool:
        run_id = record.id
        adjusted = record.adjusted_text or ""
        config = record.config
        enabled = config.get("cleanup_enabled") is True
        if not enabled and not retry:
            record = await self._services.history.update_run(
                run_id,
                expected_version=record.version,
                output_selection="adjusted",
                cleanup_status=CleanupStatus.OFF,
            )
            if self._cancel_flags.get(run_id, False):
                await self._transition(run_id, RunEvent.CANCEL)
                return False
            await self._insert_selected(record, adjusted)
            return True
        if retry or record.cleanup_status != CleanupStatus.PENDING:
            record = await self._services.history.update_run(
                run_id,
                expected_version=record.version,
                cleanup_status=CleanupStatus.PENDING,
                cleanup_reason=None,
                cleaned_text=None,
                output_selection=None,
            )
        entries = await self._services.dictionary.entries()
        if self._cancel_flags.get(run_id, False):
            await self._transition(run_id, RunEvent.CANCEL)
            return False
        engine = self._services.cleanup
        instructions = config.get("cleanup_instructions", "")
        if not isinstance(instructions, str):
            instructions = ""
        try:
            if engine is None:
                raise RuntimeError
            cleaned = await engine.clean(
                CleanupRequest(
                    text=adjusted,
                    glossary=tuple(entry.spelling for entry in entries),
                    instructions=instructions,
                )
            )
        except (ThirdPartyError, WisprError) as error:
            if self._cancel_flags.get(run_id, False):
                await self._transition(run_id, RunEvent.CANCEL)
                return False
            return await self._cleanup_failure(
                record, CleanupStatus.FAILED, error.error_code.value
            )
        except Exception:
            if self._cancel_flags.get(run_id, False):
                await self._transition(run_id, RunEvent.CANCEL)
                return False
            return await self._cleanup_failure(
                record, CleanupStatus.FAILED, "cleanup_unavailable"
            )
        if self._cancel_flags.get(run_id, False):
            await self._transition(run_id, RunEvent.CANCEL)
            return False
        verdict = check_cleanup(adjusted, cleaned)
        if not verdict.accepted:
            return await self._cleanup_failure(
                record, CleanupStatus.REJECTED, ",".join(sorted(verdict.reasons))
            )
        record = await self._services.history.update_run(
            run_id,
            expected_version=record.version,
            cleaned_text=cleaned,
            output_selection="cleaned",
            cleanup_status=CleanupStatus.OK,
            cleanup_reason=None,
        )
        if self._cancel_flags.get(run_id, False):
            await self._transition(run_id, RunEvent.CANCEL)
            return False
        await self._insert_selected(record, cleaned)
        return True

    async def _cleanup_failure(
        self, record: RunRecord, status: CleanupStatus, reason: str
    ) -> bool:
        run_id = record.id
        if self._cancel_flags.get(run_id, False):
            await self._transition(run_id, RunEvent.CANCEL)
            return False
        failed = transition(
            RunState(record.status, record.version), RunEvent.CLEANUP_FAILED
        )
        updated = await self._services.history.update_run(
            run_id,
            expected_version=record.version,
            status=failed.status,
            cleanup_status=status,
            cleanup_reason=reason,
            cleaned_text=None,
            output_selection=None,
        )
        self._publish_updated(updated)
        return False

    async def _insert_selected(self, record: RunRecord, text: str) -> None:
        async with self._insertion_gate:
            await self._insert_selected_gated(record, text)

    async def _insert_selected_gated(self, record: RunRecord, text: str) -> None:
        run_id = record.id
        if self._cancel_flags.get(run_id, False):
            await self._transition(run_id, RunEvent.CANCEL)
            return
        snapshot_json = record.destination
        if snapshot_json is None:
            result = ProtocolResult(
                ProtocolOutcome.HELD, None, "destination unavailable"
            )
        else:
            snapshot = DestinationSnapshot.from_json(snapshot_json)
            result = await self._services.insertion.attempt(
                run_id,
                text,
                snapshot,
                request_id=self._services.new_id(),
                kind="automatic",
                is_cancelled=lambda: self._cancel_flags.get(run_id, False),
            )
        if result.outcome == ProtocolOutcome.CANCELLED:
            self._cancel_flags[run_id] = True
        await self._apply_result(record, result)

    async def _apply_result(self, record: RunRecord, result: ProtocolResult) -> None:
        await self._apply_events(record, events_for(result))

    async def _apply_events(
        self,
        record: RunRecord,
        events: tuple[RunEvent, ...],
        *,
        awaiting: bool = False,
    ) -> None:
        state = RunState(record.status, record.version)
        for event in events:
            state = transition(state, event)
        if not events or state.status == record.status:
            return
        changes: dict[str, object] = {"status": state.status}
        if state.status.value == "awaiting_destination":
            awaiting_since = self._services.clock()
            changes["awaiting_since"] = awaiting_since
        if events[-1] == RunEvent.CANCEL:
            changes.update(_terminal_changes(record, RunEvent.CANCEL, state.status))
        if events[-1] == RunEvent.INSERT_FAILED:
            changes["error_code"] = ErrorCode.INSERTION_FAILED.value
        updated = await self._services.history.update_run(
            record.id,
            expected_version=record.version,
            **changes,
        )
        self._publish_updated(updated)
        status = updated.status.value
        if status == "awaiting_destination" and awaiting:
            return
        if status == "awaiting_destination":
            timestamp = updated.awaiting_since or self._services.clock()
            config = updated.config
            idle_seconds = config.get("idle_jump_seconds")
            wait_limit = config.get("destination_wait_limit_seconds")
            idle_ms = (
                int(float(idle_seconds) * 1000)
                if isinstance(idle_seconds, (int, float))
                else None
            )
            wait_s = float(wait_limit) if isinstance(wait_limit, (int, float)) else None
            snapshot = self._snapshots.get(record.id)
            if snapshot is None and updated.destination is not None:
                snapshot = DestinationSnapshot.from_json(updated.destination)
            if snapshot is not None:
                self._waiting.append(
                    WaitingRun(
                        record.id,
                        _selected_text(updated),
                        snapshot,
                        self._services.new_id(),
                        timestamp,
                        idle_ms,
                        wait_s,
                    )
                )

    def _publish_recovery(self, record: RunRecord) -> None:
        state = RunState(record.status, record.version)
        self._services.events.publish(
            {
                "name": "run:recovery",
                "run_id": record.id,
                "version": record.version,
                "status": record.status.value,
                "actions": sorted(
                    action.value for action in allowed_recovery_actions(state)
                ),
            }
        )

    def _publish_updated(self, record: RunRecord) -> None:
        self._publish_state(record)
        if record.status.value in {
            "awaiting_destination",
            "held",
            "error",
            "uncertain",
            "awaiting_cleanup_choice",
        }:
            self._publish_recovery(record)

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


def _terminal_changes(
    record: RunRecord,
    event: RunEvent,
    status: object,
    error_code: str | None = None,
) -> dict[str, object]:
    changes: dict[str, object] = {"status": status}
    if error_code is not None:
        changes["error_code"] = error_code
    if record.cleanup_status == CleanupStatus.PENDING:
        changes.update(
            cleanup_status=CleanupStatus.FAILED,
            cleanup_reason="cancelled" if event == RunEvent.CANCEL else error_code,
        )
    return changes


def _consume_task_exception(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()


def _selected_text(record: RunRecord) -> str:
    selection = record.output_selection
    if selection == "cleaned" and record.cleaned_text is not None:
        return record.cleaned_text
    if selection == "adjusted" and record.adjusted_text is not None:
        return record.adjusted_text
    if selection == "original" and record.original_text is not None:
        return record.original_text
    raise ValueError("no selected text")
