"""WO-M3f retained-WAV STT recovery contracts."""

from __future__ import annotations

import asyncio
import wave
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
from fakes.stt import FakeSttEngine, FakeSttSession

from wispr_clone.audio.capture import CaptureChunk
from wispr_clone.audio.wav_writer import WavWriter
from wispr_clone.config import RUN_RETENTION_SECONDS
from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.contracts.run import RecoveryAction, RunStatus
from wispr_clone.dictionary.apply import DictionaryEntry
from wispr_clone.dictionary.repo import DictionaryRepo
from wispr_clone.history.repo import HistoryRepo, RunRecord
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


class ReplayEngine(FakeSttEngine):
    def __init__(self, text: str = "open whisper") -> None:
        super().__init__(text)
        self.fail_replay: ErrorCode | None = None
        self.replay_entered = asyncio.Event()
        self.replay_release = asyncio.Event()
        self.replay_release.set()

    def start_session(self, on_text: Any = None) -> FakeSttSession:
        session = super().start_session(on_text)
        if self.transcribed:
            finish = session.finish

            async def replay_finish() -> str:
                self.replay_entered.set()
                await self.replay_release.wait()
                result = await finish()
                if self.fail_replay is not None:
                    raise WisprError(self.fail_replay, "stt", "replay failed")
                return result

            session.finish = replay_finish  # type: ignore[method-assign]
        return session


class Rig:
    def __init__(
        self,
        controller: RunController,
        history: HistoryRepo,
        dictionary: DictionaryRepo,
        events: FakeEventSink,
        clock: FakeClock,
        stt: ReplayEngine,
        win: FakeWin32Api,
        captures: list[FakeCapture],
        uia: FakeUiaApi,
    ) -> None:
        self.controller, self.history, self.dictionary = controller, history, dictionary
        self.events, self.clock, self.stt = events, clock, stt
        self.win, self.captures, self.uia = win, captures, uia

    def sends(self) -> int:
        return sum(name == "send_inputs" for name, _, _ in self.win.calls)

    def actions(self, run_id: str) -> list[str]:
        events = [
            event
            for event in self.events.by_name("run:recovery")
            if event["run_id"] == run_id
        ]
        return [str(action) for action in events[-1]["actions"]]

    async def captured_failure(
        self, *, text: str = "open whisper"
    ) -> tuple[str, RunRecord]:
        run_id = await self.controller.start(start_request_id="first")
        self.captures[-1].queue(
            CaptureChunk(np.ones(1280, dtype=np.float32) * 0.1, [0.1])
        )
        await self.captures[-1].pumped.wait()
        session = self.stt.sessions[-1]
        if text:

            async def failed_finish() -> str:
                raise WisprError(ErrorCode.STT_TIMEOUT, "stt", "initial failure")

            session.finish = failed_finish  # type: ignore[method-assign]
        else:
            session.final_text = "  \t"
        await self.controller.stop(run_id)
        if text:
            with pytest.raises(WisprError) as caught:
                await self.controller.settled(run_id)
            assert caught.value.error_code == ErrorCode.STT_TIMEOUT
            return run_id, await self.history.get(run_id)
        return run_id, await self.controller.settled(run_id)


@asynccontextmanager
async def scenario(
    path: Path, *, engine: ReplayEngine | None = None
) -> AsyncIterator[Rig]:
    migrations = [
        Migration(m.VERSION, m.NAME, m.apply)
        for m in (m001_base, m002_settings, m003_dictionary, m004_history)
    ]
    async with Database(path / "runs.db", migrations) as db:
        clock = FakeClock(100)
        events = FakeEventSink()
        history = HistoryRepo(db, clock=clock.now, audio_dir=path, events=events)
        dictionary = DictionaryRepo(db, clock=clock.now)
        stt = engine or ReplayEngine()
        win, uia = FakeWin32Api(), FakeUiaApi()
        snapshot = capture(win, uia)
        win.calls.clear()
        uia.calls.clear()
        win.on_send = lambda: uia.texts.__setitem__(
            (1, 2), "before" + stt.final_text.replace("open whisper", "OpenWhispr")
        )
        captures: list[FakeCapture] = []
        ids = iter(f"id-{i}" for i in range(100))

        async def inline(call: Callable[[], Any]) -> Any:
            return call()

        async def destination() -> Any:
            return snapshot

        def new_capture() -> FakeCapture:
            result = FakeCapture()
            captures.append(result)
            return result

        controller = RunController(
            RunServices(
                history=history,
                dictionary=dictionary,
                stt=stt,
                insertion=InsertionProtocol(
                    history,
                    win,
                    uia,
                    offload=inline,
                    clock=clock.now,
                    new_id=lambda: next(ids),
                    paste_settle_s=0.0,
                ),
                events=events,
                capture_destination=destination,
                new_capture=new_capture,
                new_wav=WavWriter,
                new_id=lambda: next(ids),
                audio_dir=path,
                config_snapshot=lambda: {},
                clock=clock.now,
            )
        )
        yield Rig(
            controller, history, dictionary, events, clock, stt, win, captures, uia
        )


