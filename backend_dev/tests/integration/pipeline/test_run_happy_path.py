"""WO-M3a run integration across hotkeys, audio, STT, storage and insertion."""

from __future__ import annotations

import asyncio
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
from wispr_clone.contracts.run import CleanupStatus, RunStatus
from wispr_clone.contracts.shortcuts import KeyBinding
from wispr_clone.dictionary.apply import DictionaryEntry
from wispr_clone.dictionary.repo import DictionaryRepo
from wispr_clone.history.repo import HistoryRepo
from wispr_clone.hotkeys.hotkey_service import HotkeyService, KeyAction
from wispr_clone.insertion.destination import DestinationSnapshot, capture
from wispr_clone.pipeline.insertion_protocol import InsertionProtocol
from wispr_clone.pipeline.run_controller import RunController, RunServices
from wispr_clone.storage import Database, Migration
from wispr_clone.storage.migrations import (
    m001_base,
    m002_settings,
    m003_dictionary,
    m004_history,
)

RAW = "private open whisper phrase"
ADJUSTED = "private OpenWhispr phrase"


async def _inline(call: Callable[[], Any]) -> Any:
    return call()


class TrackingWav(WavWriter):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.closed = False

    def close(self) -> None:
        super().close()
        self.closed = True


class TrackingEvents(FakeEventSink):
    def __init__(self, writers: list[TrackingWav]) -> None:
        super().__init__()
        self.writers = writers
        self.processing_wav_closed: list[bool] = []

    def publish(self, event: Any) -> None:
        if event["name"] == "run:state" and event["status"] == "processing":
            self.processing_wav_closed.append(
                bool(self.writers and self.writers[0].closed)
            )
        super().publish(event)


Scenario = tuple[
    RunController,
    FakeCapture,
    FakeSttEngine,
    TrackingEvents,
    FakeWin32Api,
    FakeUiaApi,
    list[TrackingWav],
    HistoryRepo,
]


@asynccontextmanager
async def scenario(
    path: Path, *, destination_fails: bool = False
) -> AsyncIterator[Scenario]:
    migrations = [
        Migration(module.VERSION, module.NAME, module.apply)
        for module in (m001_base, m002_settings, m003_dictionary, m004_history)
    ]
    async with Database(path / "runs.db", migrations) as db:
        clock = FakeClock(100)
        writers: list[TrackingWav] = []
        events = TrackingEvents(writers)
        history = HistoryRepo(db, clock=clock.now, audio_dir=path, events=events)
        dictionary = DictionaryRepo(db, clock=clock.now)
        await dictionary.add(DictionaryEntry("OpenWhispr", ("open whisper",)))
        win, uia = FakeWin32Api(), FakeUiaApi()
        snapshot = capture(win, uia)
        win.calls.clear()
        uia.calls.clear()
        win.on_send = lambda: uia.texts.__setitem__((1, 2), "before" + ADJUSTED)
        stt = FakeSttEngine(RAW)
        fake_capture = FakeCapture(
            (CaptureChunk(np.full(1280, 0.25, dtype=np.float32), [0.2, 0.4]),)
        )
        sequence = iter(("run-1", "request-1", "run-2", "request-2"))
        protocol = InsertionProtocol(
            history,
            win,
            uia,
            offload=_inline,
            clock=clock.now,
            new_id=lambda: "attempt-1",
            paste_settle_s=0.0,
        )

        async def destination() -> DestinationSnapshot:
            if destination_fails:
                raise WisprError(ErrorCode.DESTINATION_UNVERIFIABLE, "test", "missing")
            return snapshot

        def new_wav(wav_path: Path) -> TrackingWav:
            writer = TrackingWav(wav_path)
            writers.append(writer)
            return writer

        controller = RunController(
            RunServices(
                history=history,
                dictionary=dictionary,
                stt=stt,
                insertion=protocol,
                events=events,
                capture_destination=destination,
                new_capture=lambda: fake_capture,
                new_wav=new_wav,
                new_id=lambda: next(sequence),
                audio_dir=path,
                config_snapshot=lambda: {"cleanup_enabled": False},
            )
        )
        yield controller, fake_capture, stt, events, win, uia, writers, history


