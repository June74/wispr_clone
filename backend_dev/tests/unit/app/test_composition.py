"""WO-M5 composition and lifecycle acceptance at the public App boundary."""

from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from pathlib import Path
from typing import Callable, Mapping

import pytest
from fakes.stt import FakeSttEngine

from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.contracts.run import RunStatus
from wispr_clone.hotkeys.hotkey_service import KeyAction
from wispr_clone.storage.db import Database

from ._support import Boundaries, RecordingDatabase


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
        controller = app._controller
        assert controller is not None
        listener = boundaries.listeners[0]
        for key in ("ctrl", "shift", "space"):
            listener.service.handle(KeyAction.DOWN, key)
        async with asyncio.timeout(2):
            while True:
                state = await app.api.call("state_get", {})
                if (
                    state.ok
                    and state.data is not None
                    and state.data["active_run_id"] is not None
                    and controller.active_run_id == state.data["active_run_id"]
                    and isinstance(state.data["runs"], list)
                    and len(state.data["runs"]) == 1
                ):
                    break
                await asyncio.sleep(0.01)
        assert state.ok
        assert state.data is not None
        assert state.data["active_run_id"] is not None
        assert isinstance(state.data["runs"], list)
        assert len(state.data["runs"]) == 1
        first_run_id = str(state.data["active_run_id"])
        result = await _command(
            app, "settings_update", patch={"dictation_shortcut": "ctrl+alt+space"}
        )
        assert result.ok  # type: ignore[attr-defined]
        assert listener.stops == 1
        assert len(boundaries.listeners) == 2
        assert boundaries.listeners[1].starts == 1
        cancelled = await _command(app, "run_cancel")
        assert cancelled.ok  # type: ignore[attr-defined]
        async with asyncio.timeout(2):
            try:
                await controller.settled(first_run_id)
            except Exception:
                pass
        for key in ("ctrl", "alt", "space"):
            boundaries.listeners[1].service.handle(KeyAction.DOWN, key)
        async with asyncio.timeout(2):
            while True:
                rebuilt_state = await app.api.call("state_get", {})
                if (
                    rebuilt_state.ok
                    and rebuilt_state.data is not None
                    and rebuilt_state.data["active_run_id"] is not None
                    and isinstance(rebuilt_state.data["runs"], list)
                    and len(rebuilt_state.data["runs"]) == 2
                ):
                    break
                await asyncio.sleep(0.01)
        assert rebuilt_state.ok
        assert rebuilt_state.data is not None
        assert isinstance(rebuilt_state.data["runs"], list)
        assert len(rebuilt_state.data["runs"]) == 2
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


@pytest.mark.asyncio
async def test_T_APP_016_retention_timer_counts_schedule_errors(tmp_path: Path) -> None:
    from wispr_clone.app import App

    app = App(Boundaries().factories(), data_dir=tmp_path)
    try:
        await app.startup()
        assert app._history is not None

        def broken_expiry() -> float:
            raise RuntimeError("expiry lookup failed")

        app._history.next_expiry_at = broken_expiry  # type: ignore[method-assign]
        timer = asyncio.create_task(app._retention_loop())
        await asyncio.sleep(0)
        assert app.timer_errors.get("retention") == 1
        assert not timer.done()
    finally:
        if "timer" in locals():
            timer.cancel()
            await asyncio.gather(timer, return_exceptions=True)
        await app.shutdown()


@pytest.mark.asyncio
async def test_T_APP_016_shutdown_during_startup_stops_new_services(
    tmp_path: Path,
) -> None:
    from wispr_clone.app import App

    entered = asyncio.Event()
    release = asyncio.Event()

    class SlowStt(FakeSttEngine):
        async def start(self) -> None:
            entered.set()
            await release.wait()
            await super().start()

    boundaries = Boundaries(stt=SlowStt("fixed text"))
    app = App(boundaries.factories(), data_dir=tmp_path)
    startup = asyncio.create_task(app.startup())
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        await app.shutdown()
        release.set()
        await asyncio.wait_for(startup, timeout=2)
        assert boundaries.listeners == []
        assert app._timers == []
    finally:
        release.set()
        await asyncio.gather(startup, return_exceptions=True)
        for timer in app._timers:
            timer.cancel()
        await asyncio.gather(*app._timers, return_exceptions=True)
        await app.shutdown()


def test_T_APP_016_webview_factory_failure_closes_worker(tmp_path: Path) -> None:
    from wispr_clone.app import App

    boundaries = Boundaries()

    def broken_webview() -> object:
        raise RuntimeError("webview unavailable")

    app = App(
        replace(boundaries.factories(), webview=broken_webview), data_dir=tmp_path
    )
    try:
        assert app.run() == 1
        assert app._worker_done.wait(timeout=2)
        assert boundaries.databases[0].closed_by_app
    finally:
        if not app._worker_done.is_set():
            app._schedule_shutdown()
            app._worker_done.wait(timeout=2)


def test_T_APP_016_webview_factory_is_used_once(tmp_path: Path) -> None:
    from wispr_clone.app import App

    boundaries = Boundaries()
    calls = 0

    def new_webview() -> object:
        nonlocal calls
        calls += 1
        return boundaries.webview

    app = App(replace(boundaries.factories(), webview=new_webview), data_dir=tmp_path)
    try:
        assert app.run() == 0
        assert calls == 1
        assert len(boundaries.webview.windows) == 2
        assert sum(name == "start" for name, _ in boundaries.webview.calls) == 1
    finally:
        if not app._worker_done.is_set():
            app._schedule_shutdown()
            app._worker_done.wait(timeout=2)


