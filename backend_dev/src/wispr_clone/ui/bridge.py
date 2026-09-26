"""Validated, bounded bridge from the settings page to the application API."""

from __future__ import annotations

import asyncio
import json
import math
from concurrent.futures import TimeoutError as FutureTimeout
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wispr_clone.application.api import Api


def _json_value(value: object, depth: int = 0) -> bool:
    if depth > 8:
        return False
    if value is None or type(value) in (bool, int, str):
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is list:
        return all(_json_value(item, depth + 1) for item in value)
    if type(value) is dict:
        return all(
            isinstance(key, str) and _json_value(item, depth + 1)
            for key, item in value.items()
        )
    return False


class Bridge:
    """Expose one method to pywebview and dispatch it to the worker loop."""

    __slots__ = ("_api", "_worker_loop")

    def __init__(self, api: Api, worker_loop: asyncio.AbstractEventLoop) -> None:
        self._api = api
        self._worker_loop = worker_loop

    def call(self, name: object, payload: object) -> dict[str, object]:
        if not isinstance(name, str) or name not in self._api._commands:
            return {"ok": False, "data": None, "error": "unknown_command"}
        if not isinstance(payload, dict) or not _json_value(payload):
            return {"ok": False, "data": None, "error": "validation"}
        try:
            encoded = json.dumps(payload, ensure_ascii=True, allow_nan=False)
        except (TypeError, ValueError, RecursionError):
            return {"ok": False, "data": None, "error": "validation"}
        if len(encoded.encode("utf-8")) > 64 * 1024:
            return {"ok": False, "data": None, "error": "validation"}
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._api.call(name, payload), self._worker_loop
            )
            result = future.result(timeout=15)
        except FutureTimeout:
            future.cancel()
            return {"ok": False, "data": None, "error": "storage_error"}
        except Exception:
            return {"ok": False, "data": None, "error": "storage_error"}
        return {
            "ok": result.ok,
            "data": result.data,
            "error": result.error.value if result.error is not None else None,
        }
