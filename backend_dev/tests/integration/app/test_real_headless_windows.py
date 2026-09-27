"""T-APP-041: opt-in real Windows headless composition smoke test."""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from wispr_clone.app import App, real_factories

pytestmark = [pytest.mark.integration, pytest.mark.windows, pytest.mark.manual]


class _NoopListener:
    def __init__(self, _service: Any) -> None:
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


@pytest.mark.asyncio
async def test_T_APP_041_real_headless_tracker(tmp_path: Path) -> None:
    if sys.platform != "win32" or os.environ.get("WISPR_REAL_HEADLESS") != "1":
        pytest.skip("requires Windows and WISPR_REAL_HEADLESS=1")

    factories = replace(real_factories(), webview=None, hotkey_listener=_NoopListener)
    app = App(factories, data_dir=tmp_path)
    ticks = 0
    fourth_tick = asyncio.Event()
    track = app._track_destination

    async def count_track() -> None:
        nonlocal ticks
        try:
            await track()
        finally:
            ticks += 1
            if ticks >= 4:
                fourth_tick.set()

    app._track_destination = count_track
    try:
        await app.startup()
        assert app._win32 is not None
        assert app._uia is not None
        await asyncio.wait_for(fourth_tick.wait(), timeout=10)
        assert ticks >= 4
        assert app.timer_errors.get("tracker", 0) == 0
    finally:
        await app.shutdown()
    assert not (Path.cwd() / "@AutomationLog.txt").exists()