@pytest.mark.parametrize("available", [True, False])
def test_T_APP_044_native_hud_factory_and_fallback(
    tmp_path: Path, available: bool
) -> None:
    from wispr_clone.app import App

    boundaries = Boundaries()
    calls = 0

    class FakeNativeHud:
        def __init__(self) -> None:
            self.available = available
            self.destroyed = False

        def destroy(self) -> None:
            self.destroyed = True

    native_hud = FakeNativeHud()

    def make_native_hud(*, on_cancel: Callable[[], None]) -> FakeNativeHud:
        nonlocal calls
        assert callable(on_cancel)
        calls += 1
        return native_hud

    app = App(
        replace(boundaries.factories(gui=True), native_hud=make_native_hud),
        data_dir=tmp_path,
    )
    try:
        assert app.run() == 0
        assert calls == 1
        if available:
            assert app._hud is native_hud
            assert native_hud.destroyed
            assert len(boundaries.webview.windows) == 1
        else:
            assert app._hud is not native_hud
            assert not native_hud.destroyed
            assert len(boundaries.webview.windows) == 2
            assert boundaries.webview.windows[0].title == "Wispr Clone HUD"
    finally:
        if not app._worker_done.is_set():
            app._schedule_shutdown()
            app._worker_done.wait(timeout=2)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["recording", "waiting"])
@pytest.mark.parametrize("trigger", ["hud", "shortcut"])
async def test_T_APP_045_native_cancel_schedules_active_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str, trigger: str
) -> None:
    from wispr_clone.app import App

    boundaries = Boundaries()
    callbacks: list[Callable[[], None]] = []

    class FakeNativeHud:
        available = True

        def show(self) -> None:
            pass

        def hide(self) -> None:
            pass

        def publish_event(self, _event: object) -> None:
            pass

        def destroy(self) -> None:
            pass

    def make_native_hud(*, on_cancel: Callable[[], None]) -> FakeNativeHud:
        callbacks.append(on_cancel)
        return FakeNativeHud()

    app = App(
        replace(boundaries.factories(gui=True), native_hud=make_native_hud),
        data_dir=tmp_path,
    )
    app._loop = asyncio.get_running_loop()
    try:
        await app.startup()
        assert len(callbacks) == 1
        started = await _command(app, "run_start", request_id="native-cancel")
        assert started.ok
        assert started.data is not None
        run_id = str(started.data["run_id"])
        assert app._controller is not None
        assert app._controller.active_run_id == run_id
        if phase == "waiting":
            boundaries.win32.foreground = 20
            boundaries.win32.switch_foreground = False
            stopped = await _command(app, "run_stop", run_id=run_id)
            assert stopped.ok
            record = await app._controller.settled(run_id)
            assert record.status == RunStatus.AWAITING_DESTINATION
            assert app._controller.active_run_id is None
        original_call = app.api.call
        cancel_payloads: list[dict[str, object]] = []

        async def record_call(name: str, payload: Mapping[str, object]) -> object:
            if name == "run_cancel":
                cancel_payloads.append(dict(payload))
            return await original_call(name, payload)

        monkeypatch.setattr(app.api, "call", record_call)
        if trigger == "hud":
            await asyncio.to_thread(callbacks[0])
        else:
            boundaries.listeners[0].service.handle(KeyAction.DOWN, "escape")
        async with asyncio.timeout(2):
            while not cancel_payloads:
                await asyncio.sleep(0.01)
            record = await app._controller.settled(run_id)
            while record.status != RunStatus.CANCELLED:
                await asyncio.sleep(0.01)
                record = await app._controller.settled(run_id)
        assert app._controller.active_run_id is None
        assert len(cancel_payloads) == 1
        if phase == "recording" and trigger == "hud":
            assert cancel_payloads[0]["run_id"] == run_id
        else:
            assert "run_id" not in cancel_payloads[0]
        if phase == "recording":
            assert boundaries.captures[0].cancelled
        assert app._controller.waiting_run_ids == ()
        boundaries.win32.foreground = 10
        await app._controller.delivery_tick()
        assert not any(name == "send_inputs" for name, *_ in boundaries.win32.calls)
    finally:
        await app.shutdown()


def test_T_APP_016_migration_failure_never_starts_services(tmp_path: Path) -> None:
    from wispr_clone.app import App

    class BrokenDatabase(RecordingDatabase):
        async def open(self) -> None:
            raise RuntimeError("migration failed")

    boundaries = Boundaries()
    databases: list[BrokenDatabase] = []

    def open_database(path: Path) -> BrokenDatabase:
        database = BrokenDatabase(path)
        databases.append(database)
        return database

    app = App(
        replace(boundaries.factories(), open_database=open_database),
        data_dir=tmp_path,
    )
    assert app.run() == 1
    assert app._worker_done.wait(timeout=2)
    assert databases[0].closed_by_app
    assert boundaries.listeners == []
    assert boundaries.stt.started is False
    assert app.startup_log == ["directories"]


@pytest.mark.asyncio
async def test_T_APP_016_stt_start_failure_keeps_app_available(tmp_path: Path) -> None:
    from wispr_clone.app import App

    class BrokenStt(FakeSttEngine):
        async def start(self) -> None:
            self.available = False
            raise RuntimeError("model unavailable")

        def start_session(self) -> None:
            raise WisprError(ErrorCode.STT_UNAVAILABLE, "stt", "not ready")

    boundaries = Boundaries(stt=BrokenStt("fixed text"))
    app = App(boundaries.factories(), data_dir=tmp_path)
    try:
        await app.startup()
        result = await _command(app, "run_start", request_id="stt-failure")
        assert not result.ok  # type: ignore[attr-defined]
        assert result.error == ErrorCode.STT_UNAVAILABLE  # type: ignore[attr-defined]
        models = await _command(app, "models_status")
        assert models.ok
        assert models.data is not None
        assert models.data["models"][0]["ready"] is False
    finally:
        await app.shutdown()
