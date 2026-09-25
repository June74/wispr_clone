"""T-HIS-016: an in-flight insertion protects its run from retention."""

import asyncio
from pathlib import Path

import pytest
from _support import create, database, repo
from fakes.clock import FakeClock
from fakes.events import FakeEventSink
from fakes.ids import FakeIdFactory

from wispr_clone.config import RUN_RETENTION_SECONDS
from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.contracts.run import AttemptOutcome


@pytest.mark.asyncio
@pytest.mark.invariant("an in-flight attempt protects its run from count eviction")
async def test_T_HIS_016_evicts_oldest_unprotected_run(tmp_path: Path) -> None:
    clock, events, ids = FakeClock(100), FakeEventSink(), FakeIdFactory()
    callbacks: list[str] = []
    callback_fired = asyncio.Event()

    def on_run_evicted(run_id: str) -> None:
        callbacks.append(run_id)
        callback_fired.set()

    async with database(tmp_path / "history.db") as db:
        history = repo(db, tmp_path, clock, events, on_run_evicted=on_run_evicted)
        runs = []
        for _ in range(10):
            runs.append(await create(history, ids))
            clock.advance(1)
        claim = await history.claim_attempt(
            runs[0].id,
            attempt_id="protected-attempt",
            request_id="protected-request",
            kind="automatic",
        )
        assert claim.attempt.outcome == AttemptOutcome.IN_FLIGHT
        events.events.clear()

        newest = await create(history, ids)

        assert callbacks == []
        assert [run.id for run in await history.list_runs()] == [
            newest.id,
            *[run.id for run in reversed(runs[2:])],
            runs[0].id,
        ]
        assert await history.attempts(runs[0].id) == (claim.attempt,)
        assert await history.attempts(runs[1].id) == ()
        assert [
            (event["reason"], event["run_ids"])
            for event in events.by_name("history:changed")
        ] == [("evicted", [runs[1].id]), ("created", [newest.id])]
        await asyncio.wait_for(callback_fired.wait(), timeout=1)
        assert callbacks == [runs[1].id]


@pytest.mark.asyncio
@pytest.mark.invariant("expiry resumes after an in-flight attempt resolves")
async def test_T_HIS_016_defers_expiry_until_attempt_resolves(tmp_path: Path) -> None:
    clock, events, ids = FakeClock(100), FakeEventSink(), FakeIdFactory()
    callbacks: list[str] = []
    callback_fired = asyncio.Event()

    def on_run_evicted(run_id: str) -> None:
        callbacks.append(run_id)
        callback_fired.set()

    async with database(tmp_path / "history.db") as db:
        history = repo(db, tmp_path, clock, events, on_run_evicted=on_run_evicted)
        protected = await create(history, ids)
        await history.claim_attempt(
            protected.id,
            attempt_id="in-flight",
            request_id="request",
            kind="automatic",
        )
        clock.advance(60)
        later = await create(history, ids)
        assert history.next_expiry_at() == later.created_at + RUN_RETENTION_SECONDS

        clock.advance(RUN_RETENTION_SECONDS - 60)
        assert (await history.get(protected.id)).id == protected.id
        assert (await history.attempts(protected.id))[0].outcome == (
            AttemptOutcome.IN_FLIGHT
        )
        assert history.next_expiry_at() == later.created_at + RUN_RETENTION_SECONDS
        assert callbacks == []

        await history.resolve_attempt("in-flight", AttemptOutcome.INSERTED)
        events.events.clear()
        with pytest.raises(WisprError) as expired:
            await history.get(protected.id)
        assert expired.value.error_code == ErrorCode.RUN_EXPIRED
        assert callbacks == []
        assert [run.id for run in await history.list_runs()] == [later.id]
        with pytest.raises(WisprError) as missing:
            await history.get(protected.id)
        assert missing.value.error_code == ErrorCode.RUN_NOT_FOUND
        assert [
            (event["reason"], event["run_ids"])
            for event in events.by_name("history:changed")
        ] == [("expired", [protected.id])]
        await asyncio.wait_for(callback_fired.wait(), timeout=1)
        assert callbacks == [protected.id]


@pytest.mark.asyncio
@pytest.mark.invariant("startup recovery releases in-flight expiry protection")
async def test_T_HIS_016_recovery_expires_uncertain_attempt_run(
    tmp_path: Path,
) -> None:
    clock, events, ids = FakeClock(100), FakeEventSink(), FakeIdFactory()
    db_path = tmp_path / "history.db"
    async with database(db_path) as db:
        history = repo(db, tmp_path, clock, events)
        run = await create(history, ids)
        await history.claim_attempt(
            run.id,
            attempt_id="recovered-attempt",
            request_id="recovered-request",
            kind="automatic",
        )
        clock.advance(RUN_RETENTION_SECONDS)
        assert await history.enforce_retention() == ()
        assert (await history.attempts(run.id))[0].outcome == (AttemptOutcome.IN_FLIGHT)

    async with database(db_path) as reopened:
        history = repo(reopened, tmp_path, clock, FakeEventSink())
        report = await history.recover_on_startup()
        assert report.in_flight_to_uncertain == ("recovered-attempt",)
        assert report.expired == (run.id,)
        assert await history.list_runs() == ()
        assert await history.attempts(run.id) == ()
        assert (
            await reopened.read(
                lambda conn: conn.execute(
                    "SELECT count(*) FROM insertion_attempts WHERE attempt_id = ?",
                    ("recovered-attempt",),
                ).fetchone()[0]
            )
            == 0
        )
