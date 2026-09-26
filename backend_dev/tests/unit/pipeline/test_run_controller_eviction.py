"""WO-M3e: eviction, expiry, and start-time dictionary snapshots."""

from __future__ import annotations

import asyncio
import gc
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from fakes.audio import FakeCapture
from fakes.cleanup import FakeCleanupEngine
from fakes.clock import FakeClock
from fakes.events import FakeEventSink
from fakes.insertion import FakeUiaApi, FakeWin32Api
from fakes.stt import FakeSttEngine, FakeSttSession

from wispr_clone.audio.wav_writer import WavWriter
from wispr_clone.config import RUN_RETENTION_SECONDS
from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.contracts.run import RecoveryAction, RunStatus
from wispr_clone.dictionary.apply import DictionaryEntry
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


class LateSession(FakeSttSession):
    def __init__(self, final_text: str) -> None:
        super().__init__(final_text)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def finish(self) -> str:
        self.entered.set()
        await self.release.wait()
        self.finished = True
        return self.final_text


class LateEngine(FakeSttEngine):
    def start_session(self, on_text: Any = None) -> LateSession:
        if self.sessions and not (
            self.sessions[-1].finished or self.sessions[-1].cancelled
        ):
            raise WisprError(ErrorCode.STT_UNAVAILABLE, "stt", "session active")
        session = LateSession(self.final_text)
        self.sessions.append(session)
        return session


class Rig:
    def __init__(
        self,
        controller: RunController,
        history: HistoryRepo,
        dictionary: DictionaryRepo,
        clock: FakeClock,
        events: FakeEventSink,
        win: FakeWin32Api,
        uia: FakeUiaApi,
        stt: FakeSttEngine,
        captures: list[FakeCapture],
        config: dict[str, object],
    ) -> None:
        self.controller = controller
        self.history = history
        self.dictionary = dictionary
        self.clock = clock
        self.events = events
        self.win = win
        self.uia = uia
        self.stt = stt
        self.captures = captures
        self.config = config

    def sends(self) -> int:
        return sum(name == "send_inputs" for name, _, _ in self.win.calls)

    def states(self, run_id: str) -> list[dict[str, object]]:
        return [e for e in self.events.by_name("run:state") if e["run_id"] == run_id]


@asynccontextmanager
async def scenario(
    path: Path,
    *,
    stt: FakeSttEngine | None = None,
    cleanup: FakeCleanupEngine | None = None,
) -> AsyncIterator[Rig]:
    migrations = [
        Migration(module.VERSION, module.NAME, module.apply)
        for module in (m001_base, m002_settings, m003_dictionary, m004_history)
    ]
    async with Database(path / "runs.db", migrations) as db:
        clock = FakeClock(100)
        events = FakeEventSink()
        holder: dict[str, RunController] = {}
        history = HistoryRepo(
            db,
            clock=clock.now,
            audio_dir=path,
            events=events,
            on_run_evicted=lambda rid: holder["controller"].abort(rid),
        )
        dictionary = DictionaryRepo(db, clock=clock.now)
        win, uia = FakeWin32Api(), FakeUiaApi()
        snapshot = capture(win, uia)
        win.calls.clear()
        uia.calls.clear()
        win.on_send = lambda: uia.texts.__setitem__((1, 2), "before" + "open whisper")
        ids = iter(f"id-{i}" for i in range(100))
        config: dict[str, object] = {"cleanup_enabled": False}
        captures: list[FakeCapture] = []

        def new_capture() -> FakeCapture:
            item = FakeCapture()
            captures.append(item)
            return item

        async def inline(call: Callable[[], Any]) -> Any:
            return call()

        async def destination() -> Any:
            return snapshot

        protocol = InsertionProtocol(
            history,
            win,
            uia,
            offload=inline,
            clock=clock.now,
            new_id=lambda: next(ids),
            bring_forward_settle_s=0.0,
            paste_settle_s=0.0,
        )
        controller = RunController(
            RunServices(
                history=history,
                dictionary=dictionary,
                stt=stt or FakeSttEngine("open whisper"),
                insertion=protocol,
                events=events,
                capture_destination=destination,
                new_capture=new_capture,
                new_wav=WavWriter,
                new_id=lambda: next(ids),
                audio_dir=path,
                config_snapshot=lambda: dict(config),
                cleanup=cleanup,
                clock=clock.now,
            )
        )
        holder["controller"] = controller
        yield Rig(
            controller,
            history,
            dictionary,
            clock,
            events,
            win,
            uia,
            controller._services.stt,
            captures,
            config,
        )


