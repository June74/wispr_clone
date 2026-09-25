"""Transactional repository for temporary runs and insertion attempts."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.contracts.events import EventSink, HistoryChangedEvent
from wispr_clone.contracts.run import (
    AttemptOutcome,
    CleanupStatus,
    InsertionOutcome,
    RunStatus,
)
from wispr_clone.history.retention import (
    MAX_RUNS,
    expires_at,
    is_expired,
)
from wispr_clone.storage import Connection, Database, IntegrityError


@dataclass(frozen=True, slots=True)
class RunRecord:
    """Persisted run state, including opaque destination and configuration data."""

    id: str
    start_request_id: str
    created_at: float
    version: int
    status: RunStatus
    awaiting_since: float | None
    audio_path: str | None
    audio_duration: float | None
    original_text: str | None
    adjusted_text: str | None
    cleaned_text: str | None
    output_selection: str | None
    cleanup_status: CleanupStatus
    cleanup_reason: str | None
    destination: dict[str, object] | None
    error_code: str | None
    config: dict[str, object]


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    """One claimed insertion operation and its latest known outcome."""

    attempt_id: str
    run_id: str
    request_id: str
    kind: str
    target: dict[str, object] | None
    started_at: float
    completed_at: float | None
    outcome: AttemptOutcome


@dataclass(frozen=True, slots=True)
class ClaimResult:
    attempt: AttemptRecord
    deduplicated: bool


@dataclass(frozen=True, slots=True)
class DeleteResult:
    run_ids: tuple[str, ...]
    audio_pending: bool


@dataclass(frozen=True, slots=True)
class StartupReport:
    in_flight_to_uncertain: tuple[str, ...]
    pending_cleanup_failed: tuple[str, ...]
    expired: tuple[str, ...]
    deleted_orphan_wavs: int
    pending_deletions_left: int


UPDATABLE_FIELDS = frozenset(
    {
        "status",
        "awaiting_since",
        "audio_path",
        "audio_duration",
        "original_text",
        "adjusted_text",
        "cleaned_text",
        "output_selection",
        "cleanup_status",
        "cleanup_reason",
        "destination",
        "error_code",
    }
)
_IMMUTABLE_FIELDS = frozenset(
    {"id", "start_request_id", "created_at", "version", "config"}
)


def _unlink(path: Path) -> None:
    path.unlink(missing_ok=True)


class HistoryRepo:
    """Store history atomically and perform filesystem cleanup after commits."""

    def __init__(
        self,
        db: Database,
        *,
        clock: Callable[[], float],
        audio_dir: Path,
        events: EventSink,
        on_run_evicted: Callable[[str], None] | None = None,
        remove_file: Callable[[Path], None] = _unlink,
    ) -> None:
        self._db = db
        self._clock = clock
        self._audio_dir = audio_dir
        self._events = events
        self._on_run_evicted = on_run_evicted
        self._remove_file = remove_file
        self._next_expiry: float | None = None

    async def create_run(
        self,
        *,
        run_id: str,
        start_request_id: str,
        config: Mapping[str, object],
        destination: Mapping[str, object] | None = None,
        audio_path: str | None = None,
    ) -> RunRecord:
        now = self._clock()
        config_json = _json(config)
        destination_json = _json(destination) if destination is not None else None

        def create(
            conn: Connection,
        ) -> tuple[
            RunRecord, list[tuple[str, tuple[str, ...]]], list[str], list[str], bool
        ]:
            expired = _expire(conn, now)
            existing = conn.execute(
                "SELECT * FROM runs WHERE start_request_id = ?", (start_request_id,)
            ).fetchone()
            if existing is not None:
                expiry_groups = [("expired", tuple(expired))] if expired else []
                return _run(existing), expiry_groups, expired, [], True
            rows = conn.execute(
                "SELECT r.id, r.created_at FROM runs r WHERE NOT EXISTS "
                "(SELECT 1 FROM insertion_attempts a "
                "WHERE a.run_id=r.id AND a.outcome=?) "
                "ORDER BY r.created_at, r.id",
                (AttemptOutcome.IN_FLIGHT.value,),
            ).fetchall()
            live_count = int(conn.execute("SELECT count(*) FROM runs").fetchone()[0])
            count = min(len(rows), max(0, live_count + 1 - MAX_RUNS))
            evicted = [str(row[0]) for row in rows[:count]]
            _delete_rows(conn, evicted)
            conn.execute(
                "INSERT INTO runs (id,start_request_id,created_at,version,status,"
                "audio_path,original_text,cleanup_status, destination,config) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    start_request_id,
                    now,
                    1,
                    RunStatus.RECORDING.value,
                    audio_path,
                    None,
                    CleanupStatus.OFF.value,
                    destination_json,
                    config_json,
                ),
            )
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            assert row is not None
            groups: list[tuple[str, tuple[str, ...]]] = []
            if expired:
                groups.append(("expired", tuple(expired)))
            if evicted:
                groups.append(("evicted", tuple(evicted)))
            groups.append(("created", (run_id,)))
            return _run(row), groups, expired, evicted, False

        record, groups, expired, evicted, duplicate = await self._db.write(create)
        self._publish(groups)
        await self._remove_paths(
            await self._pending_paths_for_ids((*expired, *evicted))
        )
        await self._refresh_next_expiry()
        self._defer_evictions((*expired, *evicted))
        if duplicate:
            return record
        return record

    async def get(self, run_id: str) -> RunRecord:
        rows = await self._expire_first()
        if run_id in rows:
            raise _error(ErrorCode.RUN_EXPIRED, "run")
        row = await self._db.read(
            lambda conn: conn.execute(
                "SELECT * FROM runs WHERE id=?", (run_id,)
            ).fetchone()
        )
        if row is None:
            raise _error(ErrorCode.RUN_NOT_FOUND, "run")
        return _run(row)

    async def list_runs(self) -> tuple[RunRecord, ...]:
        await self._expire_first()
        rows = await self._db.read(
            lambda conn: conn.execute(
                "SELECT * FROM runs ORDER BY created_at DESC, id DESC"
            ).fetchall()
        )
        return tuple(_run(row) for row in rows)

    async def update_run(
        self, run_id: str, *, expected_version: int, **fields: object
    ) -> RunRecord:
        expired = await self._expire_first()
        if run_id in expired:
            raise _error(ErrorCode.RUN_EXPIRED, "run")
        invalid = set(fields) - UPDATABLE_FIELDS
        if invalid or set(fields) & _IMMUTABLE_FIELDS:
            raise _error(
                ErrorCode.VALIDATION,
                next(
                    iter(sorted(invalid | (set(fields) & _IMMUTABLE_FIELDS))), "field"
                ),
            )
        if not fields:
            return await self.get(run_id)
        values = dict(fields)
        for key in ("status", "cleanup_status"):
            if key == "status" and isinstance(values.get(key), RunStatus):
                values[key] = cast(RunStatus, values[key]).value
            if key == "cleanup_status" and isinstance(values.get(key), CleanupStatus):
                values[key] = cast(CleanupStatus, values[key]).value
        for key, enum_type in (
            ("status", RunStatus),
            ("cleanup_status", CleanupStatus),
        ):
            if key in values:
                try:
                    values[key] = enum_type(cast(str, values[key])).value
                except (TypeError, ValueError):
                    raise _error(ErrorCode.VALIDATION, key) from None
        if "output_selection" in values and values["output_selection"] not in (
            None,
            "original",
            "adjusted",
            "cleaned",
        ):
            raise _error(ErrorCode.VALIDATION, "output_selection")
        if "destination" in values:
            values["destination"] = (
                _json(values["destination"])
                if values["destination"] is not None
                else None
            )

        def update(conn: Connection) -> RunRecord:
            row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise _error(ErrorCode.RUN_NOT_FOUND, "run")
            current = _run(row)
            if current.version != expected_version:
                raise _error(ErrorCode.STALE_VERSION, "version")
            if (
                "original_text" in values
                and current.original_text is not None
                and values["original_text"] != current.original_text
            ):
                raise _error(ErrorCode.VALIDATION, "original_text")
            assignments = ", ".join(f"{key} = ?" for key in values)
            try:
                conn.execute(
                    f"UPDATE runs SET {assignments}, "
                    "version = version + 1 WHERE id = ?",
                    (*values.values(), run_id),
                )
            except IntegrityError:
                raise _error(ErrorCode.VALIDATION, "original_text") from None
            updated = conn.execute(
                "SELECT * FROM runs WHERE id=?", (run_id,)
            ).fetchone()
            assert updated is not None
            return _run(updated)

        updated = await self._db.write(update)
        self._publish([("updated", (run_id,))])
        await self._refresh_next_expiry()
        return updated

    async def claim_attempt(
        self,
        run_id: str,
        *,
        attempt_id: str,
        request_id: str,
        kind: str,
        target: Mapping[str, object] | None = None,
    ) -> ClaimResult:
        expired = await self._expire_first()
        if run_id in expired:
            raise _error(ErrorCode.RUN_EXPIRED, "run")
        target_json = _json(target) if target is not None else None

        def claim(conn: Connection) -> tuple[ClaimResult | None, tuple[str, ...]]:
            expired_inside = tuple(_expire(conn, self._clock()))
            if run_id in expired_inside:
                return None, expired_inside
            run = conn.execute("SELECT id FROM runs WHERE id=?", (run_id,)).fetchone()
            if run is None:
                raise _error(ErrorCode.RUN_NOT_FOUND, "run")
            existing = conn.execute(
                "SELECT * FROM insertion_attempts WHERE request_id=?", (request_id,)
            ).fetchone()
            if existing is not None:
                if existing[1] != run_id:
                    raise _error(ErrorCode.VALIDATION, "request_id")
                return ClaimResult(_attempt(existing), True), expired_inside
            if kind not in ("automatic", "explicit"):
                raise _error(ErrorCode.VALIDATION, "kind")
            seq = int(
                conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 FROM insertion_attempts"
                ).fetchone()[0]
            )
            try:
                conn.execute(
                    "INSERT INTO insertion_attempts "
                    "(attempt_id,run_id,request_id,kind,target,started_at,"
                    "completed_at,outcome,seq) VALUES (?,?,?,?,?,?,NULL,?,?)",
                    (
                        attempt_id,
                        run_id,
                        request_id,
                        kind,
                        target_json,
                        self._clock(),
                        AttemptOutcome.IN_FLIGHT.value,
                        seq,
                    ),
                )
            except IntegrityError:
                if kind == "automatic":
                    raise _error(
                        ErrorCode.DUPLICATE_REQUEST, "automatic attempt"
                    ) from None
                raise _error(ErrorCode.VALIDATION, "attempt") from None
            row = conn.execute(
                "SELECT * FROM insertion_attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            assert row is not None
            return ClaimResult(_attempt(row), False), expired_inside

        result, expired_inside = await self._db.write(claim)
        if expired_inside:
            self._publish([("expired", expired_inside)])
            await self._remove_paths(await self._pending_paths_for_ids(expired_inside))
            self._defer_evictions(expired_inside)
        if result is None:
            await self._refresh_next_expiry()
            raise _error(ErrorCode.RUN_EXPIRED, "run")
        await self._refresh_next_expiry()
        return result

    async def resolve_attempt(
        self, attempt_id: str, outcome: AttemptOutcome
    ) -> AttemptRecord:
        def resolve(conn: Connection) -> AttemptRecord:
            row = conn.execute(
                "SELECT * FROM insertion_attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            if row is None:
                raise _error(ErrorCode.RUN_NOT_FOUND, "attempt")
            if row[7] != AttemptOutcome.IN_FLIGHT.value:
                raise _error(ErrorCode.VALIDATION, "attempt outcome")
            conn.execute(
                "UPDATE insertion_attempts SET outcome=?, completed_at=? "
                "WHERE attempt_id=?",
                (outcome.value, self._clock(), attempt_id),
            )
            updated = conn.execute(
                "SELECT * FROM insertion_attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            assert updated is not None
            return _attempt(updated)

        result = await self._db.write(resolve)
        await self._refresh_next_expiry()
        return result

    async def attempts(self, run_id: str) -> tuple[AttemptRecord, ...]:
        rows = await self._db.read(
            lambda conn: conn.execute(
                "SELECT * FROM insertion_attempts WHERE run_id=? ORDER BY seq",
                (run_id,),
            ).fetchall()
        )
        return tuple(_attempt(row) for row in rows)

    async def insertion_outcome(self, run_id: str) -> InsertionOutcome:
        expired = await self._expire_first()
        if run_id in expired:
            raise _error(ErrorCode.RUN_EXPIRED, "run")

        def read(conn: Connection) -> InsertionOutcome:
            if (
                conn.execute("SELECT 1 FROM runs WHERE id=?", (run_id,)).fetchone()
                is None
            ):
                raise _error(ErrorCode.RUN_NOT_FOUND, "run")
            row = conn.execute(
                "SELECT outcome FROM insertion_attempts WHERE run_id=? "
                "ORDER BY seq DESC LIMIT 1",
                (run_id,),
            ).fetchone()
            return (
                InsertionOutcome.NONE if row is None else InsertionOutcome(str(row[0]))
            )

        return await self._db.read(read)

    async def delete_run(self, run_id: str) -> DeleteResult:
        return await self._delete((run_id,))

    async def delete_all(self) -> DeleteResult:
        ids = await self._db.read(
            lambda conn: tuple(
                str(row[0])
                for row in conn.execute(
                    "SELECT id FROM runs ORDER BY created_at, id"
                ).fetchall()
            )
        )
        return await self._delete(ids)

    async def _delete(self, requested: tuple[str, ...]) -> DeleteResult:
        def delete(conn: Connection) -> tuple[tuple[str, ...], tuple[str, ...]]:
            found = (
                tuple(
                    str(row[0])
                    for row in conn.execute(
                        "SELECT id FROM runs WHERE id IN (%s) ORDER BY created_at, id"
                        % ",".join("?" for _ in requested),
                        requested,
                    ).fetchall()
                )
                if requested
                else ()
            )
            if requested and not found and len(requested) == 1:
                raise _error(ErrorCode.RUN_NOT_FOUND, "run")
            paths = _delete_rows(conn, list(found))
            return found, tuple(paths)

        ids, paths = await self._db.write(delete)
        await self._remove_paths(paths)
        pending = await self._db.read(
            lambda conn: sum(
                conn.execute(
                    "SELECT 1 FROM pending_deletions WHERE path=?", (path,)
                ).fetchone()
                is not None
                for path in paths
            )
        )
        if ids:
            self._publish([("deleted", ids)])
        await self._refresh_next_expiry()
        return DeleteResult(ids, pending > 0)

    async def enforce_retention(self) -> tuple[str, ...]:
        expired = await self._expire_first()
        return expired

    def next_expiry_at(self) -> float | None:
        return self._next_expiry

    async def recover_on_startup(self) -> StartupReport:
        now = self._clock()

        def recover(
            conn: Connection,
        ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
            inflight = tuple(
                str(row[0])
                for row in conn.execute(
                    "SELECT attempt_id FROM insertion_attempts WHERE outcome=? "
                    "ORDER BY seq",
                    (AttemptOutcome.IN_FLIGHT.value,),
                ).fetchall()
            )
            if inflight:
                conn.execute(
                    "UPDATE insertion_attempts SET outcome=?, completed_at=? "
                    "WHERE outcome=?",
                    (
                        AttemptOutcome.UNCERTAIN.value,
                        self._clock(),
                        AttemptOutcome.IN_FLIGHT.value,
                    ),
                )
            cleanup = tuple(
                str(row[0])
                for row in conn.execute(
                    "SELECT id FROM runs WHERE cleanup_status=? ORDER BY created_at,id",
                    (CleanupStatus.PENDING.value,),
                ).fetchall()
            )
            if cleanup:
                conn.execute(
                    "UPDATE runs SET cleanup_status=?, status=?, version=version+1 "
                    "WHERE cleanup_status=?",
                    (
                        CleanupStatus.FAILED.value,
                        RunStatus.AWAITING_CLEANUP_CHOICE.value,
                        CleanupStatus.PENDING.value,
                    ),
                )
            expired = tuple(_expire(conn, now))
            return inflight, cleanup, expired

        inflight, cleanup, expired = await self._db.write(recover)
        if expired:
            self._publish([("expired", expired)])
            await self._remove_paths(await self._pending_paths_for_ids(expired))
            self._defer_evictions(expired)
        pending_left = await self.retry_pending_deletions()
        referenced = await self._db.read(
            lambda conn: (
                {
                    str(row[0])
                    for row in conn.execute(
                        "SELECT audio_path FROM runs WHERE audio_path IS NOT NULL"
                    ).fetchall()
                }
                | {
                    str(row[0])
                    for row in conn.execute(
                        "SELECT path FROM pending_deletions"
                    ).fetchall()
                }
            )
        )
        orphan_count = 0
        if self._audio_dir.exists():
            for path in self._audio_dir.glob("*.wav"):
                if str(path) not in referenced:
                    try:
                        self._remove_file(path)
                        orphan_count += 1
                    except OSError:
                        pass
        if cleanup:
            self._publish([("updated", cleanup)])
        await self._refresh_next_expiry()
        return StartupReport(inflight, cleanup, expired, orphan_count, pending_left)

    async def retry_pending_deletions(self) -> int:
        paths = await self._db.read(
            lambda conn: tuple(
                str(row[0])
                for row in conn.execute(
                    "SELECT path FROM pending_deletions ORDER BY path"
                ).fetchall()
            )
        )
        return await self._remove_paths(paths)

    async def _expire_first(self) -> tuple[str, ...]:
        now = self._clock()

        def expire(conn: Connection) -> tuple[str, ...]:
            return tuple(_expire(conn, now))

        expired = await self._db.write(expire)
        if expired:
            self._publish([("expired", expired)])
            paths = await self._pending_paths_for_ids(expired)
            await self._remove_paths(paths)
        await self._refresh_next_expiry()
        if expired:
            self._defer_evictions(expired)
        return expired

    async def _pending_paths_for_ids(self, run_ids: tuple[str, ...]) -> tuple[str, ...]:
        if not run_ids:
            return ()
        return await self._db.read(
            lambda conn: tuple(
                str(row[0])
                for row in conn.execute(
                    "SELECT path FROM pending_deletions ORDER BY path"
                ).fetchall()
            )
        )

    async def _remove_paths(self, paths: tuple[str, ...] | list[str]) -> int:
        for raw in paths:
            path = Path(raw)
            try:
                self._remove_file(path)
            except OSError:
                continue

            def clear_pending(conn: Connection) -> None:
                conn.execute("DELETE FROM pending_deletions WHERE path=?", (raw,))

            await self._db.write(clear_pending)
        return await self._db.read(
            lambda conn: int(
                conn.execute("SELECT count(*) FROM pending_deletions").fetchone()[0]
            )
        )

    def _publish(self, groups: list[tuple[str, tuple[str, ...]]]) -> None:
        for reason, run_ids in groups:
            event: HistoryChangedEvent = {
                "name": "history:changed",
                "run_ids": list(run_ids),
                "reason": reason,
            }
            self._events.publish(event)

    def _defer_evictions(self, ids: tuple[str, ...] | list[str]) -> None:
        if self._on_run_evicted is None or not ids:
            return
        loop = asyncio.get_running_loop()
        for run_id in ids:
            loop.call_soon(self._on_run_evicted, run_id)

    async def _refresh_next_expiry(self) -> None:
        value: object = await self._db.read(
            lambda conn: conn.execute(
                "SELECT MIN(r.created_at) FROM runs r WHERE NOT EXISTS "
                "(SELECT 1 FROM insertion_attempts a "
                "WHERE a.run_id=r.id AND a.outcome=?)",
                (AttemptOutcome.IN_FLIGHT.value,),
            ).fetchone()[0]
        )
        self._next_expiry = None if value is None else expires_at(float(str(value)))


def _expire(conn: Connection, now: float) -> list[str]:
    rows = conn.execute(
        "SELECT id, audio_path, created_at FROM runs ORDER BY created_at, id"
    ).fetchall()
    protected = {
        str(row[0])
        for row in conn.execute(
            "SELECT DISTINCT run_id FROM insertion_attempts WHERE outcome=?",
            (AttemptOutcome.IN_FLIGHT.value,),
        ).fetchall()
    }
    expired = [
        str(row[0])
        for row in rows
        if str(row[0]) not in protected and is_expired(float(row[2]), now)
    ]
    _delete_rows(conn, expired)
    return expired


def _delete_rows(conn: Connection, ids: Sequence[str]) -> list[str]:
    if not ids:
        return []
    marks = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT audio_path FROM runs WHERE id IN ({marks}) AND audio_path IS NOT NULL",
        ids,
    ).fetchall()
    paths = [str(row[0]) for row in rows]
    for path in paths:
        conn.execute(
            "INSERT OR IGNORE INTO pending_deletions(path) VALUES (?)", (path,)
        )
    conn.execute(f"DELETE FROM runs WHERE id IN ({marks})", ids)
    return paths


def _run(row: object) -> RunRecord:
    try:
        data: tuple[Any, ...] = tuple(row)  # type: ignore[arg-type]
        destination = _decode(data[14], nullable=True)
        config = _decode(data[16], nullable=False)
        if destination is not None and not isinstance(destination, dict):
            raise ValueError
        if not isinstance(config, dict):
            raise ValueError
        return RunRecord(
            str(data[0]),
            str(data[1]),
            float(data[2]),
            int(data[3]),
            RunStatus(data[4]),
            _optional_float(data[5]),
            _optional_str(data[6]),
            _optional_float(data[7]),
            _optional_str(data[8]),
            _optional_str(data[9]),
            _optional_str(data[10]),
            _optional_str(data[11]),
            CleanupStatus(data[12]),
            _optional_str(data[13]),
            destination,
            _optional_str(data[15]),
            config,
        )
    except (ValueError, TypeError, IndexError, json.JSONDecodeError):
        ident = "unknown"
        try:
            ident = str(tuple(row)[0])  # type: ignore[arg-type]
        except (TypeError, IndexError):
            pass
        raise WisprError(
            ErrorCode.STORAGE_ERROR, "history", f"stored run {ident}"
        ) from None


def _attempt(row: object) -> AttemptRecord:
    data: tuple[Any, ...] = tuple(row)  # type: ignore[arg-type]
    ident = str(data[0]) if data else "unknown"
    try:
        target = _decode(data[4], nullable=True)
        if target is not None and not isinstance(target, dict):
            raise ValueError
        return AttemptRecord(
            ident,
            str(data[1]),
            str(data[2]),
            str(data[3]),
            cast(dict[str, object] | None, target),
            float(data[5]),
            _optional_float(data[6]),
            AttemptOutcome(data[7]),
        )
    except (ValueError, TypeError, IndexError, json.JSONDecodeError):
        raise WisprError(
            ErrorCode.STORAGE_ERROR, "history", f"stored attempt {ident}"
        ) from None


def _decode(value: object, *, nullable: bool) -> object:
    if value is None and nullable:
        return None
    decoded = json.loads(str(value))
    if not isinstance(decoded, dict):
        raise ValueError
    return decoded


def _json(value: Mapping[str, object] | object) -> str:
    try:
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError):
        raise _error(ErrorCode.VALIDATION, "json") from None


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_float(value: object) -> float | None:
    return None if value is None else float(str(value))


def _error(code: ErrorCode, why: str) -> WisprError:
    return WisprError(code, "history", why)
