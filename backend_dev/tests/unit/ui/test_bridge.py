"""T-UI-001: the only exposed bridge method validates before worker dispatch."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator, Mapping

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
