"""WO-M3a recording-slot and startup failure regressions."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
import pytest
from fakes.audio import FakeCapture
from fakes.clock import FakeClock
from fakes.events import FakeEventSink
from fakes.insertion import FakeUiaApi, FakeWin32Api
from fakes.stt import FakeSttEngine, FakeSttSession

from wispr_clone.audio.capture import CaptureChunk
from wispr_clone.audio.wav_writer import WavWriter
from wispr_clone.contracts.common import ErrorCode, ThirdPartyError, WisprError
from wispr_clone.contracts.run import RunStatus
from wispr_clone.dictionary.repo import DictionaryRepo
from wispr_clone.history.repo import HistoryRepo
from wispr_clone.insertion.destination import DestinationSnapshot
from wispr_clone.pipeline.insertion_protocol import InsertionProtocol
from wispr_clone.pipeline.run_controller import RunController, RunServices
from wispr_clone.storage import Database, Migration
from wispr_clone.storage.migrations import (
    m001_base,
    m002_settings,
    m003_dictionary,
    m004_history,
)
from wispr_clone.stt.base import TextCallback


async def _inline(call: Callable[[], Any]) -> Any:
    return call()


@asynccontextmanager
async def scenario(
    path: Path,
    *,
    new_capture: Callable[[], FakeCapture],
    stt: FakeSttEngine | None = None,
    destination_entered: asyncio.Event | None = None,
    destination_release: asyncio.Event | None = None,
    new_wav: Callable[[Path], WavWriter] = WavWriter,
) -> AsyncIterator[tuple[RunController, HistoryRepo]]:
    migrations = [
        Migration(module.VERSION, module.NAME, module.apply)
        for module in (m001_base, m002_settings, m003_dictionary, m004_history)
    ]
    async with Database(path / "runs.db", migrations) as db:
        clock = FakeClock(100)
        events = FakeEventSink()
        history = HistoryRepo(db, clock=clock.now, audio_dir=path, events=events)
        protocol = InsertionProtocol(
            history,
            FakeWin32Api(),
            FakeUiaApi(),
            offload=_inline,
            clock=clock.now,
            new_id=lambda: "attempt-1",
            paste_settle_s=0.0,
        )
        ids = iter(("run-1", "run-2", "run-3"))

        async def destination() -> DestinationSnapshot:
            if destination_entered is not None:
                destination_entered.set()
            if destination_release is not None:
                await destination_release.wait()
            raise WisprError(ErrorCode.DESTINATION_UNVERIFIABLE, "test", "missing")

        controller = RunController(
            RunServices(
                history=history,
                dictionary=DictionaryRepo(db, clock=clock.now),
                stt=stt or FakeSttEngine("text"),
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
        yield controller, history


@pytest.mark.asyncio
async def test_T_RUN_001g_concurrent_starts_reserve_one_capture(tmp_path: Path) -> None:
    captures: list[FakeCapture] = []
    entered, release = asyncio.Event(), asyncio.Event()

    def new_capture() -> FakeCapture:
        capture = FakeCapture()
        captures.append(capture)
        return capture

    async with scenario(
        tmp_path,
        new_capture=new_capture,
        destination_entered=entered,
        destination_release=release,
    ) as (controller, _):
        first = asyncio.create_task(controller.start(start_request_id="start-1"))
        await entered.wait()
        second = asyncio.create_task(controller.start(start_request_id="start-2"))
        await asyncio.sleep(0)
        release.set()
        results = await asyncio.gather(first, second, return_exceptions=True)
        try:
            run_ids = [result for result in results if isinstance(result, str)]
            conflicts = [
                result
                for result in results
                if isinstance(result, WisprError)
                and result.error_code == ErrorCode.DEVICE_LEASE_CONFLICT
            ]
            assert len(run_ids) == 1
            assert len(conflicts) == 1
            assert sum(capture.started for capture in captures) == 1
        finally:
            for result in results:
                if isinstance(result, str):
                    await controller.stop(result)
                    await controller.settled(result)


class FailingStartStt(FakeSttEngine):
    def __init__(self) -> None:
        super().__init__("text")
        self.fail_start = True

    def start_session(self, on_text: TextCallback | None = None) -> FakeSttSession:
        if self.fail_start:
            raise ThirdPartyError(
                "stt", "start_session", "failed", ErrorCode.STT_UNAVAILABLE
            )
        return super().start_session(on_text)


@pytest.mark.asyncio
async def test_T_RUN_001h_failed_stt_start_cancels_and_releases_slot(
    tmp_path: Path,
) -> None:
    stt = FailingStartStt()
    captures: list[FakeCapture] = []

    def new_capture() -> FakeCapture:
        capture = FakeCapture()
        captures.append(capture)
        return capture

    async with scenario(tmp_path, new_capture=new_capture, stt=stt) as (
        controller,
        history,
    ):
        with pytest.raises(ThirdPartyError) as raised:
            await controller.start(start_request_id="start-1")
        assert raised.value.error_code == ErrorCode.STT_UNAVAILABLE
        assert captures[0].started and captures[0].cancelled
        failed = await history.get("run-1")
        assert failed.status == RunStatus.ERROR
        assert failed.error_code == ErrorCode.STT_UNAVAILABLE.value
        assert controller.active_run_id is None

        stt.fail_start = False
        run_id = await controller.start(start_request_id="start-2")
        assert controller.active_run_id == run_id
        await controller.stop(run_id)
        await controller.settled(run_id)


class FailingChunksCapture(FakeCapture):
    async def chunks(self) -> AsyncIterator[CaptureChunk]:
        yield CaptureChunk(np.zeros(1280, dtype=np.float32), [0.0])
        raise ThirdPartyError(
            "audio", "chunks", "failed", ErrorCode.MICROPHONE_DISCONNECTED
        )


class TrackedWavWriter(WavWriter):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.closed = False

    def close(self) -> None:
        super().close()
        self.closed = True


@pytest.mark.asyncio
async def test_T_RUN_001i_pump_error_releases_slot(tmp_path: Path) -> None:
    captures: list[FakeCapture] = []
    wavs: list[TrackedWavWriter] = []
    stt = FakeSttEngine("text")

    def new_capture() -> FakeCapture:
        capture = FailingChunksCapture() if not captures else FakeCapture()
        captures.append(capture)
        return capture

    def new_wav(path: Path) -> TrackedWavWriter:
        wav = TrackedWavWriter(path)
        wavs.append(wav)
        return wav

    async with scenario(
        tmp_path, new_capture=new_capture, stt=stt, new_wav=new_wav
    ) as (controller, history):
        run_id = await controller.start(start_request_id="start-1")
        with pytest.raises(ThirdPartyError) as raised:
            await controller.settled(run_id)
        assert raised.value.error_code == ErrorCode.MICROPHONE_DISCONNECTED
        assert stt.sessions[0].cancelled
        assert captures[0].cancelled
        assert wavs[0].closed
        failed = await history.get(run_id)
        assert failed.status == RunStatus.ERROR
        assert failed.error_code == ErrorCode.MICROPHONE_DISCONNECTED.value
        assert await controller.settled(run_id) == failed
        assert controller.active_run_id is None

        next_run_id = await controller.start(start_request_id="start-2")
        assert controller.active_run_id == next_run_id
        await controller.stop(next_run_id)
        await controller.settled(next_run_id)


@pytest.mark.asyncio
async def test_T_RUN_001j_stt_finish_error_cleans_up_and_releases_session(
    tmp_path: Path,
) -> None:
    captures: list[FakeCapture] = []
    wavs: list[TrackedWavWriter] = []
    stt = FakeSttEngine("text")

    def new_capture() -> FakeCapture:
        capture = FakeCapture()
        captures.append(capture)
        return capture

    def new_wav(path: Path) -> TrackedWavWriter:
        wav = TrackedWavWriter(path)
        wavs.append(wav)
        return wav

    async with scenario(
        tmp_path, new_capture=new_capture, stt=stt, new_wav=new_wav
    ) as (controller, history):
        run_id = await controller.start(start_request_id="start-1")
        error = ThirdPartyError("stt", "finish", "failed", ErrorCode.STT_UNAVAILABLE)

        async def fail_finish() -> str:
            assert (await history.get(run_id)).status == RunStatus.PROCESSING
            raise error

        with patch.object(stt.sessions[0], "finish", side_effect=fail_finish):
            await controller.stop(run_id)
            with pytest.raises(ThirdPartyError) as raised:
                await controller.settled(run_id)
        assert raised.value is error
        assert stt.sessions[0].cancelled
        assert captures[0].cancelled
        assert wavs[0].closed
        failed = await history.get(run_id)
        assert failed.status == RunStatus.ERROR
        assert failed.error_code == ErrorCode.STT_UNAVAILABLE.value
        assert await controller.settled(run_id) == failed

        next_run_id = await controller.start(start_request_id="start-2")
        await controller.stop(next_run_id)
        await controller.settled(next_run_id)
        assert len(stt.sessions) == 2


@pytest.mark.asyncio
async def test_T_RUN_001k_concurrent_settled_waits_for_final_record(
    tmp_path: Path,
) -> None:
    entered, release = asyncio.Event(), asyncio.Event()
    stt = FakeSttEngine("text")

    async with scenario(tmp_path, new_capture=FakeCapture, stt=stt) as (
        controller,
        history,
    ):
        run_id = await controller.start(start_request_id="start-1")

        async def held_finish() -> str:
            entered.set()
            await release.wait()
            stt.sessions[0].finished = True
            return "text"

        with patch.object(stt.sessions[0], "finish", side_effect=held_finish):
            await controller.stop(run_id)
            await entered.wait()
            first = asyncio.create_task(controller.settled(run_id))
            second = asyncio.create_task(controller.settled(run_id))
            try:
                await asyncio.sleep(0)
                assert not first.done()
                assert not second.done(), (
                    "settled returned a processing record while STT was still running"
                )
            finally:
                release.set()
                await asyncio.gather(first, second)

        final = await history.get(run_id)
        assert first.result() == final
        assert second.result() == final
        assert final.status == RunStatus.HELD
