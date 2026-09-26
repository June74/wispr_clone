"""Observable run and insertion-attempt persistence contracts."""

import asyncio
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from _support import create, database, repo, wav
from fakes.clock import FakeClock
from fakes.events import FakeEventSink
from fakes.ids import FakeIdFactory

from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.contracts.run import (
    AttemptOutcome,
    CleanupStatus,
    InsertionOutcome,
    RunStatus,
)


def error_code(error: pytest.ExceptionInfo[WisprError], code: ErrorCode) -> None:
    assert error.value.error_code == code
    assert error.value.where == "history"


@pytest.mark.asyncio
@pytest.mark.invariant("eleventh run evicts the oldest without a reentrant callback")
async def test_T_HIS_001_evicts_oldest_and_defers_callback(tmp_path: Path) -> None:
    from wispr_clone.history.repo import HistoryRepo

    clock, events, ids = FakeClock(100), FakeEventSink(), FakeIdFactory()
    callbacks: list[str] = []
    async with database(tmp_path / "history.db") as db:
        history: HistoryRepo = repo(
            db, tmp_path, clock, events, on_run_evicted=callbacks.append
        )
        runs = []
        for _ in range(10):
            run_id = ids.new("run")
            audio = wav(tmp_path / f"{run_id}.wav")
            runs.append(
                await history.create_run(
                    run_id=run_id,
                    start_request_id=ids.new("start"),
                    config={},
                    audio_path=str(audio),
                )
            )
            clock.advance(1)
        events.events.clear()
        latest = await create(history, ids)
        assert callbacks == []
        assert [run.id for run in await history.list_runs()] == [
            latest.id,
            *[run.id for run in reversed(runs[1:])],
        ]
        assert not (tmp_path / f"{runs[0].id}.wav").exists()
        assert [
            (event["reason"], event["run_ids"])
            for event in events.by_name("history:changed")
        ] == [("evicted", [runs[0].id]), ("created", [latest.id])]
        await asyncio.sleep(0)
        assert callbacks == [runs[0].id]


@pytest.mark.asyncio
@pytest.mark.invariant("expiry is checked at access time")
async def test_T_HIS_002_expiry_at_exact_24_hours(tmp_path: Path) -> None:
    from wispr_clone.config import RUN_RETENTION_SECONDS

    clock, events, ids = FakeClock(100), FakeEventSink(), FakeIdFactory()
    async with database(tmp_path / "history.db") as db:
        history = repo(db, tmp_path, clock, events)
        run = await create(history, ids)
        assert history.next_expiry_at() == 100 + RUN_RETENTION_SECONDS
        clock.advance(RUN_RETENTION_SECONDS - 0.001)
        assert (await history.get(run.id)).id == run.id
        clock.advance(0.001)
        with pytest.raises(WisprError) as expired:
            await history.get(run.id)
        error_code(expired, ErrorCode.RUN_EXPIRED)
        with pytest.raises(WisprError) as missing:
            await history.get(run.id)
        error_code(missing, ErrorCode.RUN_NOT_FOUND)
        assert history.next_expiry_at() is None


