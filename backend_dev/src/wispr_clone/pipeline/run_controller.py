"""Coordinate capture, transcription, and insertion for retained runs."""

from __future__ import annotations

import array
import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from wispr_clone.audio.capture import CaptureChunk
from wispr_clone.contracts.common import ErrorCode, WisprError
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
from wispr_clone.pipeline.state_machine import RunEvent, RunState, transition
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
    capture_destination: Callable[[], asyncio.Future[DestinationSnapshot] | Any]
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
        self._captures: dict[str, CaptureLike] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._snapshots: dict[str, DestinationSnapshot | None] = {}

    @property
    def active_run_id(self) -> str | None:
        return self._active_run_id

    async def start(self, *, start_request_id: str) -> str:
        if self._active_run_id is not None:
            raise WisprError(ErrorCode.DEVICE_LEASE_CONFLICT, "run", "busy")
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
        capture = self._services.new_capture()
        capture.start()
        session = self._services.stt.start_session()
        wav = self._services.new_wav(path)
        self._active_run_id = run_id
        self._captures[run_id] = capture
        self._snapshots[run_id] = snapshot
        # Keep a strong reference until settled so asyncio cannot collect this task.
        self._tasks[run_id] = asyncio.create_task(
            self._process(run_id, capture, session, wav)
        )
        return run_id

    async def stop(self, run_id: str) -> None:
        capture = self._captures.get(run_id)
        if capture is None:
            return
        capture.stop()
        if self._active_run_id == run_id:
            self._active_run_id = None

    async def settled(self, run_id: str) -> RunRecord:
        task = self._tasks.get(run_id)
        if task is not None:
            await task
        return await self._services.history.get(run_id)

    async def _process(
        self, run_id: str, capture: CaptureLike, session: SttSession, wav: WavLike
    ) -> None:
        async for chunk in capture.chunks():
            session.push_audio(array.array("f", chunk.samples))
            wav.write(chunk.samples)
            self._services.events.publish(
                {"name": "audio:level", "run_id": run_id, "bands": chunk.bands}
            )
        wav.close()
        record = await self._transition(run_id, RunEvent.STOP)
        text = await session.finish()
        adjusted = apply_dictionary(text, await self._services.dictionary.entries())
        record = await self._services.history.update_run(
            run_id,
            expected_version=record.version,
            original_text=text,
            adjusted_text=adjusted,
            output_selection="adjusted",
            cleanup_status=CleanupStatus.OFF,
            audio_duration=wav.frames_written / 16000,
        )
        snapshot = self._snapshots[run_id]
        if snapshot is None:
            held = ProtocolResult(ProtocolOutcome.HELD, None, "destination unavailable")
            await self._apply_result(record, held)
            return
        result = await self._services.insertion.attempt(
            run_id,
            adjusted,
            snapshot,
            request_id=self._services.new_id(),
            kind="automatic",
            is_cancelled=lambda: False,
        )
        await self._apply_result(record, result)

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
