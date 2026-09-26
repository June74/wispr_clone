"""WO-M3c cleanup selection, recovery, and cancellation contracts."""

from __future__ import annotations

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
from fakes.stt import FakeSttEngine

from wispr_clone.audio.wav_writer import WavWriter
from wispr_clone.contracts.common import ErrorCode, ThirdPartyError, WisprError
from wispr_clone.contracts.run import CleanupStatus, RecoveryAction, RunStatus
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
CLEANED = "do not OpenWhispr."


class Rig:
    def __init__(
        self,
        controller: RunController,
        history: HistoryRepo,
        events: FakeEventSink,
        win: FakeWin32Api,
        uia: FakeUiaApi,
        cleanup: FakeCleanupEngine | None,
        config: dict[str, object],
        inserted: list[str],
    ) -> None:
        self.controller = controller
        self.history = history
        self.events = events
        self.win = win
        self.uia = uia
        self.cleanup = cleanup
        self.config = config
        self.inserted = inserted

    async def finish(self) -> tuple[str, RunRecord]:
        run_id = await self.controller.start(start_request_id="start-1")
        await self.controller.stop(run_id)
        return run_id, await self.controller.settled(run_id)

    def sends(self) -> int:
        return sum(name == "send_inputs" for name, _, _ in self.win.calls)

    def verifications(self) -> int:
        return sum(name == "is_window" for name, _, _ in self.win.calls)

    def states(self, run_id: str) -> list[str]:
        return [
            str(event["status"])
            for event in self.events.by_name("run:state")
            if event["run_id"] == run_id
        ]


@asynccontextmanager
async def scenario(
    path: Path,
    *,
    cleanup: FakeCleanupEngine | None,
    enabled: bool = True,
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
        win.on_send = lambda: uia.texts.__setitem__((1, 2), "before" + inserted[0])
        ids = iter(f"id-{number}" for number in range(20))
        config: dict[str, object] = {
            "cleanup_enabled": enabled,
            "cleanup_instructions": "Keep the wording",
        }

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
            new_id=lambda: "attempt-1",
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
            )
        )
        yield Rig(controller, history, events, win, uia, cleanup, config, inserted)


def timeout() -> ThirdPartyError:
    return ThirdPartyError(
        "cleanup", "clean", "private input", ErrorCode.CLEANUP_TIMEOUT
    )


def assert_choice(rig: Rig, run_id: str, record: RunRecord) -> None:
    assert record.status == RunStatus.AWAITING_CLEANUP_CHOICE
    assert record.original_text == RAW and record.adjusted_text == ADJUSTED
    assert record.cleaned_text is None and record.output_selection is None
    assert rig.sends() == 0 and rig.verifications() == 0
    assert rig.states(run_id) == ["recording", "processing", "awaiting_cleanup_choice"]
    recoveries = rig.events.by_name("run:recovery")
    assert len(recoveries) == 1
    assert recoveries[0] == {
        "name": "run:recovery",
        "run_id": run_id,
        "version": record.version,
        "status": "awaiting_cleanup_choice",
        "actions": ["copy", "retry_cleanup", "use_original"],
    }


@pytest.mark.asyncio
async def test_T_RUN_009_cleanup_off_uses_adjusted_text(tmp_path: Path) -> None:
    cleanup = FakeCleanupEngine(CLEANED)
    async with scenario(tmp_path, cleanup=cleanup, enabled=False) as rig:
        run_id, record = await rig.finish()
        assert record.status == RunStatus.DONE
        assert record.cleanup_status == CleanupStatus.OFF
        assert record.output_selection == "adjusted"
        assert cleanup.requests == []
        assert rig.sends() == 1 and rig.uia.texts[(1, 2)] == "before" + ADJUSTED
        assert len(await rig.history.attempts(run_id)) == 1


@pytest.mark.asyncio
async def test_T_RUN_009b_uses_stored_config_after_live_edit(tmp_path: Path) -> None:
    cleanup = FakeCleanupEngine(CLEANED)
    async with scenario(tmp_path, cleanup=cleanup) as rig:
        run_id = await rig.controller.start(start_request_id="start-1")
        rig.config["cleanup_enabled"] = False
        rig.config["cleanup_instructions"] = "changed later"
        rig.inserted[0] = CLEANED
        await rig.controller.stop(run_id)
        record = await rig.controller.settled(run_id)
        assert record.status == RunStatus.DONE
        assert record.config["cleanup_enabled"] is True
        assert cleanup.requests[0].instructions == "Keep the wording"
        assert rig.uia.texts[(1, 2)] == "before" + CLEANED


