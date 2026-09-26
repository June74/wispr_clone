"""WO-M2 protocol behavior against real temporary history storage."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fakes.clock import FakeClock
from fakes.events import FakeEventSink
from fakes.ids import FakeIdFactory
from fakes.insertion import FakeUiaApi, FakeWin32Api
from wispr_clone.pipeline.insertion_protocol import (
    InsertionProtocol,
    ProtocolOutcome,
    WaitingRun,
)

from wispr_clone.contracts.run import AttemptOutcome
from wispr_clone.history.repo import HistoryRepo
from wispr_clone.insertion.destination import DestinationSnapshot, capture
from wispr_clone.storage import Connection, Database, Migration


def _settings(conn: Connection) -> None:
    conn.execute("CREATE TABLE settings (id TEXT PRIMARY KEY, value TEXT NOT NULL)")


def _dictionary(conn: Connection) -> None:
    conn.execute(
        "CREATE TABLE dictionary_entries (id TEXT PRIMARY KEY, word TEXT NOT NULL)"
    )


def _database(path: Path) -> Database:
    from wispr_clone.storage.migrations import m001_base, m004_history

    return Database(
        path,
        [
            Migration(m001_base.VERSION, m001_base.NAME, m001_base.apply),
            Migration(2, "settings_test_placeholder", _settings),
            Migration(3, "dictionary_test_placeholder", _dictionary),
            Migration(m004_history.VERSION, m004_history.NAME, m004_history.apply),
        ],
    )


async def _inline(call: Callable[[], Any]) -> Any:
    return call()


@dataclass
class Scenario:
    history: HistoryRepo
    protocol: InsertionProtocol
    clock: FakeClock
    win: FakeWin32Api
    uia: FakeUiaApi
    snapshot: DestinationSnapshot
    ids: FakeIdFactory
    run_id: str

    async def attempt(
        self,
        *,
        request_id: str = "request-1",
        kind: str = "automatic",
        cancelled: Callable[[], bool] = lambda: False,
    ) -> Any:
        return await self.protocol.attempt(
            self.run_id,
            "PRIVATE TRANSCRIPT",
            self.snapshot,
            request_id=request_id,
            kind=kind,
            is_cancelled=cancelled,
        )

    def waiting(self, *, since: float | None = None) -> WaitingRun:
        return WaitingRun(
            self.run_id,
            "PRIVATE TRANSCRIPT",
            self.snapshot,
            "request-1",
            self.clock.now() if since is None else since,
        )

    def sends(self) -> int:
        return sum(name == "send_inputs" for name, _, _ in self.win.calls)

    def jump_calls(self) -> int:
        return sum(name == "set_foreground" for name, _, _ in self.win.calls)


@asynccontextmanager
async def scenario(path: Path) -> AsyncIterator[Scenario]:
    clock, ids = FakeClock(100), FakeIdFactory()
    win, uia = FakeWin32Api(), FakeUiaApi()
    snapshot = capture(win, uia)
    win.calls.clear()
    uia.calls.clear()
    async with _database(path / "history.db") as db:
        history = HistoryRepo(
            db, clock=clock.now, audio_dir=path, events=FakeEventSink()
        )
        run_id = ids.new("run")
        await history.create_run(
            run_id=run_id,
            start_request_id=ids.new("start"),
            config={},
            destination=snapshot.to_json(),
        )
        protocol = InsertionProtocol(
            history,
            win,
            uia,
            offload=_inline,
            clock=clock.now,
            new_id=lambda: ids.new("attempt"),
            bring_forward_settle_s=0.0,
            paste_settle_s=0.0,
        )
        yield Scenario(history, protocol, clock, win, uia, snapshot, ids, run_id)


def _confirm(s: Scenario) -> None:
    s.win.on_send = lambda: s.uia.texts.__setitem__((1, 2), "beforePRIVATE TRANSCRIPT")


@pytest.mark.asyncio
async def test_T_PRO_001_claim_failure_sends_no_input(tmp_path: Path) -> None:
    async with scenario(tmp_path) as s:
        s.history.claim_attempt = AsyncMock(side_effect=OSError("disk failed"))  # type: ignore[method-assign]
        result = await s.attempt()
        assert (result.outcome, result.reason, result.attempt_id) == (
            ProtocolOutcome.HELD,
            "claim failed",
            None,
        )
        assert s.sends() == 0
        assert await s.history.attempts(s.run_id) == ()


@pytest.mark.asyncio
async def test_T_PRO_002_final_cancel_resolves_claim(tmp_path: Path) -> None:
    async with scenario(tmp_path) as s:
        checks = iter((False, True))
        result = await s.attempt(cancelled=lambda: next(checks))
        assert (result.outcome, result.reason) == (
            ProtocolOutcome.CANCELLED,
            "cancelled",
        )
        assert s.sends() == 0
        assert (await s.history.attempts(s.run_id))[
            0
        ].outcome == AttemptOutcome.CANCELLED


@pytest.mark.asyncio
async def test_T_PRO_003_changed_destination_has_no_claim(tmp_path: Path) -> None:
    async with scenario(tmp_path) as s:
        s.win.foreground = 20
        result = await s.attempt()
        assert (result.outcome, result.reason) == (
            ProtocolOutcome.AWAITING,
            "window changed",
        )
        assert result.attempt_id is None
        assert await s.history.attempts(s.run_id) == ()
        assert s.sends() == 0


@pytest.mark.asyncio
async def test_T_PRO_004_same_request_dispatches_once(tmp_path: Path) -> None:
    async with scenario(tmp_path) as s:
        _confirm(s)
        first = await s.attempt()
        second = await s.attempt()
        assert first.outcome == ProtocolOutcome.INSERTED
        assert (second.outcome, second.reason, second.attempt_id) == (
            ProtocolOutcome.DUPLICATE,
            "duplicate request",
            first.attempt_id,
        )
        assert s.sends() == 1
        assert len(await s.history.attempts(s.run_id)) == 1


@pytest.mark.asyncio
async def test_T_PRO_006_dispatch_error_is_uncertain_without_retry(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as s:
        s.win.send_error = RuntimeError("PRIVATE TRANSCRIPT")
        result = await s.attempt()
        assert (result.outcome, result.reason) == (
            ProtocolOutcome.UNCERTAIN,
            "dispatch error",
        )
        assert (await s.history.attempts(s.run_id))[
            0
        ].outcome == AttemptOutcome.UNCERTAIN
        assert s.sends() == 1


@pytest.mark.asyncio
async def test_T_PRO_006b_confirmation_mismatch_and_zero_events(tmp_path: Path) -> None:
    async with scenario(tmp_path) as s:
        mismatch = await s.attempt()
        assert (mismatch.outcome, mismatch.reason) == (
            ProtocolOutcome.UNCERTAIN,
            "not confirmed",
        )
        assert (await s.history.attempts(s.run_id))[
            0
        ].outcome == AttemptOutcome.UNCERTAIN
        s.win.accepted = 0
        zero = await s.attempt(request_id="request-2", kind="explicit")
        assert (zero.outcome, zero.reason) == (ProtocolOutcome.FAILED, "no events")
        assert (await s.history.attempts(s.run_id))[1].outcome == AttemptOutcome.FAILED
        assert s.sends() == 2


@pytest.mark.asyncio
async def test_T_PRO_007_explicit_retry_after_uncertain(tmp_path: Path) -> None:
    async with scenario(tmp_path) as s:
        first = await s.attempt()
        assert first.outcome == ProtocolOutcome.UNCERTAIN
        _confirm(s)
        second = await s.attempt(request_id="request-2", kind="explicit")
        assert second.outcome == ProtocolOutcome.INSERTED
        assert second.attempt_id != first.attempt_id
        assert s.sends() == 2
        assert len(await s.history.attempts(s.run_id)) == 2


@pytest.mark.asyncio
async def test_T_PRO_008_expiry_at_final_recheck_abandons(tmp_path: Path) -> None:
    from wispr_clone.config import RUN_RETENTION_SECONDS

    async with scenario(tmp_path) as s:
        original = s.history.get

        async def expire_then_get(run_id: str) -> Any:
            s.clock.advance(RUN_RETENTION_SECONDS)
            return await original(run_id)

        s.history.get = expire_then_get  # type: ignore[method-assign]
        result = await s.attempt()
        assert (result.outcome, result.reason) == (ProtocolOutcome.ABANDONED, "expired")
        assert s.sends() == 0
        assert await s.history.attempts(s.run_id) == ()


@pytest.mark.asyncio
async def test_T_PRO_009_idle_threshold_controls_jump(tmp_path: Path) -> None:
    async with scenario(tmp_path) as s:
        s.win.foreground = 20
        s.win.idle_values = [999, 1000, 1000, 1000]
        first = await s.protocol.deliver_next(
            [s.waiting()], is_cancelled=lambda _: False
        )
        assert first is not None and first[1].outcome == ProtocolOutcome.AWAITING
        assert s.jump_calls() == 0
        _confirm(s)
        second = await s.protocol.deliver_next(
            [s.waiting()], is_cancelled=lambda _: False
        )
        assert second is not None and second[1].outcome == ProtocolOutcome.INSERTED
        assert s.jump_calls() >= 2


@pytest.mark.asyncio
async def test_T_PRO_010_input_after_jump_restores_without_claim(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as s:
        s.win.foreground = 20
        s.win.idle_values = [1500, 1500, 0]
        result = await s.protocol.deliver_next(
            [s.waiting()], is_cancelled=lambda _: False
        )
        assert result is not None
        assert (result[1].outcome, result[1].reason) == (
            ProtocolOutcome.AWAITING,
            "input during jump",
        )
        assert s.win.foreground == 20
        assert s.uia.tabs[20] == (20, 1)
        assert await s.history.attempts(s.run_id) == ()
        assert s.sends() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("send_error", [False, True])
async def test_T_PRO_011_idle_jump_always_restores(
    tmp_path: Path, send_error: bool
) -> None:
    async with scenario(tmp_path) as s:
        s.win.foreground = 20
        s.win.idle_values = [1500] * 8
        if send_error:
            s.win.send_error = RuntimeError("PRIVATE TRANSCRIPT")
        else:
            _confirm(s)
        result = await s.protocol.deliver_next(
            [s.waiting()], is_cancelled=lambda _: False
        )
        assert result is not None
        assert result[1].outcome == (
            ProtocolOutcome.UNCERTAIN if send_error else ProtocolOutcome.INSERTED
        )
        assert s.win.foreground == 20
        assert s.uia.tabs[20] == (20, 1)
        assert s.sends() == 1


@pytest.mark.asyncio
async def test_T_PRO_012_return_trigger_deduplicates(tmp_path: Path) -> None:
    async with scenario(tmp_path) as s:
        _confirm(s)
        s.win.idle_values = [300, 300]
        waiting = s.waiting()
        first = await s.protocol.deliver_next([waiting], is_cancelled=lambda _: False)
        second = await s.protocol.deliver_next([waiting], is_cancelled=lambda _: False)
        assert first is not None and first[1].outcome == ProtocolOutcome.INSERTED
        assert second is not None
        assert (second[1].outcome, second[1].reason) == (
            ProtocolOutcome.DUPLICATE,
            "duplicate request",
        )
        assert second[1].attempt_id == first[1].attempt_id
        assert s.sends() == 1
        assert s.jump_calls() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "reason"),
    [
        ("closed", "window closed"),
        ("unverifiable", "unverifiable"),
        ("limit", "wait limit"),
    ],
)
async def test_T_PRO_013_waiting_hold_conditions(
    tmp_path: Path, state: str, reason: str
) -> None:
    async with scenario(tmp_path) as s:
        if state == "closed":
            s.win.windows.remove(10)
        elif state == "unverifiable":
            s.uia.visible[(1, 2)] = False
        else:
            s.clock.advance(601)
        result = await s.protocol.deliver_next(
            [s.waiting(since=100)], is_cancelled=lambda _: False
        )
        assert result is not None
        assert (result[1].outcome, result[1].reason) == (ProtocolOutcome.HELD, reason)
        assert await s.history.attempts(s.run_id) == ()
        assert s.sends() == 0


@pytest.mark.asyncio
async def test_T_PRO_014_oldest_only_per_tick(tmp_path: Path) -> None:
    async with scenario(tmp_path) as s:
        _confirm(s)
        second = await s.history.create_run(
            run_id="run-2", start_request_id="start-2", config={}
        )
        third = await s.history.create_run(
            run_id="run-3", start_request_id="start-3", config={}
        )
        newer = WaitingRun(s.run_id, "PRIVATE TRANSCRIPT", s.snapshot, "r1", 30)
        oldest = WaitingRun(second.id, "PRIVATE TRANSCRIPT", s.snapshot, "r2", 10)
        middle = WaitingRun(third.id, "PRIVATE TRANSCRIPT", s.snapshot, "r3", 20)
        s.clock.advance(0)
        first = await s.protocol.deliver_next(
            [newer, middle, oldest], is_cancelled=lambda _: False
        )
        assert first is not None and first[0] == oldest.run_id
        assert s.sends() == 1
        assert await s.history.attempts(newer.run_id) == ()
        assert await s.history.attempts(middle.run_id) == ()
        s.uia.texts[(1, 2)] = "before"
        next_result = await s.protocol.deliver_next(
            [newer, middle], is_cancelled=lambda _: False
        )
        assert next_result is not None and next_result[0] == middle.run_id
        assert s.sends() == 2
        assert await s.history.attempts(newer.run_id) == ()


@pytest.mark.asyncio
async def test_T_PRO_015_cancelled_while_awaiting(tmp_path: Path) -> None:
    async with scenario(tmp_path) as s:
        s.win.foreground = 20
        result = await s.protocol.deliver_next(
            [s.waiting()], is_cancelled=lambda _: True
        )
        assert result is not None
        assert (result[1].outcome, result[1].reason) == (
            ProtocolOutcome.CANCELLED,
            "cancelled",
        )
        assert await s.history.attempts(s.run_id) == ()
        assert s.sends() == 0


@pytest.mark.asyncio
async def test_T_PRO_016_concurrent_calls_share_one_slot(tmp_path: Path) -> None:
    async with scenario(tmp_path) as s:
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def gated(call: Callable[[], Any]) -> Any:
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                await release.wait()
            return call()

        s.protocol = InsertionProtocol(
            s.history,
            s.win,
            s.uia,
            offload=gated,
            clock=s.clock.now,
            new_id=lambda: s.ids.new("attempt"),
            paste_settle_s=0.0,
        )
        first = asyncio.create_task(s.attempt(request_id="r1"))
        await entered.wait()
        second = asyncio.create_task(s.attempt(request_id="r2", kind="explicit"))
        await asyncio.sleep(0)
        assert calls == 1
        assert s.win.calls == []
        release.set()
        await first
        await second
        assert calls > 1
        assert s.sends() == 2


@pytest.mark.asyncio
async def test_T_PRO_017_private_content_absent_from_logs_and_reason(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async with scenario(tmp_path) as s:
        s.win.send_error = RuntimeError("PRIVATE TRANSCRIPT PRIVATE TITLE")
        with caplog.at_level(logging.DEBUG):
            result = await s.attempt()
        assert result.reason == "dispatch error"
        assert "PRIVATE TRANSCRIPT" not in caplog.text + result.reason
        assert "PRIVATE TITLE" not in caplog.text + result.reason
