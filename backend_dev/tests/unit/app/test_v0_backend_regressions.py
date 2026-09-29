"""App composition regressions from WO-fix-v0-backend."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from wispr_clone.contracts.common import ErrorCode
from wispr_clone.hotkeys.hotkey_service import KeyAction

from ._support import Boundaries


async def command(app: object, name: str, **fields: object) -> object:
    api = app.api  # type: ignore[attr-defined]
    return await api.call(
        name,
        {
            "session_token": api.session_token,
            "deadline": app.factories.clock() + 10,
            **fields,
        },  # type: ignore[attr-defined]
    )


def press(listener: object) -> None:
    service = listener.service  # type: ignore[attr-defined]
    for key in ("ctrl", "shift", "space"):
        service.handle(KeyAction.DOWN, key)
    service.handle(KeyAction.UP, "space")


async def wait_for_active(app: object, *, previous: str | None = None) -> str | None:
    try:
        async with asyncio.timeout(0.5):
            while True:
                controller = app._controller  # type: ignore[attr-defined]
                active = controller.active_run_id if controller else None
                if active is not None and active != previous:
                    return active
                await asyncio.sleep(0)
    except TimeoutError:
        return None


async def wait_for_stopped(app: object) -> bool:
    try:
        async with asyncio.timeout(0.5):
            while app._controller.active_run_id is not None:  # type: ignore[attr-defined]
                await asyncio.sleep(0)
        return True
    except TimeoutError:
        return False


async def waiting_run(app: object, boundaries: Boundaries) -> str:
    started = await command(app, "run_start", request_id="waiting-run")
    assert started.ok and started.data is not None  # type: ignore[attr-defined]
    run_id = str(started.data["run_id"])  # type: ignore[attr-defined]
    boundaries.win32.foreground = 20
    stopped = await command(app, "run_stop", run_id=run_id)
    assert stopped.ok  # type: ignore[attr-defined]
    assert app._controller is not None  # type: ignore[attr-defined]
    await app._controller.settled(run_id)  # type: ignore[attr-defined]
    record = await app._history.get(run_id)  # type: ignore[attr-defined]
    assert record.status.value == "awaiting_destination"
    return run_id


@pytest.mark.asyncio
async def test_T_APP_053a_wait_limit_uses_wall_clock(tmp_path: Path) -> None:
    from wispr_clone.app import App

    boundaries = Boundaries(now=1_000_000.0, monotonic_now=50.0)
    app = App(boundaries.factories(), data_dir=tmp_path)
    try:
        await app.startup()
        run_id = await waiting_run(app, boundaries)
        boundaries.now += 601
        await app._delivery()
        record = await app._history.get(run_id)
        assert record.status.value == "held"
        assert not any(
            name in {"send_inputs", "set_clipboard"}
            for name, _, _ in boundaries.win32.calls
        )
    finally:
        await app.shutdown()


@pytest.mark.asyncio
async def test_T_APP_053b_expired_waiting_run_never_dispatches(tmp_path: Path) -> None:
    from wispr_clone.app import App

    boundaries = Boundaries(now=1_000_000.0, monotonic_now=50.0)
    app = App(boundaries.factories(), data_dir=tmp_path)
    try:
        await app.startup()
        run_id = await waiting_run(app, boundaries)
        boundaries.now += 86_400
        boundaries.win32.foreground = 10
        await app._delivery()
        assert not any(
            name in {"send_inputs", "set_clipboard"}
            for name, _, _ in boundaries.win32.calls
        )
        assert run_id not in app._controller.waiting_run_ids
    finally:
        await app.shutdown()


@pytest.mark.asyncio
async def test_T_APP_054_saved_microphone_is_used_for_next_run(tmp_path: Path) -> None:
    from wispr_clone.app import App

    boundaries = Boundaries()
    app = App(boundaries.factories(), data_dir=tmp_path)
    try:
        await app.startup()
        for index, device in enumerate(("2", "0", None)):
            updated = await command(
                app, "settings_update", patch={"microphone_id": device}
            )
            assert updated.ok  # type: ignore[attr-defined]
            started = await command(app, "run_start", request_id=f"microphone-{index}")
            assert started.ok and started.data is not None  # type: ignore[attr-defined]
            assert boundaries.capture_devices[-1] == (
                int(device) if device is not None else None
            )
            cancelled = await command(app, "run_cancel", run_id=started.data["run_id"])  # type: ignore[attr-defined]
            assert cancelled.ok  # type: ignore[attr-defined]
    finally:
        await app.shutdown()


@pytest.mark.asyncio
async def test_T_APP_055a_cancel_resets_toggle_press(tmp_path: Path) -> None:
    from wispr_clone.app import App

    boundaries = Boundaries()
    app = App(boundaries.factories(), data_dir=tmp_path)
    app._loop = asyncio.get_running_loop()
    try:
        await app.startup()
        listener = boundaries.listeners[-1]
        press(listener)
        first = await wait_for_active(app)
        assert first is not None
        listener.service.handle(KeyAction.DOWN, "escape")
        assert await wait_for_stopped(app)
        await app._controller.settled(first)
        press(listener)
        second = await wait_for_active(app, previous=first)
        assert second is not None and second != first
    finally:
        await app.shutdown()


@pytest.mark.asyncio
async def test_T_APP_055b_hotkey_stops_api_started_recording(tmp_path: Path) -> None:
    from wispr_clone.app import App

    boundaries = Boundaries()
    app = App(boundaries.factories(), data_dir=tmp_path)
    app._loop = asyncio.get_running_loop()
    try:
        await app.startup()
        started = await command(app, "run_start", request_id="api-start")
        assert started.ok and started.data is not None  # type: ignore[attr-defined]
        run_id = started.data["run_id"]  # type: ignore[attr-defined]
        press(boundaries.listeners[-1])
        assert await wait_for_stopped(app)
        await app._controller.settled(run_id)
        record = await app._history.get(run_id)
        assert record.status.value != "recording"
    finally:
        await app.shutdown()


@pytest.mark.asyncio
async def test_T_APP_055c_api_stop_resets_toggle_press(tmp_path: Path) -> None:
    from wispr_clone.app import App

    boundaries = Boundaries()
    app = App(boundaries.factories(), data_dir=tmp_path)
    app._loop = asyncio.get_running_loop()
    try:
        await app.startup()
        listener = boundaries.listeners[-1]
        press(listener)
        first = await wait_for_active(app)
        assert first is not None
        stopped = await command(app, "run_stop", run_id=first)
        assert stopped.ok  # type: ignore[attr-defined]
        assert await wait_for_stopped(app)
        await app._controller.settled(first)
        press(listener)
        second = await wait_for_active(app, previous=first)
        assert second is not None and second != first
    finally:
        await app.shutdown()


@pytest.mark.asyncio
async def test_T_APP_055d_hold_starts_on_down_stops_on_up(tmp_path: Path) -> None:
    from wispr_clone.app import App

    boundaries = Boundaries()
    app = App(boundaries.factories(), data_dir=tmp_path)
    app._loop = asyncio.get_running_loop()
    try:
        await app.startup()
        updated = await command(
            app, "settings_update", patch={"recording_mode": "hold"}
        )
        assert updated.ok  # type: ignore[attr-defined]
        listener = boundaries.listeners[-1]
        for key in ("ctrl", "shift", "space"):
            listener.service.handle(KeyAction.DOWN, key)
        active = await wait_for_active(app)
        assert active is not None
        listener.service.handle(KeyAction.UP, "space")
        assert await wait_for_stopped(app)
        await app._controller.settled(active)
        record = await app._history.get(active)
        assert record.status.value != "recording"
    finally:
        await app.shutdown()


@pytest.mark.asyncio
async def test_T_APP_017_removed_local_only_patch_returns_validation(
    tmp_path: Path,
) -> None:
    from wispr_clone.app import App

    app = App(Boundaries().factories(), data_dir=tmp_path)
    try:
        await app.startup()
        selected = await command(
            app,
            "models_select",
            role="stt",
            model_id="deepgram/nova-3",
        )
        assert selected.ok  # type: ignore[attr-defined]
        tested = await command(
            app,
            "models_test",
            role="cleanup",
            model_id="meta-llama-3.1-8b-instruct",
        )
        assert tested.ok  # type: ignore[attr-defined]
        result = await command(app, "settings_update", patch={"local_only": True})
        assert result.error == ErrorCode.VALIDATION  # type: ignore[attr-defined]
    finally:
        await app.shutdown()