@pytest.mark.asyncio
async def test_T_RUN_010c_accepted_cleanup_inserts_once(tmp_path: Path) -> None:
    cleanup = FakeCleanupEngine(CLEANED)
    async with scenario(tmp_path, cleanup=cleanup) as rig:
        rig.inserted[0] = CLEANED
        run_id, record = await rig.finish()
        assert record.status == RunStatus.DONE
        assert record.original_text == RAW and record.adjusted_text == ADJUSTED
        assert record.cleaned_text == CLEANED
        assert record.output_selection == "cleaned"
        assert record.cleanup_status == CleanupStatus.OK
        assert record.cleanup_reason is None
        assert len(cleanup.requests) == 1
        assert cleanup.requests[0].text == ADJUSTED
        assert cleanup.requests[0].glossary == ("OpenWhispr",)
        assert cleanup.requests[0].instructions == "Keep the wording"
        assert rig.sends() == 1 and rig.uia.texts[(1, 2)] == "before" + CLEANED
        assert len(await rig.history.attempts(run_id)) == 1


@pytest.mark.asyncio
async def test_T_RUN_010_timeout_offers_choice_without_claim(tmp_path: Path) -> None:
    async with scenario(tmp_path, cleanup=FakeCleanupEngine(timeout())) as rig:
        run_id, record = await rig.finish()
        assert_choice(rig, run_id, record)
        assert record.cleanup_status == CleanupStatus.FAILED
        assert record.cleanup_reason == "cleanup_timeout"
        assert await rig.history.attempts(run_id) == ()


@pytest.mark.asyncio
async def test_T_RUN_010b_unexpected_cleanup_error_uses_fixed_reason(
    tmp_path: Path,
) -> None:
    async with scenario(
        tmp_path, cleanup=FakeCleanupEngine(RuntimeError("private input"))
    ) as rig:
        run_id, record = await rig.finish()
        assert_choice(rig, run_id, record)
        assert record.cleanup_status == CleanupStatus.FAILED
        assert record.cleanup_reason == "cleanup_unavailable"


@pytest.mark.asyncio
async def test_T_RUN_011c_guard_rejects_lost_negation(tmp_path: Path) -> None:
    async with scenario(tmp_path, cleanup=FakeCleanupEngine("do OpenWhispr")) as rig:
        run_id, record = await rig.finish()
        assert_choice(rig, run_id, record)
        assert record.cleanup_status == CleanupStatus.REJECTED
        assert record.cleanup_reason == "negation"
        assert await rig.history.attempts(run_id) == ()


@pytest.mark.asyncio
async def test_T_RUN_011d_missing_engine_offers_choice(tmp_path: Path) -> None:
    async with scenario(tmp_path, cleanup=None) as rig:
        run_id, record = await rig.finish()
        assert_choice(rig, run_id, record)
        assert record.cleanup_status == CleanupStatus.FAILED
        assert record.cleanup_reason == "cleanup_unavailable"


@pytest.mark.asyncio
async def test_T_RUN_012_retry_cleanup_rechecks_and_inserts(tmp_path: Path) -> None:
    cleanup = FakeCleanupEngine(timeout(), CLEANED)
    async with scenario(tmp_path, cleanup=cleanup) as rig:
        run_id, failed = await rig.finish()
        assert_choice(rig, run_id, failed)
        rig.inserted[0] = CLEANED
        await rig.controller.recover(
            run_id, RecoveryAction.RETRY_CLEANUP, expected_version=failed.version
        )
        record = await rig.controller.settled(run_id)
        assert record.status == RunStatus.DONE
        assert record.original_text == RAW and record.adjusted_text == ADJUSTED
        assert record.cleaned_text == CLEANED
        assert record.cleanup_status == CleanupStatus.OK
        assert record.output_selection == "cleaned"
        assert len(cleanup.requests) == 2
        assert cleanup.requests[1].text == ADJUSTED
        assert cleanup.requests[1].instructions == "Keep the wording"
        assert rig.verifications() >= 2
        assert rig.sends() == 1 and rig.uia.texts[(1, 2)] == "before" + CLEANED
        assert len(await rig.history.attempts(run_id)) == 1


@pytest.mark.asyncio
async def test_T_RUN_012b_retry_after_user_switches_awaits_destination(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path, cleanup=FakeCleanupEngine(timeout(), CLEANED)) as rig:
        run_id, failed = await rig.finish()
        rig.win.foreground = 20
        await rig.controller.recover(
            run_id, RecoveryAction.RETRY_CLEANUP, expected_version=failed.version
        )
        record = await rig.controller.settled(run_id)
        assert record.status == RunStatus.AWAITING_DESTINATION
        assert record.cleaned_text == CLEANED
        assert rig.verifications() >= 1
        assert rig.sends() == 0 and await rig.history.attempts(run_id) == ()


