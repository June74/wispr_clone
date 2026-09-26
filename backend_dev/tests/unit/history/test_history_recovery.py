"""Startup recovery preserves terminal runs with interrupted cleanup."""

from __future__ import annotations

from pathlib import Path

import pytest
from fakes.clock import FakeClock
from fakes.events import FakeEventSink

from wispr_clone.contracts.run import CleanupStatus, RunStatus
from wispr_clone.history.repo import HistoryRepo
from wispr_clone.storage import Database, Migration
from wispr_clone.storage.migrations import (
    m001_base,
    m002_settings,
    m003_dictionary,
    m004_history,
)


@pytest.mark.asyncio
async def test_T_HIS_011b_only_processing_pending_cleanup_recovers(
    tmp_path: Path,
) -> None:
    migrations = [
        Migration(module.VERSION, module.NAME, module.apply)
        for module in (m001_base, m002_settings, m003_dictionary, m004_history)
    ]
    async with Database(tmp_path / "runs.db", migrations) as db:
        clock = FakeClock(100)
        history = HistoryRepo(
            db, clock=clock.now, audio_dir=tmp_path, events=FakeEventSink()
        )
        before = {}
        for status in (RunStatus.CANCELLED, RunStatus.ERROR, RunStatus.PROCESSING):
            run_id = status.value
            created = await history.create_run(
                run_id=run_id, start_request_id=run_id, config={}
            )
            before[run_id] = await history.update_run(
                run_id,
                expected_version=created.version,
                status=status,
                cleanup_status=CleanupStatus.PENDING,
            )

        report = await history.recover_on_startup()

        assert report.pending_cleanup_failed == (RunStatus.PROCESSING.value,)
        for status in (RunStatus.CANCELLED, RunStatus.ERROR):
            assert await history.get(status.value) == before[status.value]
        recovered = await history.get(RunStatus.PROCESSING.value)
        assert recovered.status == RunStatus.AWAITING_CLEANUP_CHOICE
        assert recovered.cleanup_status == CleanupStatus.FAILED
        assert recovered.version == before[RunStatus.PROCESSING.value].version + 1