async def rejects(
    rig: Rig, record: RunRecord, code: ErrorCode, why: str | None = None
) -> None:
    with pytest.raises(WisprError) as caught:
        await rig.controller.recover(
            record.id, RecoveryAction.RETRY_STT, expected_version=record.version
        )
    assert caught.value.error_code == code
    if why is not None:
        assert caught.value.why == why


@pytest.mark.asyncio
async def test_T_RUN_040_retry_replays_wav_and_preserves_age(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        run_id, failed = await rig.captured_failure()
        assert failed.status == RunStatus.ERROR
        assert failed.error_code == ErrorCode.STT_TIMEOUT.value
        assert "retry_stt" in rig.actions(run_id)
        await rig.dictionary.add(DictionaryEntry("OpenWhispr", ("open whisper",)))
        await rig.controller.recover(
            run_id, RecoveryAction.RETRY_STT, expected_version=failed.version
        )
        done = await rig.controller.settled(run_id)
        assert rig.stt.transcribed == [Path(str(failed.audio_path))]
        assert done.status == RunStatus.DONE
        assert done.original_text == "open whisper"
        assert done.adjusted_text == "OpenWhispr"
        assert done.created_at == failed.created_at
        assert rig.sends() == 1
        assert len(await rig.history.attempts(run_id)) == 1
        assert (await rig.history.attempts(run_id))[0].kind == "automatic"
        rig.clock.advance(RUN_RETENTION_SECONDS)
        with pytest.raises(WisprError) as caught:
            await rig.history.get(run_id)
        assert caught.value.error_code == ErrorCode.RUN_EXPIRED


@pytest.mark.asyncio
async def test_T_RUN_040b_failed_replay_remains_retryable(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        run_id, first = await rig.captured_failure()
        await rig.dictionary.add(DictionaryEntry("OpenWhispr", ("open whisper",)))
        rig.stt.fail_replay = ErrorCode.STT_UNAVAILABLE
        await rig.controller.recover(
            run_id, RecoveryAction.RETRY_STT, expected_version=first.version
        )
        with pytest.raises(WisprError):
            await rig.controller.settled(run_id)
        second = await rig.history.get(run_id)
        assert second.status == RunStatus.ERROR
        assert second.error_code == ErrorCode.STT_UNAVAILABLE.value
        assert "retry_stt" in rig.actions(run_id)
        rig.stt.fail_replay = None
        await rig.controller.recover(
            run_id, RecoveryAction.RETRY_STT, expected_version=second.version
        )
        assert (await rig.controller.settled(run_id)).status == RunStatus.DONE
        assert len(rig.stt.transcribed) == 2
        assert rig.sends() == 1


@pytest.mark.asyncio
async def test_T_RUN_040c_no_speech_can_be_retried(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        run_id, empty = await rig.captured_failure(text="")
        await rig.dictionary.add(DictionaryEntry("OpenWhispr", ("open whisper",)))
        assert empty.original_text is None
        assert empty.error_code == ErrorCode.NO_SPEECH_DETECTED.value
        assert "retry_stt" in rig.actions(run_id)
        await rig.controller.recover(
            run_id, RecoveryAction.RETRY_STT, expected_version=empty.version
        )
        assert (await rig.controller.settled(run_id)).status == RunStatus.DONE
        assert rig.sends() == 1


@pytest.mark.asyncio
async def test_T_RUN_040d_retry_holds_single_session_slot(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        run_id, failed = await rig.captured_failure()
        rig.stt.replay_release.clear()
        await rig.controller.recover(
            run_id, RecoveryAction.RETRY_STT, expected_version=failed.version
        )
        try:
            await asyncio.wait_for(rig.stt.replay_entered.wait(), 1)
            with pytest.raises(WisprError) as caught:
                await rig.controller.start(start_request_id="blocked")
            assert caught.value.error_code == ErrorCode.DEVICE_LEASE_CONFLICT
        finally:
            rig.stt.replay_release.set()
        await rig.controller.settled(run_id)
        second = await rig.controller.start(start_request_id="recording")
        third = await rig.history.create_run(
            run_id="retry-while-recording",
            start_request_id="third",
            config={},
            audio_path=str(tmp_path / "retry-while-recording.wav"),
        )
        wav = WavWriter(tmp_path / "retry-while-recording.wav")
        wav.write(np.ones(128, dtype=np.float32))
        wav.close()
        third = await rig.history.update_run(
            third.id,
            expected_version=third.version,
            status=RunStatus.ERROR,
            error_code="stt_timeout",
        )
        await rejects(rig, third, ErrorCode.DEVICE_LEASE_CONFLICT, "busy")
        await rig.controller.cancel(second)


@pytest.mark.asyncio
async def test_T_RUN_040e_cancel_during_replay_suppresses_dispatch(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as rig:
        run_id, failed = await rig.captured_failure()
        rig.stt.replay_release.clear()
        await rig.controller.recover(
            run_id, RecoveryAction.RETRY_STT, expected_version=failed.version
        )
        await asyncio.wait_for(rig.stt.replay_entered.wait(), 1)
        await rig.controller.cancel(run_id)
        rig.stt.replay_release.set()
        assert (await rig.controller.settled(run_id)).status == RunStatus.CANCELLED
        assert rig.sends() == 0
        new = await rig.controller.start(start_request_id="after-cancel")
        await rig.controller.cancel(new)


@pytest.mark.asyncio
@pytest.mark.parametrize("remove", [True, False])
async def test_T_RUN_041_missing_or_empty_wav_rejected(
    tmp_path: Path, remove: bool
) -> None:
    async with scenario(tmp_path) as rig:
        run_id = await rig.controller.start(start_request_id="first")
        rig.captures[-1].queue(CaptureChunk(np.ones(128, dtype=np.float32), [0.1]))
        await rig.captures[-1].pumped.wait()
        path = tmp_path / f"{run_id}.wav"

        async def failed_finish() -> str:
            path.unlink()
            if not remove:
                writer = WavWriter(path)
                writer.open()
                writer.close()
            raise WisprError(ErrorCode.STT_TIMEOUT, "stt", "initial failure")

        rig.stt.sessions[-1].finish = failed_finish  # type: ignore[method-assign]
        await rig.controller.stop(run_id)
        with pytest.raises(WisprError):
            await rig.controller.settled(run_id)
        failed = await rig.history.get(run_id)
        assert "retry_stt" not in rig.actions(run_id)
        await rejects(rig, failed, ErrorCode.VALIDATION, "no audio")


@pytest.mark.asyncio
async def test_T_RUN_041b_existing_text_disallows_retry(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        rig.win.accepted = 0
        run_id = await rig.controller.start(start_request_id="first")
        rig.captures[-1].queue(CaptureChunk(np.ones(128, dtype=np.float32), [0.1]))
        await rig.captures[-1].pumped.wait()
        await rig.controller.stop(run_id)
        record = await rig.controller.settled(run_id)
        assert record.status == RunStatus.ERROR
        assert record.original_text is not None
        assert "retry_stt" not in rig.actions(run_id)
        await rejects(rig, record, ErrorCode.VALIDATION, "no audio")


@pytest.mark.asyncio
async def test_T_RUN_041c_stale_and_expired_precede_audio_checks(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as rig:
        run_id, failed = await rig.captured_failure()
        with pytest.raises(WisprError) as caught:
            await rig.controller.recover(
                run_id, RecoveryAction.RETRY_STT, expected_version=failed.version - 1
            )
        assert caught.value.error_code == ErrorCode.STALE_VERSION
        rig.clock.advance(RUN_RETENTION_SECONDS)
        await rejects(rig, failed, ErrorCode.RUN_EXPIRED)


@pytest.mark.asyncio
async def test_T_RUN_042a_start_cannot_claim_slot_during_retry_write(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as rig:
        run_id, failed = await rig.captured_failure()
        original_update = rig.history.update_run
        writing = asyncio.Event()
        release = asyncio.Event()

        async def paused_update(target_run_id: str, **changes: Any) -> RunRecord:
            if (
                target_run_id == run_id
                and changes.get("status") == RunStatus.PROCESSING
            ):
                writing.set()
                await release.wait()
            return await original_update(target_run_id, **changes)

        rig.history.update_run = paused_update  # type: ignore[method-assign]
        retry = asyncio.create_task(
            rig.controller.recover(
                run_id, RecoveryAction.RETRY_STT, expected_version=failed.version
            )
        )
        started: str | None = None
        start_error: WisprError | None = None
        try:
            await asyncio.wait_for(writing.wait(), 1)
            try:
                started = await rig.controller.start(start_request_id="racing-start")
            except WisprError as error:
                start_error = error
            if started is not None:
                await rig.controller.cancel(started)
                await rig.controller.settled(started)
        finally:
            release.set()
        await retry
        await rig.controller.settled(run_id)
        assert start_error is not None
        assert start_error.error_code == ErrorCode.DEVICE_LEASE_CONFLICT


@pytest.mark.asyncio
async def test_T_RUN_042b_abort_holds_slot_until_transcription_returns(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as rig:
        run_id, failed = await rig.captured_failure()
        rig.stt.replay_release.clear()
        await rig.controller.recover(
            run_id, RecoveryAction.RETRY_STT, expected_version=failed.version
        )
        await asyncio.wait_for(rig.stt.replay_entered.wait(), 1)
        await rig.history.delete_run(run_id)
        rig.controller.abort(run_id)
        try:
            with pytest.raises(WisprError) as caught:
                await rig.controller.start(start_request_id="during-abort")
            assert caught.value.error_code == ErrorCode.DEVICE_LEASE_CONFLICT
        finally:
            rig.stt.replay_release.set()
        with pytest.raises(WisprError) as caught:
            await rig.controller.settled(run_id)
        assert caught.value.error_code == ErrorCode.RUN_NOT_FOUND
        assert rig.sends() == 0
        next_run = await rig.controller.start(start_request_id="after-abort")
        await rig.controller.cancel(next_run)


@pytest.mark.asyncio
async def test_T_RUN_042c_double_retry_starts_one_transcription(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        run_id, failed = await rig.captured_failure()
        rig.stt.replay_release.clear()
        await rig.controller.recover(
            run_id, RecoveryAction.RETRY_STT, expected_version=failed.version
        )
        try:
            await asyncio.wait_for(rig.stt.replay_entered.wait(), 1)
            with pytest.raises(WisprError) as caught:
                await rig.controller.recover(
                    run_id, RecoveryAction.RETRY_STT, expected_version=failed.version
                )
            assert caught.value.error_code == ErrorCode.STALE_VERSION
            assert len(rig.stt.transcribed) == 1
        finally:
            rig.stt.replay_release.set()
        await rig.controller.settled(run_id)


@pytest.mark.asyncio
async def test_T_RUN_042d_corrupt_wav_does_not_break_recovery_publish(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as rig:
        run_id, failed = await rig.captured_failure()
        assert failed.audio_path is not None
        Path(failed.audio_path).write_bytes(b"corrupt WAV")
        rig.controller._publish_recovery(failed)
        assert "retry_stt" not in rig.actions(run_id)
        await rejects(rig, failed, ErrorCode.VALIDATION, "no audio")


@pytest.mark.asyncio
async def test_T_RUN_042e_cancel_before_retry_task_skips_transcription(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as rig:
        run_id, failed = await rig.captured_failure()
        await rig.controller.recover(
            run_id, RecoveryAction.RETRY_STT, expected_version=failed.version
        )
        await rig.controller.cancel(run_id)
        assert (await rig.controller.settled(run_id)).status == RunStatus.CANCELLED
        assert rig.stt.transcribed == []
        assert rig.sends() == 0
        next_run = await rig.controller.start(start_request_id="after-cancel")
        await rig.controller.cancel(next_run)


@pytest.mark.asyncio
async def test_fake_replay_validates_wav_and_uses_one_session(tmp_path: Path) -> None:
    engine = FakeSttEngine("recognized")
    valid = tmp_path / "valid.wav"
    writer = WavWriter(valid)
    writer.write(np.ones(128, dtype=np.float32))
    writer.close()
    active = engine.start_session()
    with pytest.raises(WisprError) as caught:
        await engine.transcribe_file(valid)
    assert caught.value.error_code == ErrorCode.STT_UNAVAILABLE
    active.cancel()
    assert await engine.transcribe_file(valid) == "recognized"
    assert len(engine.sessions) == 2
    assert engine.sessions[-1].pushed[0].typecode == "f"
    invalid = tmp_path / "invalid.wav"
    with wave.open(str(invalid), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\0" * 8)
    with pytest.raises(WisprError) as caught:
        await engine.transcribe_file(invalid)
    assert caught.value.error_code == ErrorCode.VALIDATION
    assert caught.value.why == "wav format"