@pytest.mark.asyncio
@pytest.mark.invariant("access and retry never renew the recording start")
async def test_T_HIS_003_age_never_renews(tmp_path: Path) -> None:
    from wispr_clone.config import RUN_RETENTION_SECONDS

    clock, events, ids = FakeClock(200), FakeEventSink(), FakeIdFactory()
    async with database(tmp_path / "history.db") as db:
        history = repo(db, tmp_path, clock, events)
        run = await create(history, ids)
        clock.advance(100)
        assert (await history.get(run.id)).created_at == 200
        assert (await history.list_runs())[0].created_at == 200
        updated = await history.update_run(
            run.id, expected_version=run.version, status=RunStatus.PROCESSING
        )
        assert updated.created_at == 200
        claim = await history.claim_attempt(
            run.id,
            attempt_id=ids.new("attempt"),
            request_id=ids.new("request"),
            kind="explicit",
        )
        assert claim.attempt.started_at == clock.now()
        await history.resolve_attempt(claim.attempt.attempt_id, AttemptOutcome.FAILED)
        assert (await history.get(run.id)).created_at == 200
        await history.recover_on_startup()
        assert (await history.get(run.id)).created_at == 200
        clock.advance(RUN_RETENTION_SECONDS - 100)
        with pytest.raises(WisprError) as expired:
            await history.get(run.id)
        error_code(expired, ErrorCode.RUN_EXPIRED)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation",
    ["get", "list_runs", "update_run", "claim_attempt", "insertion_outcome"],
)
@pytest.mark.invariant("every access path expires first")
async def test_T_HIS_004_expiry_precedes_access(tmp_path: Path, operation: str) -> None:
    from wispr_clone.config import RUN_RETENTION_SECONDS

    clock, events, ids = FakeClock(0), FakeEventSink(), FakeIdFactory()
    async with database(tmp_path / f"{operation}.db") as db:
        history = repo(db, tmp_path, clock, events)
        run = await create(history, ids)
        clock.advance(RUN_RETENTION_SECONDS)
        if operation == "list_runs":
            assert await history.list_runs() == ()
        else:
            calls = {
                "get": lambda: history.get(run.id),
                "update_run": lambda: history.update_run(
                    run.id, expected_version=1, status=RunStatus.DONE
                ),
                "claim_attempt": lambda: history.claim_attempt(
                    run.id, attempt_id="a", request_id="r", kind="explicit"
                ),
                "insertion_outcome": lambda: history.insertion_outcome(run.id),
            }
            with pytest.raises(WisprError) as expired:
                await calls[operation]()
            error_code(expired, ErrorCode.RUN_EXPIRED)
        assert (
            await db.read(
                lambda conn: conn.execute("SELECT count(*) FROM runs").fetchone()[0]
            )
            == 0
        )


@pytest.mark.asyncio
async def test_T_HIS_007_only_one_automatic_attempt(tmp_path: Path) -> None:
    clock, events, ids = FakeClock(), FakeEventSink(), FakeIdFactory()
    async with database(tmp_path / "history.db") as db:
        history = repo(db, tmp_path, clock, events)
        run = await create(history, ids)
        await history.claim_attempt(
            run.id, attempt_id="a1", request_id="r1", kind="automatic"
        )
        with pytest.raises(WisprError) as duplicate:
            await history.claim_attempt(
                run.id, attempt_id="a2", request_id="r2", kind="automatic"
            )
        error_code(duplicate, ErrorCode.DUPLICATE_REQUEST)
        assert duplicate.value.why == "automatic attempt"
        await history.claim_attempt(
            run.id, attempt_id="a3", request_id="r3", kind="explicit"
        )
        assert [
            (attempt.attempt_id, attempt.kind)
            for attempt in await history.attempts(run.id)
        ] == [("a1", "automatic"), ("a3", "explicit")]


@pytest.mark.asyncio
async def test_T_HIS_008_request_id_is_idempotent_and_run_scoped(
    tmp_path: Path,
) -> None:
    clock, events, ids = FakeClock(), FakeEventSink(), FakeIdFactory()
    async with database(tmp_path / "history.db") as db:
        history = repo(db, tmp_path, clock, events)
        first, second = await create(history, ids), await create(history, ids)
        claimed = await history.claim_attempt(
            first.id, attempt_id="a1", request_id="same", kind="explicit"
        )
        repeated = await history.claim_attempt(
            first.id, attempt_id="unused", request_id="same", kind="explicit"
        )
        assert not claimed.deduplicated
        assert repeated.deduplicated and repeated.attempt == claimed.attempt
        assert len(await history.attempts(first.id)) == 1
        with pytest.raises(WisprError) as wrong_run:
            await history.claim_attempt(
                second.id, attempt_id="a2", request_id="same", kind="explicit"
            )
        error_code(wrong_run, ErrorCode.VALIDATION)
        assert await history.attempts(second.id) == ()


