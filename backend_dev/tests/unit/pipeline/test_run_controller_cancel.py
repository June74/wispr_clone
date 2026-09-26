"""WO-M3b cancellation and adjacent run lifecycle regressions."""

from __future__ import annotations

import asyncio
import gc
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fakes.audio import FakeCapture
from fakes.clock import FakeClock
from fakes.events import FakeEventSink
from fakes.insertion import FakeUiaApi, FakeWin32Api
from fakes.stt import FakeSttEngine

from wispr_clone.audio.capture import CaptureChunk
from wispr_clone.audio.wav_writer import WavWriter
from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.contracts.run import AttemptOutcome, RunStatus
from wispr_clone.dictionary.repo import DictionaryRepo
from wispr_clone.history.repo import HistoryRepo
from wispr_clone.insertion.destination import capture
from wispr_clone.pipeline.insertion_protocol import InsertionProtocol
from wispr_clone.pipeline.run_controller import RunController, RunServices
from wispr_clone.storage import Database, Migration
from wispr_clone.storage.migrations import (
    m001_base,
    m002_settings,
    m003_dictionary,
    m004_history,
)


class TrackedWav(WavWriter):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.closed = False

    def close(self) -> None:
        super().close()
        self.closed = True


class Rig:
    def __init__(
        self,
        controller: RunController,
        history: HistoryRepo,
        events: FakeEventSink,
        clock: FakeClock,
        stt: FakeSttEngine,
        win: FakeWin32Api,
        captures: list[FakeCapture],
        wavs: list[TrackedWav],
    ) -> None:
        self.controller = controller
        self.history = history
        self.events = events
        self.clock = clock
        self.stt = stt
        self.win = win
        self.captures = captures
        self.wavs = wavs

    def statuses(self, run_id: str) -> list[str]:
        return [
            str(event["status"])
            for event in self.events.by_name("run:state")
            if event["run_id"] == run_id
        ]

    def sends(self) -> int:
        return sum(name == "send_inputs" for name, _, _ in self.win.calls)


@asynccontextmanager
async def scenario(
    path: Path,
    *,
    text: str = "spoken words",
    offload: Callable[[Callable[[], Any]], Any] | None = None,
) -> AsyncIterator[Rig]:
    migrations = [
        Migration(module.VERSION, module.NAME, module.apply)
        for module in (m001_base, m002_settings, m003_dictionary, m004_history)
    ]
    async with Database(path / "runs.db", migrations) as db:
        clock = FakeClock(100)
        events = FakeEventSink()
        history = HistoryRepo(db, clock=clock.now, audio_dir=path, events=events)
        stt = FakeSttEngine(text)
        win, uia = FakeWin32Api(), FakeUiaApi()
        snapshot = capture(win, uia)
        win.calls.clear()
        uia.calls.clear()
        win.on_send = lambda: uia.texts.__setitem__((1, 2), "before" + text)
        captures: list[FakeCapture] = []
        wavs: list[TrackedWav] = []
        ids = iter(f"id-{number}" for number in range(20))

        async def inline(call: Callable[[], Any]) -> Any:
            return call()

        async def destination() -> Any:
            return snapshot

        def new_capture() -> FakeCapture:
            result = FakeCapture()
            captures.append(result)
            return result

        def new_wav(wav_path: Path) -> TrackedWav:
            result = TrackedWav(wav_path)
            wavs.append(result)
            return result

        protocol = InsertionProtocol(
            history,
            win,
            uia,
            offload=offload or inline,
            clock=clock.now,
            new_id=lambda: "attempt-1",
            paste_settle_s=0.0,
        )
        controller = RunController(
            RunServices(
                history=history,
                dictionary=DictionaryRepo(db, clock=clock.now),
                stt=stt,
                insertion=protocol,
                events=events,
                capture_destination=destination,
                new_capture=new_capture,
                new_wav=new_wav,
                new_id=lambda: next(ids),
                audio_dir=path,
                config_snapshot=lambda: {},
            )
        )
        yield Rig(controller, history, events, clock, stt, win, captures, wavs)


