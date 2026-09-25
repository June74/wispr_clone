"""Async-friendly SQLite access serialized on one dedicated thread."""

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Sequence, TypeVar

from wispr_clone.contracts.common import ErrorCode, ThirdPartyError, WisprError
from wispr_clone.storage.migrations import (
    Migration,
    apply_migrations,
    discover_migrations,
)

T = TypeVar("T")


class Database:
    """Own one SQLite connection and serialize all operations on its thread."""

    def __init__(
        self, path: Path, migrations: Sequence[Migration] | None = None
    ) -> None:
        self._path = path
        self._migrations = migrations
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="wispr-db"
        )
        self._conn: sqlite3.Connection | None = None
        self._opened = False
        self._closed = False
        self._schema_version = 0

    @property
    def schema_version(self) -> int:
        """Return the version most recently applied by this instance."""
        return self._schema_version

    def _require_open(self) -> sqlite3.Connection:
        if not self._opened or self._conn is None or self._closed:
            raise WisprError(ErrorCode.STORAGE_ERROR, "storage.db", "not open")
        return self._conn

    async def open(self) -> None:
        """Create/configure the connection and apply migrations on its owner thread."""
        if self._opened or self._closed:
            raise WisprError(ErrorCode.STORAGE_ERROR, "storage.db", "already opened")

        def initialize() -> int:
            try:
                conn = sqlite3.connect(self._path, isolation_level=None)
                self._conn = conn
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("PRAGMA synchronous=FULL")
                conn.execute("PRAGMA busy_timeout=5000")
            except Exception as error:
                if self._conn is not None:
                    self._conn.close()
                    self._conn = None
                raise ThirdPartyError(
                    "sqlite3", "open", type(error).__name__, ErrorCode.STORAGE_ERROR
                ) from error
            migrations = self._migrations
            if migrations is None:
                migrations = discover_migrations()
            return apply_migrations(conn, migrations)

        try:
            self._schema_version = await asyncio.get_running_loop().run_in_executor(
                self._executor, initialize
            )
        except Exception:
            if self._conn is not None:
                try:
                    loop = asyncio.get_running_loop()
                    self._schema_version = await loop.run_in_executor(
                        self._executor,
                        self._read_schema_version,
                    )
                except Exception:
                    pass
                await asyncio.get_running_loop().run_in_executor(
                    self._executor, self._close_connection
                )
            self._shutdown_executor()
            self._closed = True
            raise
        self._opened = True

    def _close_connection(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _read_schema_version(self) -> int:
        if self._conn is None:
            return self._schema_version
        return int(self._conn.execute("PRAGMA user_version").fetchone()[0])

    def _shutdown_executor(self) -> None:
        self._executor.shutdown(wait=True)

    async def _run(self, fn: Callable[[sqlite3.Connection], T], write: bool) -> T:
        conn = self._require_open()

        def execute() -> T:
            if not write:
                return fn(conn)
            conn.execute("BEGIN IMMEDIATE")
            try:
                result = fn(conn)
                if not conn.in_transaction:
                    raise WisprError(
                        ErrorCode.STORAGE_ERROR,
                        "storage.db",
                        "transaction ended early",
                    )
                conn.execute("COMMIT")
                return result
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise

        return await asyncio.get_running_loop().run_in_executor(self._executor, execute)

    async def write(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        """Run a callback in one immediate transaction."""
        return await self._run(fn, True)

    async def read(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        """Run a callback on the writer thread without an explicit transaction."""
        return await self._run(fn, False)

    async def close(self) -> None:
        """Close the connection and stop its thread; safe to call repeatedly."""
        if self._closed:
            return
        self._closed = True
        if self._conn is not None:
            await asyncio.get_running_loop().run_in_executor(
                self._executor, self._close_connection
            )
        await asyncio.to_thread(self._shutdown_executor)

    async def __aenter__(self) -> "Database":
        await self.open()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()