async def missing(history: HistoryRepo, run_id: str) -> None:
    with pytest.raises(WisprError) as caught:
        await history.get(run_id)
    assert caught.value.error_code in {ErrorCode.RUN_NOT_FOUND, ErrorCode.RUN_EXPIRED}


@pytest.mark.asyncio
async def test_T_RUN_030_eviction_during_finish_discards_late_text(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    engine = LateEngine("open whisper")
    async with scenario(tmp_path, stt=engine) as rig:
        with caplog.at_level(logging.ERROR):
            run_id = await rig.controller.start(start_request_id="first")
            await rig.controller.stop(run_id)
            session = engine.sessions[0]
            assert isinstance(session, LateSession)
            await session.entered.wait()
            for i in range(10):
                await rig.history.create_run(
                    run_id=f"new-{i}", start_request_id=f"new-{i}", config={}
                )
            await asyncio.sleep(0)  # real deferred eviction callback
            events_after_eviction = len(rig.states(run_id))
            session.release.set()
            await asyncio.wait_for(rig.controller._tasks[run_id], 1)
            await missing(rig.history, run_id)
            with pytest.raises(WisprError) as caught:
                await rig.controller.settled(run_id)
            assert caught.value.error_code == ErrorCode.RUN_NOT_FOUND
            assert rig.sends() == 0
            assert len(rig.states(run_id)) == events_after_eviction
            gc.collect()
            await asyncio.sleep(0)
            assert "Task exception was never retrieved" not in caplog.text


@pytest.mark.asyncio
async def test_T_RUN_030g_expiry_while_recording_frees_slot(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        run_id = await rig.controller.start(start_request_id="first")
        rig.clock.advance(RUN_RETENTION_SECONDS)
        assert await rig.history.enforce_retention() == (run_id,)
        await asyncio.sleep(0)
        assert rig.captures[0].cancelled
        assert rig.stt.sessions[0].cancelled
        assert rig.controller.active_run_id is None
        assert rig.controller._slot_reserved is False
        await rig.controller.start(start_request_id="second")
        await rig.controller.cancel_current()


@pytest.mark.asyncio
async def test_T_RUN_030h_eviction_removes_awaiting_run(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        run_id = await rig.controller.start(start_request_id="first")
        rig.win.foreground = 20
        await rig.controller.stop(run_id)
        assert (
            await rig.controller.settled(run_id)
        ).status == RunStatus.AWAITING_DESTINATION
        assert rig.controller.waiting_run_ids == (run_id,)
        rig.clock.advance(RUN_RETENTION_SECONDS)
        await rig.history.enforce_retention()
        await asyncio.sleep(0)
        assert rig.controller.waiting_run_ids == ()
        rig.win.foreground = 10
        await rig.controller.delivery_tick()
        assert rig.sends() == 0


@pytest.mark.asyncio
async def test_T_RUN_030i_eviction_during_cleanup_discards_result(
    tmp_path: Path,
) -> None:
    cleanup = FakeCleanupEngine("open whisper.")
    cleanup.release.clear()
    async with scenario(tmp_path, cleanup=cleanup) as rig:
        rig.config["cleanup_enabled"] = True
        run_id = await rig.controller.start(start_request_id="first")
        await rig.controller.stop(run_id)
        await cleanup.entered.wait()
        rig.clock.advance(RUN_RETENTION_SECONDS)
        await rig.history.enforce_retention()
        await asyncio.sleep(0)
        events_after_eviction = len(rig.states(run_id))
        cleanup.release.set()
        await asyncio.wait_for(rig.controller._tasks[run_id], 1)
        await missing(rig.history, run_id)
        assert rig.sends() == 0
        assert len(rig.states(run_id)) == events_after_eviction


@pytest.mark.asyncio
async def test_T_RUN_030j_missing_before_callback_ends_quietly(tmp_path: Path) -> None:
    engine = LateEngine("open whisper")
    async with scenario(tmp_path, stt=engine) as rig:
        run_id = await rig.controller.start(start_request_id="first")
        await rig.controller.stop(run_id)
        session = engine.sessions[0]
        assert isinstance(session, LateSession)
        await session.entered.wait()
        await rig.history.delete_run(
            run_id
        )  # delete_run schedules no eviction callback
        events_after_deletion = len(rig.states(run_id))
        session.release.set()
        await asyncio.wait_for(rig.controller._tasks[run_id], 1)
        await missing(rig.history, run_id)
        assert rig.sends() == 0
        assert len(rig.states(run_id)) == events_after_deletion


@pytest.mark.asyncio
async def test_T_RUN_031_dictionary_and_config_snapshot_at_start(
    tmp_path: Path,
) -> None:
    cleanup = FakeCleanupEngine("OpenWhispr.")
    async with scenario(tmp_path, cleanup=cleanup) as rig:
        first = await rig.controller.start(start_request_id="first")
        await rig.dictionary.add(DictionaryEntry("OpenWhispr", ("open whisper",)))
        rig.config["cleanup_enabled"] = True
        await rig.controller.stop(first)
        original = await rig.controller.settled(first)
        assert original.adjusted_text == "open whisper"
        assert original.cleanup_status.value == "off"
        assert cleanup.requests == []
        rig.uia.texts[(1, 2)] = "before"
        second = await rig.controller.start(start_request_id="second")
        rig.config["cleanup_enabled"] = False
        await rig.controller.stop(second)
        updated = await rig.controller.settled(second)
        assert updated.adjusted_text == "OpenWhispr"
        assert updated.cleanup_status.value == "ok"
        assert cleanup.requests[0].glossary == ("OpenWhispr",)


@pytest.mark.asyncio
async def test_T_RUN_031c_cleanup_glossary_uses_start_snapshot(tmp_path: Path) -> None:
    cleanup = FakeCleanupEngine("open whisper.")
    async with scenario(tmp_path, cleanup=cleanup) as rig:
        rig.config["cleanup_enabled"] = True
        run_id = await rig.controller.start(start_request_id="first")
        await rig.dictionary.add(DictionaryEntry("OpenWhispr", ("open whisper",)))
        await rig.controller.stop(run_id)
        record = await rig.controller.settled(run_id)
        assert record.adjusted_text == "open whisper"
        assert cleanup.requests[0].glossary == ()


@pytest.mark.asyncio
async def test_T_RUN_031b_abort_unknown_and_finished_is_noop(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        rig.controller.abort("unknown")
        run_id = await rig.controller.start(start_request_id="first")
        await rig.controller.stop(run_id)
        finished = await rig.controller.settled(run_id)
        events_before = list(rig.events.events)
        rig.controller.abort(run_id)
        assert await rig.history.get(run_id) == finished
        assert rig.events.events == events_before


@pytest.mark.asyncio
async def test_T_RUN_032_abort_before_create_returns_stops_start(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as rig:
        create = rig.history.create_run
        created = asyncio.Event()
        release = asyncio.Event()

        async def delayed_create(**kwargs: Any) -> Any:
            record = await create(**kwargs)
            created.set()
            await release.wait()
            return record

        rig.history.create_run = delayed_create  # type: ignore[method-assign]
        starting = asyncio.create_task(rig.controller.start(start_request_id="first"))
        try:
            await asyncio.wait_for(created.wait(), 1)
            await rig.history.delete_run("id-0")
            rig.controller.abort("id-0")
        finally:
            release.set()
        try:
            await asyncio.wait_for(starting, 1)
        except WisprError as error:
            assert error.error_code == ErrorCode.RUN_NOT_FOUND
        else:
            await rig.controller.cancel("id-0")
            pytest.fail("start returned a run that had already been evicted")
        assert rig.controller.active_run_id is None
        assert rig.controller._slot_reserved is False
        assert rig.captures == []


@pytest.mark.asyncio
async def test_T_RUN_032a_abort_during_dictionary_read_frees_reserved_slot(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as rig:
        entries = rig.dictionary.entries
        reading = asyncio.Event()
        release = asyncio.Event()

        async def delayed_entries() -> Any:
            reading.set()
            await release.wait()
            return await entries()

        rig.dictionary.entries = delayed_entries  # type: ignore[method-assign]
        starting = asyncio.create_task(rig.controller.start(start_request_id="first"))
        try:
            await asyncio.wait_for(reading.wait(), 1)
            await rig.history.delete_run("id-0")
            rig.controller.abort("id-0")
            slot_freed = not rig.controller._slot_reserved
        finally:
            release.set()
        with pytest.raises(WisprError):
            await asyncio.wait_for(starting, 1)
        assert slot_freed
        assert rig.controller.active_run_id is None
        second = await rig.controller.start(start_request_id="second")
        await rig.controller.cancel(second)


@pytest.mark.asyncio
async def test_T_RUN_032b_abort_during_cleanup_failure_write_emits_no_event(
    tmp_path: Path,
) -> None:
    cleanup = FakeCleanupEngine(RuntimeError("cleanup failed"))
    async with scenario(tmp_path, cleanup=cleanup) as rig:
        rig.config["cleanup_enabled"] = True
        update = rig.history.update_run
        written = asyncio.Event()
        release = asyncio.Event()

        async def delayed_update(*args: Any, **kwargs: Any) -> Any:
            record = await update(*args, **kwargs)
            if record.status == RunStatus.AWAITING_CLEANUP_CHOICE:
                written.set()
                await release.wait()
            return record

        rig.history.update_run = delayed_update  # type: ignore[method-assign]
        run_id = await rig.controller.start(start_request_id="first")
        await rig.controller.stop(run_id)
        try:
            await asyncio.wait_for(written.wait(), 1)
            await rig.history.delete_run(run_id)
            rig.controller.abort(run_id)
            event_count = len(rig.states(run_id))
            recovery_count = len(rig.events.by_name("run:recovery"))
        finally:
            release.set()
        await asyncio.wait_for(rig.controller._tasks[run_id], 1)
        assert len(rig.states(run_id)) == event_count
        assert len(rig.events.by_name("run:recovery")) == recovery_count
        assert rig.sends() == 0


@pytest.mark.asyncio
async def test_T_RUN_032c_abort_during_tick_does_not_wait_for_insertion_gate(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as rig:
        run_id = await rig.controller.start(start_request_id="first")
        rig.win.foreground = 20
        await rig.controller.stop(run_id)
        assert (
            await rig.controller.settled(run_id)
        ).status == RunStatus.AWAITING_DESTINATION
        rig.win.foreground = 10
        protocol = rig.controller._services.insertion
        deliver = protocol.deliver_next
        entered = asyncio.Event()
        release = asyncio.Event()

        async def delayed_delivery(*args: Any, **kwargs: Any) -> Any:
            entered.set()
            await release.wait()
            return await deliver(*args, **kwargs)

        protocol.deliver_next = delayed_delivery  # type: ignore[method-assign]
        tick = asyncio.create_task(rig.controller.delivery_tick())
        try:
            await asyncio.wait_for(entered.wait(), 1)
            await rig.history.delete_run(run_id)
            rig.controller.abort(run_id)
            assert rig.controller.waiting_run_ids == ()
            assert rig.controller._insertion_gate.locked()
        finally:
            release.set()
        await asyncio.wait_for(tick, 1)
        assert rig.sends() == 0


@pytest.mark.asyncio
async def test_T_RUN_032d_abort_racing_cancel_emits_no_run_event(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as rig:
        run_id = await rig.controller.start(start_request_id="first")
        rig.win.foreground = 20
        await rig.controller.stop(run_id)
        await rig.controller.settled(run_id)
        await rig.controller._insertion_gate.acquire()
        cancelling = asyncio.create_task(rig.controller.cancel(run_id))
        try:
            await asyncio.sleep(0)
            await rig.history.delete_run(run_id)
            rig.controller.abort(run_id)
            states = len(rig.states(run_id))
        finally:
            rig.controller._insertion_gate.release()
        await asyncio.wait_for(cancelling, 1)
        assert len(rig.states(run_id)) == states
        assert rig.sends() == 0


@pytest.mark.asyncio
async def test_T_RUN_032e_aborted_ids_are_reclaimed_after_evicted_tasks_finish(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as rig:
        for index in range(3):
            run_id = await rig.controller.start(start_request_id=f"run-{index}")
            rig.clock.advance(RUN_RETENTION_SECONDS)
            assert await rig.history.enforce_retention() == (run_id,)
            await asyncio.sleep(0)
            await asyncio.wait_for(rig.controller._tasks[run_id], 1)
        assert len(rig.controller._aborted) == 0


@pytest.mark.asyncio
async def test_T_RUN_032f_retry_cleanup_rereads_dictionary(tmp_path: Path) -> None:
    cleanup = FakeCleanupEngine(RuntimeError("unavailable"), "open whisper.")
    async with scenario(tmp_path, cleanup=cleanup) as rig:
        rig.config["cleanup_enabled"] = True
        run_id = await rig.controller.start(start_request_id="first")
        await rig.controller.stop(run_id)
        failed = await rig.controller.settled(run_id)
        assert failed.status == RunStatus.AWAITING_CLEANUP_CHOICE
        await rig.dictionary.add(DictionaryEntry("OpenWhispr", ("open whisper",)))
        await rig.controller.recover(
            run_id, RecoveryAction.RETRY_CLEANUP, expected_version=failed.version
        )
        await rig.controller.settled(run_id)
        assert cleanup.requests[0].glossary == ()
        assert cleanup.requests[1].glossary == ("OpenWhispr",)


@pytest.mark.asyncio
async def test_T_RUN_032g_abort_pending_recovery_discards_cleanup_result(
    tmp_path: Path,
) -> None:
    cleanup = FakeCleanupEngine(RuntimeError("unavailable"), "open whisper.")
    async with scenario(tmp_path, cleanup=cleanup) as rig:
        rig.config["cleanup_enabled"] = True
        run_id = await rig.controller.start(start_request_id="first")
        await rig.controller.stop(run_id)
        failed = await rig.controller.settled(run_id)
        cleanup.entered.clear()
        cleanup.release.clear()
        await rig.controller.recover(
            run_id, RecoveryAction.RETRY_CLEANUP, expected_version=failed.version
        )
        await asyncio.wait_for(cleanup.entered.wait(), 1)
        await rig.history.delete_run(run_id)
        rig.controller.abort(run_id)
        state_count = len(rig.states(run_id))
        cleanup.release.set()
        await asyncio.wait_for(rig.controller._tasks[run_id], 1)
        assert len(rig.states(run_id)) == state_count
        assert rig.sends() == 0


@pytest.mark.asyncio
async def test_T_RUN_032h_abort_while_capture_drains_after_stop(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        run_id = await rig.controller.start(start_request_id="first")
        capture = rig.captures[0]
        draining = asyncio.Event()
        release = asyncio.Event()

        async def delayed_chunks() -> AsyncIterator[Any]:
            draining.set()
            await release.wait()
            if False:
                yield None

        capture.chunks = delayed_chunks  # type: ignore[method-assign]
        await rig.controller.stop(run_id)
        try:
            await asyncio.wait_for(draining.wait(), 1)
            await rig.history.delete_run(run_id)
            rig.controller.abort(run_id)
            state_count = len(rig.states(run_id))
        finally:
            release.set()
        await asyncio.wait_for(rig.controller._tasks[run_id], 1)
        assert len(rig.states(run_id)) == state_count
        assert rig.sends() == 0


@pytest.mark.asyncio
async def test_T_RUN_032i_abort_while_attempt_waits_before_dispatch(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as rig:
        protocol = rig.controller._services.insertion
        attempt = protocol.attempt
        entered = asyncio.Event()
        release = asyncio.Event()

        async def delayed_attempt(*args: Any, **kwargs: Any) -> Any:
            entered.set()
            await release.wait()
            return await attempt(*args, **kwargs)

        protocol.attempt = delayed_attempt  # type: ignore[method-assign]
        run_id = await rig.controller.start(start_request_id="first")
        await rig.controller.stop(run_id)
        try:
            await asyncio.wait_for(entered.wait(), 1)
            await rig.history.delete_run(run_id)
            rig.controller.abort(run_id)
            state_count = len(rig.states(run_id))
        finally:
            release.set()
        await asyncio.wait_for(rig.controller._tasks[run_id], 1)
        assert len(rig.states(run_id)) == state_count
        assert rig.sends() == 0