@pytest.mark.asyncio
async def test_T_RUN_002_cancel_recording_releases_slot_and_ignores_audio(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as rig:
        run_id = await rig.controller.start(start_request_id="one")
        rig.captures[0].queue(CaptureChunk(np.zeros(1280, dtype=np.float32), [0.0]))
        await rig.captures[0].pumped.wait()
        await rig.controller.cancel(run_id)
        assert rig.controller.active_run_id is None
        levels_after_cancel = len(rig.events.by_name("audio:level"))
        result = await rig.controller.settled(run_id)
        assert result.status == RunStatus.CANCELLED
        assert rig.statuses(run_id) == ["recording", "cancelled"]
        assert rig.captures[0].cancelled and rig.stt.sessions[0].cancelled
        assert rig.wavs[0].closed and rig.sends() == 0
        assert len(rig.events.by_name("audio:level")) == levels_after_cancel
        second = await rig.controller.start(start_request_id="two")
        await rig.controller.stop(second)
        assert (await rig.controller.settled(second)).status == RunStatus.DONE


@pytest.mark.asyncio
async def test_T_RUN_010_cancel_after_stop_discards_queued_audio(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as rig:
        run_id = await rig.controller.start(start_request_id="one")
        rig.captures[0].queue(CaptureChunk(np.zeros(1280, dtype=np.float32), [0.0]))
        await rig.controller.stop(run_id)
        await rig.controller.cancel(run_id)
        assert rig.captures[0].cancelled
        assert rig.captures[0].queued == []
        assert (await rig.controller.settled(run_id)).status == RunStatus.CANCELLED
        assert rig.statuses(run_id) == ["recording", "cancelled"]
        assert rig.events.by_name("audio:level") == []


@pytest.mark.asyncio
async def test_T_RUN_011_cancel_during_transcript_write_keeps_text(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as rig:
        run_id = await rig.controller.start(start_request_id="one")
        entered, release = asyncio.Event(), asyncio.Event()
        original_update = rig.history.update_run

        async def gated_update(*args: Any, **kwargs: Any) -> Any:
            if "original_text" in kwargs:
                entered.set()
                await release.wait()
            return await original_update(*args, **kwargs)

        rig.history.update_run = gated_update  # type: ignore[method-assign]
        await rig.controller.stop(run_id)
        await entered.wait()
        await rig.controller.cancel(run_id)
        release.set()
        record = await rig.controller.settled(run_id)
        assert record.status == RunStatus.CANCELLED
        assert record.original_text == "spoken words"
        assert record.adjusted_text == "spoken words"
        assert rig.sends() == 0


@pytest.mark.asyncio
async def test_T_RUN_012_double_cancel_and_old_task_preserve_new_run(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as rig:
        old = await rig.controller.start(start_request_id="one")
        old_session = rig.stt.sessions[0]
        entered, release = asyncio.Event(), asyncio.Event()

        async def blocked_finish() -> str:
            entered.set()
            await release.wait()
            return "late text"

        old_session.finish = blocked_finish  # type: ignore[method-assign]
        await rig.controller.stop(old)
        await entered.wait()
        await rig.controller.cancel(old)
        await rig.controller.cancel(old)
        new = await rig.controller.start(start_request_id="two")
        assert rig.controller.active_run_id == new
        release.set()
        assert (await rig.controller.settled(old)).status == RunStatus.CANCELLED
        assert rig.controller.active_run_id == new
        assert not rig.captures[1].cancelled
        assert not rig.stt.sessions[1].cancelled
        assert rig.statuses(old) == ["recording", "processing", "cancelled"]
        await rig.controller.stop(new)
        assert (await rig.controller.settled(new)).status == RunStatus.DONE


@pytest.mark.asyncio
@pytest.mark.parametrize("late_text", [False, True])
async def test_T_RUN_003_cancel_while_finish_pending_discards_text(
    tmp_path: Path, late_text: bool
) -> None:
    async with scenario(tmp_path) as rig:
        entered, release = asyncio.Event(), asyncio.Event()
        session = None
        run_id = await rig.controller.start(start_request_id="one")
        session = rig.stt.sessions[0]

        async def blocked_finish() -> str:
            entered.set()
            await release.wait()
            session.finished = True
            if late_text:
                return "private late text"
            raise WisprError(ErrorCode.STT_STREAM_CLOSED, "stt", "closed")

        session.finish = blocked_finish  # type: ignore[method-assign]
        await rig.controller.stop(run_id)
        await entered.wait()
        await rig.controller.cancel(run_id)
        release.set()
        record = await rig.controller.settled(run_id)
        assert record.status == RunStatus.CANCELLED
        assert record.original_text is None and record.adjusted_text is None
        assert rig.sends() == 0 and session.cancelled
        assert rig.statuses(run_id) == ["recording", "processing", "cancelled"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "boundary,expected", [(2, RunStatus.CANCELLED), (3, RunStatus.DONE)]
)
async def test_T_RUN_003b_cancel_at_insertion_dispatch_boundary(
    tmp_path: Path, boundary: int, expected: RunStatus
) -> None:
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def gated_offload(operation: Callable[[], Any]) -> Any:
        nonlocal calls
        calls += 1
        result = operation()
        if calls == boundary:
            entered.set()
            await release.wait()
        return result

    async with scenario(tmp_path, offload=gated_offload) as rig:
        run_id = await rig.controller.start(start_request_id="one")
        await rig.controller.stop(run_id)
        await entered.wait()
        await rig.controller.cancel(run_id)
        release.set()
        record = await rig.controller.settled(run_id)
        assert record.status == expected
        attempts = await rig.history.attempts(run_id)
        assert len(attempts) == 1
        assert attempts[0].outcome == (
            AttemptOutcome.CANCELLED if boundary == 2 else AttemptOutcome.INSERTED
        )
        assert rig.sends() == (0 if boundary == 2 else 1)


@pytest.mark.asyncio
async def test_T_RUN_005_overlapping_start_preserves_first_run(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        run_id = await rig.controller.start(start_request_id="one")
        with pytest.raises(WisprError) as raised:
            await rig.controller.start(start_request_id="two")
        assert raised.value.error_code == ErrorCode.DEVICE_LEASE_CONFLICT
        assert rig.controller.active_run_id == run_id
        await rig.controller.stop(run_id)
        assert (await rig.controller.settled(run_id)).status == RunStatus.DONE
        assert len(rig.captures) == 1 and rig.sends() == 1


@pytest.mark.asyncio
async def test_T_RUN_006_ten_minutes_silence_does_not_stop(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        run_id = await rig.controller.start(start_request_id="one")
        for _ in range(600):
            rig.captures[0].queue(CaptureChunk(np.zeros(1280, dtype=np.float32), [0.0]))
            rig.clock.advance(1)
        await rig.captures[0].pumped.wait()
        await asyncio.sleep(0)
        assert rig.controller.active_run_id == run_id
        assert (await rig.history.get(run_id)).status == RunStatus.RECORDING
        assert rig.statuses(run_id) == ["recording"]
        await rig.controller.stop(run_id)
        assert (await rig.controller.settled(run_id)).status == RunStatus.DONE


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["", " \t\n"])
async def test_T_RUN_007_empty_transcript_fails_without_dispatch(
    tmp_path: Path, text: str
) -> None:
    async with scenario(tmp_path, text=text) as rig:
        run_id = await rig.controller.start(start_request_id="one")
        await rig.controller.stop(run_id)
        record = await rig.controller.settled(run_id)
        assert record.status == RunStatus.ERROR
        assert record.error_code == ErrorCode.NO_SPEECH_DETECTED.value
        assert record.original_text is None
        assert rig.sends() == 0


@pytest.mark.asyncio
async def test_T_RUN_008_cancel_unknown_finished_and_current(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        await rig.controller.cancel("unknown")
        assert await rig.controller.cancel_current() is None
        first = await rig.controller.start(start_request_id="one")
        assert await rig.controller.cancel_current() == first
        assert (await rig.controller.settled(first)).status == RunStatus.CANCELLED
        second = await rig.controller.start(start_request_id="two")
        await rig.controller.stop(second)
        assert await rig.controller.cancel_current() == second
        assert (await rig.controller.settled(second)).status == RunStatus.CANCELLED
        count = len(rig.events.events)
        await rig.controller.cancel(first)
        await rig.controller.cancel(second)
        assert await rig.controller.cancel_current() is None
        assert len(rig.events.events) == count
        third = await rig.controller.start(start_request_id="three")
        await rig.controller.stop(third)
        assert (await rig.controller.settled(third)).status == RunStatus.DONE
        count = len(rig.events.events)
        await rig.controller.cancel(third)
        assert await rig.controller.cancel_current() is None
        assert len(rig.events.events) == count


@pytest.mark.asyncio
async def test_T_RUN_009a_late_stt_callback_changes_nothing(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        run_id = await rig.controller.start(start_request_id="one")
        session = rig.stt.sessions[0]
        await rig.controller.cancel(run_id)
        record = await rig.controller.settled(run_id)
        before = list(rig.events.events)
        session.emit_text("private late text", "private tentative")
        assert record.status == RunStatus.CANCELLED
        assert record.original_text is None and record.adjusted_text is None
        assert await rig.history.get(run_id) == record
        assert rig.events.events == before


@pytest.mark.asyncio
async def test_T_RUN_009b_shutdown_cancellation_cleans_without_status_write(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as rig:
        run_id = await rig.controller.start(start_request_id="one")
        task = rig.controller._tasks[run_id]  # shutdown targets the owned task
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (await rig.history.get(run_id)).status == RunStatus.RECORDING
        assert rig.captures[0].cancelled and rig.stt.sessions[0].cancelled
        assert rig.wavs[0].closed and rig.controller.active_run_id is None


@pytest.mark.asyncio
async def test_T_RUN_009c_unobserved_task_error_is_retrieved(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async with scenario(tmp_path) as rig:
        run_id = await rig.controller.start(start_request_id="one")

        async def failing_finish() -> str:
            raise WisprError(ErrorCode.STT_UNAVAILABLE, "stt", "failed")

        rig.stt.sessions[0].finish = failing_finish  # type: ignore[method-assign]
        with caplog.at_level(logging.ERROR, logger="asyncio"):
            await rig.controller.stop(run_id)
            for _ in range(20):
                if (await rig.history.get(run_id)).status == RunStatus.ERROR:
                    break
                await asyncio.sleep(0)
            assert (await rig.history.get(run_id)).status == RunStatus.ERROR
            rig.controller._tasks.pop(run_id)  # drop owner without calling settled
            gc.collect()
            await asyncio.sleep(0)
        assert "Task exception was never retrieved" not in caplog.text
