"""T-APP-044: shutdown scheduling is safe across worker-loop teardown."""

from __future__ import annotations

import asyncio
import gc
import threading
import warnings
from pathlib import Path

import pytest

from wispr_clone.app import App

from ._support import Boundaries


@pytest.mark.unit
def test_T_APP_044_shutdown_is_scheduled_once_and_not_on_closed_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = App(Boundaries().factories(), data_dir=tmp_path)
    loop = asyncio.new_event_loop()
    app._loop = loop
    running = threading.Event()
    shutdown_calls = 0
    original_shutdown = app.shutdown

    async def counted_shutdown() -> None:
        nonlocal shutdown_calls
        shutdown_calls += 1
        await original_shutdown()

    monkeypatch.setattr(app, "shutdown", counted_shutdown)

    def run_loop() -> None:
        asyncio.set_event_loop(loop)
        loop.call_soon(running.set)
        try:
            loop.run_forever()
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    worker = threading.Thread(target=run_loop, daemon=True)
    worker.start()
    try:
        assert running.wait(timeout=2)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", RuntimeWarning)
            app._schedule_shutdown()
            app._schedule_shutdown()
            worker.join(timeout=2)
            assert not worker.is_alive()
            assert loop.is_closed()
            app._schedule_shutdown()
            gc.collect()

        assert shutdown_calls == 1
        assert not [w for w in caught if issubclass(w.category, RuntimeWarning)]
    finally:
        if worker.is_alive():
            loop.call_soon_threadsafe(loop.stop)
            worker.join(timeout=2)
        app.insertion_executor.shutdown(wait=True, cancel_futures=True)
