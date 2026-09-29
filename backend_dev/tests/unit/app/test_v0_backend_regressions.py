"""App composition regressions from WO-fix-v0-backend."""

from __future__ import annotations

from pathlib import Path

import pytest

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
