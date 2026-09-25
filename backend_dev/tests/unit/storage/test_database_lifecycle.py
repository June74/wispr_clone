"""Lifecycle errors of the pinned Database API."""

import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from wispr_clone.contracts.common import ErrorCode, WisprError


@pytest.mark.asyncio
async def test_T_STO_006_closed_access_idempotent_close_and_newer_schema(
    tmp_path: Path,
) -> None:
    from wispr_clone.storage import Database

    db = Database(tmp_path / "lifecycle.db")
    assert db.schema_version == 0
    for operation in (
        lambda: db.read(lambda conn: None),
        lambda: db.write(lambda conn: None),
    ):
        with pytest.raises(WisprError) as caught:
            await operation()
        assert caught.value.error_code == ErrorCode.STORAGE_ERROR
        assert caught.value.where == "storage.db"
    await db.open()
    with pytest.raises(WisprError) as twice:
        await db.open()
    assert twice.value.error_code == ErrorCode.STORAGE_ERROR
    await db.close()
    await db.close()
    for operation in (
        lambda: db.read(lambda conn: None),
        lambda: db.write(lambda conn: None),
    ):
        with pytest.raises(WisprError) as caught:
            await operation()
        assert caught.value.error_code == ErrorCode.STORAGE_ERROR
        assert caught.value.where == "storage.db"

    path = tmp_path / "future.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA user_version = 999")
    future = Database(path)
    with pytest.raises(WisprError) as caught:
        await future.open()
    assert caught.value.error_code == ErrorCode.STORAGE_ERROR
    assert caught.value.where == "storage.migrations"
    assert caught.value.why == "newer schema"
    await future.close()


@pytest.mark.asyncio
async def test_T_STO_006_overlapping_open_rejects_second_call(tmp_path: Path) -> None:
    from wispr_clone.storage import Database

    db = Database(tmp_path / "overlapping_open.db")
    try:
        results = await asyncio.gather(db.open(), db.open(), return_exceptions=True)
        assert sum(result is None for result in results) == 1
        errors = [result for result in results if isinstance(result, WisprError)]
        assert len(errors) == 1
        assert errors[0].error_code == ErrorCode.STORAGE_ERROR
        assert errors[0].where == "storage.db"
    finally:
        await db.close()