@pytest.mark.asyncio
async def test_T_HIS_009_outcome_uses_highest_sequence_not_timestamp(
    tmp_path: Path,
) -> None:
    clock, events, ids = FakeClock(100), FakeEventSink(), FakeIdFactory()
    async with database(tmp_path / "history.db") as db:
        history = repo(db, tmp_path, clock, events)
        run = await create(history, ids)
        assert await history.insertion_outcome(run.id) == InsertionOutcome.NONE
        await history.claim_attempt(
            run.id, attempt_id="first", request_id="r1", kind="automatic"
        )
        await history.claim_attempt(
            run.id, attempt_id="second", request_id="r2", kind="explicit"
        )
        await history.resolve_attempt("second", AttemptOutcome.UNCERTAIN)
        clock.advance(1)
        await history.resolve_attempt("first", AttemptOutcome.INSERTED)
        assert await history.insertion_outcome(run.id) == InsertionOutcome.UNCERTAIN
        assert [attempt.outcome for attempt in await history.attempts(run.id)] == [
            AttemptOutcome.INSERTED,
            AttemptOutcome.UNCERTAIN,
        ]


@pytest.mark.asyncio
async def test_T_HIS_010_restart_marks_claim_uncertain(tmp_path: Path) -> None:
    clock, events, ids = FakeClock(100), FakeEventSink(), FakeIdFactory()
    path = tmp_path / "history.db"
    async with database(path) as db:
        history = repo(db, tmp_path, clock, events)
        run = await create(history, ids)
        await history.claim_attempt(
            run.id, attempt_id="inflight", request_id="request", kind="automatic"
        )
    async with database(path) as reopened:
        history = repo(reopened, tmp_path, clock, FakeEventSink())
        report = await history.recover_on_startup()
        assert report.in_flight_to_uncertain == ("inflight",)
        assert (await history.attempts(run.id))[0].outcome == AttemptOutcome.UNCERTAIN
        assert await history.insertion_outcome(run.id) == InsertionOutcome.UNCERTAIN
        assert (await history.recover_on_startup()).in_flight_to_uncertain == ()


@pytest.mark.asyncio
async def test_T_HIS_011_restart_fails_pending_cleanup(tmp_path: Path) -> None:
    clock, events, ids = FakeClock(100), FakeEventSink(), FakeIdFactory()
    path = tmp_path / "history.db"
    async with database(path) as db:
        history = repo(db, tmp_path, clock, events)
        run = await create(history, ids)
        processing = await history.update_run(
            run.id, expected_version=run.version, status=RunStatus.PROCESSING
        )
        pending = await history.update_run(
            run.id,
            expected_version=processing.version,
            cleanup_status=CleanupStatus.PENDING,
        )
    async with database(path) as reopened:
        history = repo(reopened, tmp_path, clock, FakeEventSink())
        report = await history.recover_on_startup()
        recovered = await history.get(run.id)
        assert report.pending_cleanup_failed == (run.id,)
        assert recovered.cleanup_status == CleanupStatus.FAILED
        assert recovered.status == RunStatus.AWAITING_CLEANUP_CHOICE
        assert recovered.version == pending.version + 1
        assert (await history.recover_on_startup()).pending_cleanup_failed == ()


@pytest.mark.asyncio
async def test_T_HIS_013_original_is_write_once_even_in_sql(tmp_path: Path) -> None:
    clock, events, ids = FakeClock(), FakeEventSink(), FakeIdFactory()
    path = tmp_path / "history.db"
    async with database(path) as db:
        history = repo(db, tmp_path, clock, events)
        run = await create(history, ids)
        stored = await history.update_run(
            run.id,
            expected_version=1,
            original_text="exact original",
            adjusted_text="different",
        )
        assert (
            stored.original_text == "exact original"
            and stored.adjusted_text == "different"
        )
        with pytest.raises(WisprError) as immutable:
            await history.update_run(
                run.id, expected_version=stored.version, original_text="changed"
            )
        error_code(immutable, ErrorCode.VALIDATION)
        assert immutable.value.why == "original_text"
        with closing(sqlite3.connect(path)) as conn:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE runs SET original_text = ? WHERE id = ?",
                    ("changed", run.id),
                )
        assert (await history.get(run.id)).original_text == "exact original"


