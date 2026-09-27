"""T-APP-046/047: tray ownership, start-hidden, and launch-at-login commands."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import pytest

from wispr_clone.contracts.common import ErrorCode

from ._support import Boundaries


class FakeTray:
    instances: list[FakeTray] = []

    def __init__(
        self, *, on_open: Callable[[], None], on_quit: Callable[[], None]
    ) -> None:
        self.on_open, self.on_quit = on_open, on_quit
        self.started = self.stopped = False
        self.start_result = True
        FakeTray.instances.append(self)

    def start(self) -> bool:
        self.started = True
        return self.start_result

    def stop(self) -> None:
        self.stopped = True


def _failing_tray(**kwargs: Any) -> FakeTray:
    tray = FakeTray(**kwargs)
    tray.start_result = False
    return tray


def _run(app: Any) -> None:
    try:
        assert app.run() == 0
    finally:
        if not app._worker_done.is_set():
            app._schedule_shutdown()
            app._worker_done.wait(timeout=2)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("tray_factory", "start_hidden", "shown", "hides"),
    [
        (FakeTray, True, False, True),
        (FakeTray, False, True, True),
        # No tray icon: the window must be shown and closing must quit.
        (_failing_tray, True, True, False),
        (None, True, True, False),
    ],
)
def test_T_APP_046_tray_decides_hide_on_close_and_background_start(
    tmp_path: Path,
    tray_factory: Callable[..., FakeTray] | None,
    start_hidden: bool,
    shown: bool,
    hides: bool,
) -> None:
    from wispr_clone.app import App

    FakeTray.instances.clear()
    boundaries = Boundaries()
    app = App(
        replace(boundaries.factories(gui=True), tray=tray_factory),
        data_dir=tmp_path,
        start_hidden=start_hidden,
    )
    _run(app)

    settings = boundaries.webview.windows[-1]
    assert settings.title == "Wispr Clone"
    assert (("show", ()) in settings.calls) is shown
    if tray_factory is None:
        assert FakeTray.instances == []
        return
    tray = FakeTray.instances[0]
    assert tray.started
    assert tray.stopped
    assert tray.on_open.__self__.hide_on_close is hides  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_T_APP_047_autostart_commands_use_injected_boundary(
    tmp_path: Path,
) -> None:
    from wispr_clone.app import App

    state = {"available": True, "enabled": False}
    writes: list[bool] = []

    def set_enabled(enabled: bool) -> dict[str, bool]:
        writes.append(enabled)
        if enabled and len(writes) > 1:
            raise PermissionError("registry denied")
        state["enabled"] = enabled
        return dict(state)

    boundaries = Boundaries()
    app = App(
        replace(
            boundaries.factories(),
            autostart_status=lambda: dict(state),
            autostart_set=set_enabled,
        ),
        data_dir=tmp_path,
    )
    app._loop = asyncio.get_running_loop()
    await app.startup()
    try:
        api = app.api
        base = {"session_token": api.session_token, "deadline": 1010.0}
        got = await api.call("autostart_get", {"session_token": api.session_token})
        assert got.ok and got.data == {"available": True, "enabled": False}
        bad = await api.call("autostart_set", {**base, "enabled": "yes"})
        assert bad.error is ErrorCode.VALIDATION
        assert writes == []
        on = await api.call("autostart_set", {**base, "enabled": True})
        assert on.ok and on.data == {"available": True, "enabled": True}
        denied = await api.call("autostart_set", {**base, "enabled": True})
        assert denied.error is ErrorCode.STORAGE_ERROR
        assert writes == [True, True]
    finally:
        await app.shutdown()


@pytest.mark.unit
def test_T_APP_048_cues_tick_once_per_recording_start_and_stop() -> None:
    from wispr_clone.app import EventRouter

    router = EventRouter()
    heard: list[str] = []
    router.cue = heard.append

    def state(run_id: str, status: str) -> None:
        router.publish(
            {"name": "run:state", "run_id": run_id, "version": 1, "status": status}
        )

    state("a", "recording")
    state("a", "recording")  # repeated state events do not repeat the tick
    state("a", "processing")
    state("a", "done")
    state("b", "recording")
    state("b", "cancelled")
    state("c", "processing")  # never recorded here: no stop tick
    assert heard == ["start", "stop", "start", "stop"]


@pytest.mark.asyncio
async def test_T_APP_048_cues_follow_the_sound_setting(tmp_path: Path) -> None:
    from wispr_clone.app import App

    app = App(Boundaries().factories(), data_dir=tmp_path)
    app._loop = asyncio.get_running_loop()
    await app.startup()
    played: list[str] = []
    app._cues.play = played.append  # type: ignore[method-assign]
    try:
        app._play_cue("start")
        assert played == []
        api = app.api
        result = await api.call(
            "settings_update",
            {
                "session_token": api.session_token,
                "deadline": 1010.0,
                "patch": {"sound_cues": True},
            },
        )
        assert result.ok and result.data["sound_cues"] is True
        app._play_cue("start")
        app._play_cue("stop")
        assert played == ["start", "stop"]
    finally:
        await app.shutdown()
