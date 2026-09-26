"""WO-M5 composition and lifecycle acceptance at the public App boundary."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from wispr_clone.contracts.common import ErrorCode
from wispr_clone.contracts.run import RunStatus
from wispr_clone.hotkeys.hotkey_service import KeyAction
from wispr_clone.storage.db import Database

from ._support import Boundaries


async def _command(app: object, name: str, **fields: object) -> object:
    api = app.api  # type: ignore[attr-defined]
    return await api.call(
        name,
        {"session_token": api.session_token, "deadline": 1010.0, **fields},
    )


@pytest.mark.asyncio
async def test_startup_recovers_before_exposing_history(tmp_path: Path) -> None:
    from wispr_clone.app import App

    audio_dir = tmp_path / "history"
    audio_dir.mkdir()
    wav = audio_dir / "crashed.wav"
    wav.write_bytes(b"retained audio")
    seeded_path = tmp_path / "seeded.db"
    database = Database(seeded_path)
    await database.open()
    await database.write(
        lambda conn: conn.execute(
            "INSERT INTO runs (id,start_request_id,created_at,version,status,"
            "audio_path,cleanup_status,config) VALUES (?,?,?,?,?,?,?,?)",
            ("crashed", "old-request", 999.0, 1, "recording", str(wav), "off", "{}"),
        )
    )
    await database.close()

    boundaries = Boundaries(db_path=seeded_path)
    app = App(boundaries.factories(), data_dir=tmp_path)
    try:
        await app.startup()
        assert app.startup_log == [
            "directories",
            "database",
            "history_recovery",
            "interrupted_runs",
            "settings",
            "services",
            "stt",
            "timers_hotkeys",
            "windows",
        ]
        state = await app.api.call("state_get", {})
        assert state.ok
        assert state.data is not None
        assert state.data["runs"][0]["status"] == RunStatus.ERROR.value
        assert wav.read_bytes() == b"retained audio"
        row = await boundaries.databases[0].read(
            lambda conn: conn.execute(
                "SELECT error_code FROM runs WHERE id='crashed'"
            ).fetchone()
        )
        assert row[0] == ErrorCode.STORAGE_ERROR.value
    finally:
        await app.shutdown()


@pytest.mark.asyncio
async def test_shutdown_active_capture_is_ordered_and_idempotent(
    tmp_path: Path,
) -> None:
    from wispr_clone.app import App

    boundaries = Boundaries()
    app = App(boundaries.factories(), data_dir=tmp_path)
    await app.startup()
    started = await _command(app, "run_start", request_id="shutdown-request")
    assert started.ok  # type: ignore[attr-defined]
    await app.shutdown()
    assert boundaries.captures[0].cancelled
    assert boundaries.stt.closed
    assert boundaries.cleanups
    assert all(cleanup.closed for cleanup in boundaries.cleanups)
    assert boundaries.databases[0].closed_by_app
    assert boundaries.listeners[0].stops == 1
    assert app.shutdown_log == [
        "hotkeys",
        "timers",
        "runs_and_mic",
        "live_tasks",
        "models",
        "insertion_executor",
        "database",
        "worker_loop",
        "single_instance",
    ]
    await app.shutdown()
    assert boundaries.listeners[0].stops == 1
    assert boundaries.databases[0].closed_by_app


@pytest.mark.asyncio
async def test_hotkey_and_settings_update_use_api_and_rebuild_listener(
    tmp_path: Path,
) -> None:
    from wispr_clone.app import App

    boundaries = Boundaries()
    app = App(boundaries.factories(), data_dir=tmp_path)
    try:
        await app.startup()
        listener = boundaries.listeners[0]
        for key in ("ctrl", "shift", "space"):
            listener.service.handle(KeyAction.DOWN, key)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        state = await app.api.call("state_get", {})
        assert state.ok
        assert state.data is not None
        assert state.data["active_run_id"] is not None
        assert len(state.data["runs"]) == 1
        result = await _command(
            app, "settings_update", patch={"dictation_shortcut": "ctrl+alt+space"}
        )
        assert result.ok  # type: ignore[attr-defined]
        assert listener.stops == 1
        assert len(boundaries.listeners) == 2
        assert boundaries.listeners[1].starts == 1
    finally:
        await app.shutdown()


def test_factory_contract_is_frozen_and_headless() -> None:
    from wispr_clone.app import AppFactories

    assert AppFactories.__dataclass_params__.frozen
    factories = Boundaries().factories()
    assert factories.webview is None


@pytest.mark.asyncio
async def test_tracker_ignores_own_window_and_remembers_external_destination(
    tmp_path: Path,
) -> None:
    from wispr_clone.app import App

    boundaries = Boundaries()
    boundaries.win32.processes[10] = (os.getpid(), "wispr-clone.exe")
    boundaries.win32.titles[20] = "external private title"
    boundaries.win32.layouts[20] = 0x0409
    boundaries.win32.foreground = 10
    app = App(boundaries.factories(), data_dir=tmp_path)
    try:
        await app.startup()
        await asyncio.sleep(0.3)
        assert app.last_external_destination() is None
        boundaries.win32.foreground = 20
        await asyncio.sleep(0.3)
        snapshot = app.last_external_destination()
        assert snapshot is not None
        assert snapshot.hwnd == 20
        captured = len(boundaries.uia.calls)
        await asyncio.sleep(0.3)
        assert len(boundaries.uia.calls) == captured
    finally:
        await app.shutdown()


@pytest.mark.asyncio
async def test_retention_eviction_aborts_and_invalidates_start_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from wispr_clone.app import App
    from wispr_clone.pipeline.run_controller import RunController

    boundaries = Boundaries()
    aborted: list[str] = []
    original_abort = RunController.abort

    def record_abort(controller: RunController, run_id: str) -> None:
        aborted.append(run_id)
        original_abort(controller, run_id)

    monkeypatch.setattr(RunController, "abort", record_abort)
    app = App(boundaries.factories(), data_dir=tmp_path)
    try:
        await app.startup()
        first_id = ""
        for index in range(11):
            boundaries.now += 0.1
            started = await _command(app, "run_start", request_id=f"request-{index}")
            assert started.ok
            assert started.data is not None
            run_id = str(started.data["run_id"])
            if index == 0:
                first_id = run_id
            cancelled = await _command(app, "run_cancel", run_id=run_id)
            assert cancelled.ok
        await asyncio.sleep(0)
        assert first_id in aborted
        repeated = await _command(app, "run_start", request_id="request-0")
        assert not repeated.ok
        assert repeated.error == ErrorCode.RUN_DELETED
    finally:
        await app.shutdown()
