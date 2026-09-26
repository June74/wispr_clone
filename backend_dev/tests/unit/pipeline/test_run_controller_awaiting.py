"""WO-M3d retained destination delivery and explicit recovery contracts."""

from __future__ import annotations

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
from fakes.stt import FakeSttEngine

from wispr_clone.audio.wav_writer import WavWriter
from wispr_clone.config import RUN_RETENTION_SECONDS
from wispr_clone.contracts.common import ErrorCode, ThirdPartyError, WisprError
from wispr_clone.contracts.run import InsertionOutcome, RecoveryAction, RunStatus
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

RAW = "do not open whisper"
ADJUSTED = "do not OpenWhispr"


class Rig:
    def __init__(
        self,
        controller: RunController,
        history: HistoryRepo,
        events: FakeEventSink,
        win: FakeWin32Api,
        uia: FakeUiaApi,
        clock: FakeClock,
        config: dict[str, object],
        inserted: list[str],
    ) -> None:
        self.controller = controller
        self.history = history
        self.events = events
        self.win = win
        self.uia = uia
        self.clock = clock
        self.config = config
        self.inserted = inserted

    async def finish(self, *, away: bool = False) -> tuple[str, RunRecord]:
        run_id = await self.controller.start(
            start_request_id=f"start-{self.clock.now()}"
        )
        if away:
            self.win.foreground = 20
        await self.controller.stop(run_id)
        return run_id, await self.controller.settled(run_id)

    def sends(self) -> int:
        return sum(name == "send_inputs" for name, _, _ in self.win.calls)

    def recovery(self, run_id: str) -> list[dict[str, object]]:
        return [
            event
            for event in self.events.by_name("run:recovery")
            if event["run_id"] == run_id
        ]


@asynccontextmanager
async def scenario(
    path: Path,
    *,
    cleanup: FakeCleanupEngine | None = None,
    enabled: bool = False,
) -> AsyncIterator[Rig]:
    migrations = [
        Migration(module.VERSION, module.NAME, module.apply)
        for module in (m001_base, m002_settings, m003_dictionary, m004_history)
    ]
    async with Database(path / "runs.db", migrations) as db:
        clock = FakeClock(100)
        events = FakeEventSink()
        history = HistoryRepo(db, clock=clock.now, audio_dir=path, events=events)
        dictionary = DictionaryRepo(db, clock=clock.now)
        await dictionary.add(DictionaryEntry("OpenWhispr", ("open whisper",)))
        win, uia = FakeWin32Api(), FakeUiaApi()
        snapshot = capture(win, uia)
        win.calls.clear()
        uia.calls.clear()
        inserted = [ADJUSTED]
        win.on_send = lambda: uia.texts.__setitem__(
            (1, 2), (uia.texts[(1, 2)] or "") + inserted[0]
        )
        ids = iter(f"id-{number}" for number in range(100))
        config: dict[str, object] = {"cleanup_enabled": enabled}

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
                stt=FakeSttEngine(RAW),
                insertion=protocol,
                events=events,
                capture_destination=destination,
                new_capture=FakeCapture,
                new_wav=WavWriter,
                new_id=lambda: next(ids),
                audio_dir=path,
                config_snapshot=lambda: dict(config),
                cleanup=cleanup,
                clock=clock.now,
            )
        )
        yield Rig(controller, history, events, win, uia, clock, config, inserted)


