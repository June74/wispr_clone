"""T-APP-040: insertion adapter lifecycle stays on one initialized thread."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from wispr_clone.app import App
from wispr_clone.insertion.uia import UiaApi
from wispr_clone.insertion.win32 import Win32Api

from ._support import Boundaries


@pytest.mark.unit
@pytest.mark.asyncio
async def test_T_APP_040_insertion_thread_lifecycle(tmp_path: Path) -> None:
    boundaries = Boundaries()
    events: list[tuple[str, str]] = []

    def record(name: str) -> None:
        events.append((name, threading.current_thread().name))

    def make_win32() -> Win32Api:
        record("win32")
        return boundaries.win32

    def make_uia() -> UiaApi:
        record("uia")
        return boundaries.uia

    factories = replace(
        boundaries.factories(),
        win32=make_win32,
        uia=make_uia,
        insertion_thread_init=lambda: record("init"),
        insertion_thread_exit=lambda: record("exit"),
    )
    app = App(factories, data_dir=tmp_path)
    try:
        await app.startup()
        await app._offload(lambda: record("offload"))
        await asyncio.sleep(0)
    finally:
        await app.shutdown()

    names = [name for name, _thread in events]
    assert names.count("init") == 1
    assert names.count("exit") == 1
    assert names.index("init") < names.index("win32")
    assert names.index("init") < names.index("uia")
    assert names.index("init") < names.index("offload")
    assert names[-1] == "exit"
    assert {thread for _, thread in events} == {events[0][1]}
    assert events[0][1].startswith("wispr-insertion")