@pytest.mark.asyncio
async def test_T_RUN_012c_retry_failure_returns_to_choice(tmp_path: Path) -> None:
    cleanup = FakeCleanupEngine(timeout(), timeout())
    async with scenario(tmp_path, cleanup=cleanup) as rig:
        run_id, failed = await rig.finish()
        await rig.controller.recover(
            run_id, RecoveryAction.RETRY_CLEANUP, expected_version=failed.version
        )
        again = await rig.controller.settled(run_id)
        assert again.status == RunStatus.AWAITING_CLEANUP_CHOICE
        assert again.version > failed.version
        assert again.original_text == RAW and again.adjusted_text == ADJUSTED
        assert again.cleanup_status == CleanupStatus.FAILED
        assert again.cleanup_reason == "cleanup_timeout"
        assert again.cleaned_text is None and again.output_selection is None
        assert len(cleanup.requests) == 2
        assert rig.sends() == 0 and await rig.history.attempts(run_id) == ()
        assert len(rig.events.by_name("run:recovery")) == 2


@pytest.mark.asyncio
async def test_T_RUN_013_use_original_inserts_exact_stt_text(tmp_path: Path) -> None:
    async with scenario(tmp_path, cleanup=FakeCleanupEngine(timeout())) as rig:
        run_id, failed = await rig.finish()
        rig.inserted[0] = RAW
        await rig.controller.recover(
            run_id, RecoveryAction.USE_ORIGINAL, expected_version=failed.version
        )
        record = await rig.controller.settled(run_id)
        assert record.status == RunStatus.DONE
        assert record.original_text == RAW and record.adjusted_text == ADJUSTED
        assert record.output_selection == "original"
        assert rig.sends() == 1 and rig.uia.texts[(1, 2)] == "before" + RAW
        assert len(await rig.history.attempts(run_id)) == 1


@pytest.mark.asyncio
async def test_T_RUN_014_recover_checks_version_then_action(tmp_path: Path) -> None:
    async with scenario(tmp_path, cleanup=FakeCleanupEngine(timeout())) as rig:
        run_id, failed = await rig.finish()
        for action, version, code in (
            (RecoveryAction.USE_ORIGINAL, failed.version - 1, ErrorCode.STALE_VERSION),
            (RecoveryAction.INSERT, failed.version, ErrorCode.VALIDATION),
        ):
            with pytest.raises(WisprError) as raised:
                await rig.controller.recover(run_id, action, expected_version=version)
            assert raised.value.error_code == code
            assert await rig.history.get(run_id) == failed
            assert rig.sends() == 0

    done_path = tmp_path / "done"
    done_path.mkdir()
    async with scenario(done_path, cleanup=FakeCleanupEngine(CLEANED)) as rig:
        rig.inserted[0] = CLEANED
        run_id, done = await rig.finish()
        with pytest.raises(WisprError) as raised:
            await rig.controller.recover(
                run_id, RecoveryAction.RETRY_CLEANUP, expected_version=done.version
            )
        assert raised.value.error_code == ErrorCode.VALIDATION
        assert await rig.history.get(run_id) == done


@pytest.mark.asyncio
async def test_T_RUN_004_cancel_while_cleanup_pending(tmp_path: Path) -> None:
    cleanup = FakeCleanupEngine(CLEANED)
    cleanup.release.clear()
    async with scenario(tmp_path, cleanup=cleanup) as rig:
        run_id = await rig.controller.start(start_request_id="start-1")
        await rig.controller.stop(run_id)
        await cleanup.entered.wait()
        pending = await rig.history.get(run_id)
        assert pending.cleanup_status == CleanupStatus.PENDING
        assert pending.original_text == RAW and pending.adjusted_text == ADJUSTED
        assert pending.output_selection is None
        await rig.controller.cancel(run_id)
        cleanup.release.set()
        record = await rig.controller.settled(run_id)
        assert record.status == RunStatus.CANCELLED
        assert record.cleaned_text is None and rig.sends() == 0
        assert await rig.history.attempts(run_id) == ()


@pytest.mark.asyncio
async def test_T_RUN_015_cancel_choice_without_live_task(tmp_path: Path) -> None:
    async with scenario(tmp_path, cleanup=FakeCleanupEngine(timeout())) as rig:
        run_id, failed = await rig.finish()
        await rig.controller.cancel(run_id)
        cancelled = await rig.history.get(run_id)
        assert cancelled.status == RunStatus.CANCELLED
        assert cancelled.version > failed.version
        assert rig.states(run_id) == [
            "recording",
            "processing",
            "awaiting_cleanup_choice",
            "cancelled",
        ]
        events_before = list(rig.events.events)
        await rig.controller.cancel(run_id)
        assert await rig.history.get(run_id) == cancelled
        assert rig.events.events == events_before
        assert rig.sends() == 0


@pytest.mark.asyncio
async def test_T_RUN_016_cleanup_privacy(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        async with scenario(
            tmp_path, cleanup=FakeCleanupEngine("do OpenWhispr")
        ) as rig:
            _, record = await rig.finish()
            assert record.cleanup_reason == "negation"
            assert RAW not in caplog.text
            assert ADJUSTED not in caplog.text
            assert "do OpenWhispr" not in caplog.text
            assert all(
                private not in record.cleanup_reason
                for private in (RAW, ADJUSTED, "do OpenWhispr")
            )