@pytest.mark.asyncio
async def test_T_RUN_001_hotkey_happy_path_and_T_RUN_001b_persistence(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as (
        controller,
        audio,
        stt,
        events,
        win,
        uia,
        writers,
        history,
    ):
        loop = asyncio.get_running_loop()
        started: asyncio.Future[str] = loop.create_future()
        stopped: asyncio.Future[None] = loop.create_future()

        async def do_start() -> None:
            try:
                started.set_result(await controller.start(start_request_id="start-1"))
            except Exception as error:
                started.set_exception(error)

        async def do_stop() -> None:
            try:
                await controller.stop(await started)
                stopped.set_result(None)
            except Exception as error:
                stopped.set_exception(error)

        hotkey = HotkeyService(
            dictation=KeyBinding(frozenset({"ctrl"}), "space"),
            cancel=KeyBinding(frozenset(), "escape"),
            mode="hold",
            on_start=lambda: asyncio.create_task(do_start()),
            on_stop=lambda: asyncio.create_task(do_stop()),
            on_cancel=lambda: None,
            post=loop.call_soon_threadsafe,
        )
        hotkey.handle(KeyAction.DOWN, "ctrl")
        hotkey.handle(KeyAction.DOWN, "space")
        run_id = await started
        assert run_id == "run-1"
        assert controller.active_run_id == run_id
        assert (await history.get(run_id)).status == RunStatus.RECORDING
        await audio.pumped.wait()
        hotkey.handle(KeyAction.UP, "space")
        await stopped
        assert controller.active_run_id is None
        record = await controller.settled(run_id)

        assert record.status == RunStatus.DONE
        assert record.original_text == RAW
        assert record.adjusted_text == ADJUSTED
        assert record.output_selection == "adjusted"
        assert record.cleanup_status == CleanupStatus.OFF
        assert record.audio_duration == pytest.approx(1280 / 16000)
        assert record.audio_path == str(tmp_path / "run-1.wav")
        assert writers[0].closed and events.processing_wav_closed == [True]
        assert audio.started and audio.stopped and not audio.cancelled
        assert len(stt.sessions) == 1 and stt.sessions[0].finished
        assert len(stt.sessions[0].pushed) == 1
        assert stt.sessions[0].pushed[0].typecode == "f"
        assert list(stt.sessions[0].pushed[0]) == pytest.approx([0.25] * 1280)
        states = events.by_name("run:state")
        assert [event["status"] for event in states] == [
            "recording",
            "processing",
            "done",
        ]
        versions = [event["version"] for event in states]
        assert versions[0] == 1 and versions == sorted(set(versions))
        assert all(event["run_id"] == run_id for event in states)
        levels = events.by_name("audio:level")
        assert len(levels) == 1 and levels[0]["bands"] == [0.2, 0.4]
        assert events.events.index(levels[0]) < events.events.index(states[1])
        assert sum(name == "send_inputs" for name, _, _ in win.calls) == 1
        assert uia.texts[(1, 2)] == "before" + ADJUSTED
        assert len(await history.attempts(run_id)) == 1


@pytest.mark.asyncio
async def test_T_RUN_001d_unverifiable_destination_holds_without_dispatch(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path, destination_fails=True) as (
        controller,
        _,
        _,
        events,
        win,
        _,
        _,
        history,
    ):
        run_id = await controller.start(start_request_id="start-1")
        await controller.stop(run_id)
        record = await controller.settled(run_id)
        assert record.status == RunStatus.HELD
        assert record.destination is None
        assert [event["status"] for event in events.by_name("run:state")] == [
            "recording",
            "processing",
            "held",
        ]
        assert not await history.attempts(run_id)
        assert sum(name == "send_inputs" for name, _, _ in win.calls) == 0


@pytest.mark.asyncio
async def test_T_RUN_001e_second_start_conflicts_without_harming_first(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as (controller, audio, _, _, _, _, _, history):
        run_id = await controller.start(start_request_id="start-1")
        with pytest.raises(WisprError) as raised:
            await controller.start(start_request_id="start-2")
        assert raised.value.error_code == ErrorCode.DEVICE_LEASE_CONFLICT
        assert controller.active_run_id == run_id
        assert (await history.get(run_id)).status == RunStatus.RECORDING
        assert not audio.stopped
        await controller.stop(run_id)
        assert (await controller.settled(run_id)).status == RunStatus.DONE


@pytest.mark.asyncio
async def test_T_RUN_001f_private_text_is_absent_from_logs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async with scenario(tmp_path) as (controller, _, _, _, _, _, _, _):
        with caplog.at_level(logging.DEBUG):
            run_id = await controller.start(start_request_id="start-1")
            await controller.stop(run_id)
            await controller.settled(run_id)
        assert RAW not in caplog.text
        assert ADJUSTED not in caplog.text
        assert "PRIVATE TITLE" not in caplog.text
