"""T-UI-001: the only exposed bridge method validates before worker dispatch."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Iterator, Mapping
from concurrent.futures import TimeoutError as FutureTimeout
from unittest.mock import Mock

import pytest

from wispr_clone.application.api import Api, CommandSpec
from wispr_clone.ui.bridge import Bridge


@pytest.fixture
def worker_loop() -> Iterator[asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever)
    thread.start()
    try:
        yield loop
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)
        loop.close()


@pytest.mark.unit
def test_T_UI_001_bridge_validates_and_dispatches_on_worker(
    worker_loop: asyncio.AbstractEventLoop,
) -> None:
    received: list[tuple[int, dict[str, object]]] = []

    async def handler(payload: Mapping[str, object]) -> Mapping[str, object]:
        received.append((threading.get_ident(), dict(payload)))
        return {"accepted": True}

    api = Api(
        {"state_get": CommandSpec(handler, mutating=False, needs_session=False)},
        session_token="session",
        clock=lambda: 0.0,
    )
    bridge = Bridge(api, worker_loop)
    assert [name for name in dir(bridge) if not name.startswith("_")] == ["call"]

    for name in ("not_registered", None, 7):
        assert bridge.call(name, {}) == {
            "ok": False,
            "data": None,
            "error": "unknown_command",
        }
    assert received == []

    invalid_payloads: list[object] = [
        None,
        [],
        {1: "non-string key"},
        {"value": b"bytes"},
        {"value": object()},
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": "x" * (64 * 1024)},
    ]
    nested: object = "leaf"
    for _ in range(9):
        nested = {"level": nested}
    invalid_payloads.append(nested)
    for payload in invalid_payloads:
        assert bridge.call("state_get", payload) == {
            "ok": False,
            "data": None,
            "error": "validation",
        }
    assert received == []

    assert bridge.call("state_get", {"value": [True, None, {"n": 1}]}) == {
        "ok": True,
        "data": {"accepted": True},
        "error": None,
    }
    assert len(received) == 1
    assert received[0][0] != threading.get_ident()
    assert received[0][1] == {"value": [True, None, {"n": 1}]}


@pytest.mark.unit
def test_T_UI_001_bridge_rejects_subclasses_tuples_large_ints_and_deep_lists(
    worker_loop: asyncio.AbstractEventLoop,
) -> None:
    class CustomDict(dict[str, object]):
        pass

    api = Api(
        {"state_get": CommandSpec(lambda _: _never_called(), False, False)},
        session_token="session",
        clock=lambda: 0.0,
    )
    bridge = Bridge(api, worker_loop)
    deep: object = None
    for _ in range(9):
        deep = [deep]
    for payload in (
        CustomDict(value=1),
        {"value": (1, 2)},
        {"value": 10**10000},
        {"value": deep},
        {"value": {1: "non-string key"}},
    ):
        assert bridge.call("state_get", payload)["error"] == "validation"


async def _never_called() -> Mapping[str, object]:
    raise AssertionError("invalid payload reached Api.call")


@pytest.mark.unit
def test_T_UI_001_bridge_cancels_timed_out_dispatch_and_redacts_errors(
    worker_loop: asyncio.AbstractEventLoop,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from wispr_clone.ui import bridge as bridge_module

    async def handler(_: Mapping[str, object]) -> Mapping[str, object]:
        raise RuntimeError("private transcript marker")

    api = Api(
        {"state_get": CommandSpec(handler, False, False)},
        session_token="session",
        clock=lambda: 0.0,
    )
    bridge = Bridge(api, worker_loop)
    with caplog.at_level(logging.WARNING):
        result = bridge.call("state_get", {"text": "private transcript marker"})
        assert result["error"] == "storage_error"
    assert "private transcript marker" not in caplog.text

    future = Mock()
    future.result.side_effect = FutureTimeout()

    def dispatch(coroutine: object, loop: asyncio.AbstractEventLoop) -> Mock:
        assert loop is worker_loop
        coroutine.close()  # type: ignore[attr-defined]
        return future

    monkeypatch.setattr(bridge_module.asyncio, "run_coroutine_threadsafe", dispatch)
    assert bridge.call("state_get", {}) == {
        "ok": False,
        "data": None,
        "error": "storage_error",
    }
    future.result.assert_called_once_with(timeout=15)
    future.cancel.assert_called_once_with()