@pytest.mark.asyncio
async def test_T_RUN_020_return_to_original_destination(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        run_id, waiting = await rig.finish(away=True)
        assert waiting.status == RunStatus.AWAITING_DESTINATION
        assert waiting.awaiting_since == rig.clock.now()
        assert rig.controller.waiting_run_ids == (run_id,)
        assert rig.recovery(run_id) == [
            {
                "name": "run:recovery",
                "run_id": run_id,
                "version": waiting.version,
                "status": "awaiting_destination",
                "actions": ["copy", "insert"],
            }
        ]
        rig.win.idle_values = [0]
        await rig.controller.delivery_tick()
        assert (await rig.history.get(run_id)).version == waiting.version
        assert rig.sends() == 0
        rig.win.foreground = 10
        rig.win.idle_values = [300]
        await rig.controller.delivery_tick()
        assert (await rig.history.get(run_id)).status == RunStatus.DONE
        assert rig.sends() == 1
        assert rig.controller.waiting_run_ids == ()
        await rig.controller.delivery_tick()
        assert rig.sends() == 1


@pytest.mark.asyncio
async def test_T_RUN_020b_idle_jump_restores_previous_window(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        run_id, _ = await rig.finish(away=True)
        rig.win.idle_values = [1500] * 8
        await rig.controller.delivery_tick()
        assert (await rig.history.get(run_id)).status == RunStatus.DONE
        assert rig.sends() == 1
        assert rig.win.foreground == 20
        assert rig.uia.tabs[20] == (20, 1)


@pytest.mark.asyncio
async def test_T_RUN_020c_oldest_first_one_per_tick(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        first, _ = await rig.finish(away=True)
        rig.clock.advance(1)
        second, _ = await rig.finish(away=True)
        rig.win.foreground = 10
        rig.win.idle_values = [300, 300]
        assert rig.controller.waiting_run_ids == (first, second)
        await rig.controller.delivery_tick()
        assert rig.sends() == 1
        assert (await rig.history.get(first)).status == RunStatus.DONE
        assert (await rig.history.get(second)).status == RunStatus.AWAITING_DESTINATION
        await rig.controller.delivery_tick()
        assert rig.sends() == 2
        assert (await rig.history.get(second)).status == RunStatus.DONE


@pytest.mark.asyncio
async def test_T_RUN_021_held_explicit_insert(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        rig.win.windows.remove(10)
        run_id, held = await rig.finish()
        assert held.status == RunStatus.HELD
        assert rig.recovery(run_id)[-1]["actions"] == ["copy", "insert"]
        rig.win.windows.add(10)
        await rig.controller.recover(
            run_id, RecoveryAction.INSERT, expected_version=held.version
        )
        assert (await rig.history.get(run_id)).status == RunStatus.DONE
        assert rig.sends() == 1
        attempts = await rig.history.attempts(run_id)
        assert len(attempts) == 1 and attempts[0].kind == "explicit"


@pytest.mark.asyncio
async def test_T_RUN_021b_confirmed_attempt_blocks_second_paste(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        run_id, done = await rig.finish()
        assert done.status == RunStatus.DONE
        assert await rig.history.insertion_outcome(run_id) == InsertionOutcome.INSERTED
        error = await rig.history.update_run(
            run_id, expected_version=done.version, status=RunStatus.ERROR
        )
        with pytest.raises(WisprError, match="already inserted") as caught:
            await rig.controller.recover(
                run_id, RecoveryAction.INSERT, expected_version=error.version
            )
        assert caught.value.error_code == ErrorCode.VALIDATION
        assert rig.sends() == 1
        assert len(await rig.history.attempts(run_id)) == 1


@pytest.mark.asyncio
async def test_T_RUN_021c_uncertain_requires_acknowledgement(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        rig.win.on_send = None
        run_id, uncertain = await rig.finish()
        assert uncertain.status == RunStatus.UNCERTAIN
        with pytest.raises(WisprError, match="acknowledge") as caught:
            await rig.controller.recover(
                run_id, RecoveryAction.INSERT, expected_version=uncertain.version
            )
        assert caught.value.error_code == ErrorCode.VALIDATION
        assert rig.sends() == 1
        rig.win.on_send = lambda: rig.uia.texts.__setitem__((1, 2), "before" + ADJUSTED)
        await rig.controller.recover(
            run_id,
            RecoveryAction.INSERT,
            expected_version=uncertain.version,
            acknowledge_uncertain=True,
        )
        assert (await rig.history.get(run_id)).status == RunStatus.DONE
        assert rig.sends() == 2
        assert len(await rig.history.attempts(run_id)) == 2


@pytest.mark.asyncio
async def test_T_RUN_021d_away_explicit_insert_keeps_wait(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        run_id, waiting = await rig.finish(away=True)
        with pytest.raises(WisprError) as caught:
            await rig.controller.recover(
                run_id, RecoveryAction.INSERT, expected_version=waiting.version
            )
        assert caught.value.error_code == ErrorCode.DESTINATION_UNVERIFIABLE
        assert (await rig.history.get(run_id)).status == RunStatus.AWAITING_DESTINATION
        assert rig.controller.waiting_run_ids == (run_id,)
        assert rig.sends() == 0


@pytest.mark.asyncio
async def test_T_RUN_022_copy_selected_text_has_no_side_effect(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        run_id, waiting = await rig.finish(away=True)
        assert await rig.controller.copy_text(run_id) == ADJUSTED
        assert (await rig.history.get(run_id)).version == waiting.version
        assert rig.sends() == 0
        assert rig.win.clipboard is None


@pytest.mark.asyncio
async def test_T_RUN_023_copy_and_insert_use_original_selection(tmp_path: Path) -> None:
    timeout = ThirdPartyError("cleanup", "clean", "private", ErrorCode.CLEANUP_TIMEOUT)
    async with scenario(
        tmp_path, cleanup=FakeCleanupEngine(timeout), enabled=True
    ) as rig:
        run_id, choice = await rig.finish()
        rig.win.foreground = 20
        await rig.controller.recover(
            run_id, RecoveryAction.USE_ORIGINAL, expected_version=choice.version
        )
        waiting = await rig.controller.settled(run_id)
        assert waiting.status == RunStatus.AWAITING_DESTINATION
        assert await rig.controller.copy_text(run_id) == RAW
        rig.win.foreground = 10
        rig.inserted[0] = RAW
        await rig.controller.recover(
            run_id, RecoveryAction.INSERT, expected_version=waiting.version
        )
        assert (await rig.history.get(run_id)).status == RunStatus.DONE
        assert rig.uia.texts[(1, 2)] == "before" + RAW
        assert rig.sends() == 1


@pytest.mark.asyncio
async def test_T_RUN_024_stale_version_prevents_insert(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        rig.win.windows.remove(10)
        run_id, held = await rig.finish()
        with pytest.raises(WisprError) as caught:
            await rig.controller.recover(
                run_id, RecoveryAction.INSERT, expected_version=held.version - 1
            )
        assert caught.value.error_code == ErrorCode.STALE_VERSION
        assert (await rig.history.get(run_id)).version == held.version
        assert rig.sends() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["recover", "copy"])
async def test_T_RUN_025_expired_run_rejects_recovery_and_copy(
    tmp_path: Path, action: str
) -> None:
    async with scenario(tmp_path) as rig:
        rig.win.windows.remove(10)
        run_id, held = await rig.finish()
        rig.clock.advance(RUN_RETENTION_SECONDS + 1)
        with pytest.raises(WisprError) as caught:
            if action == "recover":
                await rig.controller.recover(
                    run_id, RecoveryAction.INSERT, expected_version=held.version
                )
            else:
                await rig.controller.copy_text(run_id)
        assert caught.value.error_code == ErrorCode.RUN_EXPIRED
        assert rig.sends() == 0


@pytest.mark.asyncio
async def test_T_RUN_026_stored_wait_configuration_controls_hold(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as rig:
        rig.config.update(idle_jump_seconds=3, destination_wait_limit_seconds=60)
        run_id, waiting = await rig.finish(away=True)
        rig.config.update(idle_jump_seconds=1, destination_wait_limit_seconds=600)
        rig.win.idle_values = [2500]
        await rig.controller.delivery_tick()
        assert (await rig.history.get(run_id)).version == waiting.version
        assert rig.sends() == 0
        rig.clock.advance(61)
        protocol = rig.controller._services.insertion
        deliver = protocol.deliver_next
        reasons: list[str] = []

        async def record_reason(*args: Any, **kwargs: Any) -> Any:
            result = await deliver(*args, **kwargs)
            if result is not None:
                reasons.append(result[1].reason)
            return result

        protocol.deliver_next = record_reason  # type: ignore[method-assign]
        await rig.controller.delivery_tick()
        assert reasons == ["wait limit"]
        assert (await rig.history.get(run_id)).status == RunStatus.HELD
        assert rig.recovery(run_id)[-1]["actions"] == ["copy", "insert"]
        assert rig.sends() == 0


@pytest.mark.asyncio
async def test_T_RUN_027_cancel_removes_waiting_run(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        run_id, _ = await rig.finish(away=True)
        await rig.controller.cancel(run_id)
        assert rig.controller.waiting_run_ids == ()
        assert (await rig.history.get(run_id)).status == RunStatus.CANCELLED
        rig.win.foreground = 10
        await rig.controller.delivery_tick()
        assert rig.sends() == 0


@pytest.mark.asyncio
async def test_T_RUN_028_closed_while_waiting_becomes_held(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        run_id, _ = await rig.finish(away=True)
        rig.win.windows.remove(10)
        await rig.controller.delivery_tick()
        assert (await rig.history.get(run_id)).status == RunStatus.HELD
        assert rig.recovery(run_id)[-1]["actions"] == ["copy", "insert"]
        assert rig.sends() == 0


@pytest.mark.asyncio
async def test_T_RUN_029_tick_exception_retains_waiting_run(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        run_id, _ = await rig.finish(away=True)
        protocol = rig.controller._services.insertion
        original = protocol.deliver_next
        calls = 0

        async def fail_once(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("private transcript")
            return await original(*args, **kwargs)

        protocol.deliver_next = fail_once  # type: ignore[method-assign]
        await rig.controller.delivery_tick()
        assert rig.controller.waiting_run_ids == (run_id,)
        rig.win.foreground = 10
        await rig.controller.delivery_tick()
        assert (await rig.history.get(run_id)).status == RunStatus.DONE
        assert rig.sends() == 1