@pytest.mark.asyncio
async def test_T_HIS_014_deduplicate_start_validate_and_keep_private_data_out(
    tmp_path: Path,
) -> None:
    clock, events = FakeClock(), FakeEventSink()
    async with database(tmp_path / "history.db") as db:
        history = repo(db, tmp_path, clock, events)
        secret = "private-destination-sentinel"
        run = await history.create_run(
            run_id="first",
            start_request_id="same",
            config={"marker": secret},
            destination={"field": secret},
        )
        events.events.clear()
        repeated = await history.create_run(
            run_id="unused", start_request_id="same", config={"different": True}
        )
        assert repeated == run
        assert len(await history.list_runs()) == 1 and events.events == []
        for field in (
            "unknown_field",
            "id",
            "start_request_id",
            "created_at",
            "version",
            "config",
        ):
            with pytest.raises(WisprError) as invalid:
                await history.update_run(
                    run.id, expected_version=run.version, **{field: secret}
                )
            error_code(invalid, ErrorCode.VALIDATION)
            assert secret not in str(invalid.value) + invalid.value.why
        changed = await history.update_run(
            run.id,
            expected_version=run.version,
            original_text="private-transcript-sentinel",
        )
        with pytest.raises(WisprError) as stale:
            await history.update_run(
                run.id, expected_version=run.version, status=RunStatus.DONE
            )
        error_code(stale, ErrorCode.STALE_VERSION)
        assert changed.version == run.version + 1
        assert all(
            secret not in json.dumps(event)
            and "private-transcript-sentinel" not in json.dumps(event)
            for event in events.events
        )


@pytest.mark.asyncio
async def test_T_HIS_004_claim_rechecks_expiry_inside_write(tmp_path: Path) -> None:
    from wispr_clone.config import RUN_RETENTION_SECONDS
    from wispr_clone.history.repo import HistoryRepo

    clock = FakeClock(0)
    async with database(tmp_path / "history.db") as db:
        history = HistoryRepo(
            db, clock=clock.now, audio_dir=tmp_path, events=FakeEventSink()
        )
        run = await create(history, FakeIdFactory())
        clock.advance(RUN_RETENTION_SECONDS - 0.001)
        real_now = clock.now
        calls = 0

        def crossing_clock() -> float:
            nonlocal calls
            calls += 1
            if calls == 1:
                return real_now()
            clock.advance(0.001)
            return real_now()

        history = HistoryRepo(
            db, clock=crossing_clock, audio_dir=tmp_path, events=FakeEventSink()
        )
        with pytest.raises(WisprError) as expired:
            await history.claim_attempt(
                run.id, attempt_id="late", request_id="late-request", kind="automatic"
            )
        error_code(expired, ErrorCode.RUN_EXPIRED)
        assert await history.attempts(run.id) == ()
        assert (
            await db.read(
                lambda conn: conn.execute("SELECT count(*) FROM runs").fetchone()[0]
            )
            == 0
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "invalid"),
    [("status", "invalid-status"), ("cleanup_status", "invalid-cleanup")],
)
async def test_T_HIS_014_bad_lifecycle_enum_rejected_without_write(
    tmp_path: Path, field: str, invalid: str
) -> None:
    clock, events, ids = FakeClock(), FakeEventSink(), FakeIdFactory()
    async with database(tmp_path / "history.db") as db:
        history = repo(db, tmp_path, clock, events)
        run = await create(history, ids)
        events.events.clear()
        with pytest.raises(WisprError) as rejected:
            await history.update_run(
                run.id, expected_version=run.version, **{field: invalid}
            )
        error_code(rejected, ErrorCode.VALIDATION)
        assert await history.get(run.id) == run
        assert events.events == []


@pytest.mark.asyncio
async def test_T_HIS_015_corrupt_attempt_target_is_storage_error(
    tmp_path: Path,
) -> None:
    clock, events, ids = FakeClock(), FakeEventSink(), FakeIdFactory()
    async with database(tmp_path / "history.db") as db:
        history = repo(db, tmp_path, clock, events)
        run = await create(history, ids)
        await history.claim_attempt(
            run.id, attempt_id="attempt", request_id="request", kind="explicit"
        )
        await db.write(
            lambda conn: conn.execute(
                "UPDATE insertion_attempts SET target=? WHERE attempt_id=?",
                ("{broken-json", "attempt"),
            )
        )
        with pytest.raises(WisprError) as corrupt:
            await history.attempts(run.id)
        error_code(corrupt, ErrorCode.STORAGE_ERROR)
        assert "broken-json" not in str(corrupt.value) + corrupt.value.why
