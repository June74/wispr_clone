"""Handlers for run lifecycle and recovery commands."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, cast

from wispr_clone.application.api import CommandSpec
from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.contracts.run import RecoveryAction
from wispr_clone.pipeline.run_controller import RunController


class RunCommands:
    def __init__(
        self,
        controller: RunController,
        *,
        clock: Callable[[], float],
        copy_to_clipboard: Callable[[str], Awaitable[None]],
        last_external_destination: Callable[[], object | None],
        dedupe_window_s: float = 30.0,
    ) -> None:
        self._controller = controller
        self._clock = clock
        self._copy_to_clipboard = copy_to_clipboard
        self._last_external_destination = last_external_destination
        self._dedupe_window_s = dedupe_window_s
        self._dedupe: dict[str, tuple[str, float]] = {}
        self._pending: dict[str, asyncio.Future[str]] = {}
        self._invalidated: dict[str, float] = {}

    def specs(self) -> dict[str, CommandSpec]:
        return {
            "run_start": CommandSpec(self._start, mutating=True),
            "run_stop": CommandSpec(self._stop, mutating=True),
            "run_cancel": CommandSpec(self._cancel, mutating=True),
            "run_recover": CommandSpec(self._recover, mutating=True),
        }

    def invalidate(self, run_id: str) -> None:
        expires = self._clock() + self._dedupe_window_s
        for request_id, (mapped_run_id, _) in tuple(self._dedupe.items()):
            if mapped_run_id == run_id:
                del self._dedupe[request_id]
                self._invalidated[request_id] = expires

    async def _start(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        request_id = _required_string(payload, "request_id")
        self._prune()
        if request_id in self._invalidated:
            raise WisprError(ErrorCode.RUN_DELETED, "run", "invalidated")
        previous = self._dedupe.get(request_id)
        if previous is not None:
            return {"run_id": previous[0], "deduplicated": True}
        pending = self._pending.get(request_id)
        if pending is not None:
            return {"run_id": await asyncio.shield(pending), "deduplicated": True}
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            run_id = await self._controller.start(start_request_id=request_id)
            self._dedupe[request_id] = (run_id, self._clock())
            future.set_result(run_id)
            return {"run_id": run_id, "deduplicated": False}
        except BaseException as error:
            future.set_exception(error)
            future.exception()
            raise
        finally:
            self._pending.pop(request_id, None)

    async def _stop(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        run_id = _required_string(payload, "run_id")
        await self._controller.stop(run_id)
        return {"run_id": run_id}

    async def _cancel(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        selected_run_id: str | None
        if "run_id" in payload:
            selected_run_id = _required_string(payload, "run_id")
            await self._controller.cancel(selected_run_id)
        else:
            selected_run_id = await self._controller.cancel_current()
        return {"run_id": selected_run_id}

    async def _recover(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        run_id = _required_string(payload, "run_id")
        expected_version = payload.get("expected_version")
        if isinstance(expected_version, bool) or not isinstance(expected_version, int):
            raise WisprError(ErrorCode.VALIDATION, "run", "expected_version")
        action_value = _required_string(payload, "action")
        try:
            action = RecoveryAction(action_value)
        except ValueError:
            raise WisprError(ErrorCode.VALIDATION, "run", "action") from None
        acknowledge = payload.get("acknowledge_uncertain", False)
        selected = payload.get("use_selected_destination", False)
        if type(acknowledge) is not bool or type(selected) is not bool:
            raise WisprError(ErrorCode.VALIDATION, "run", "options")
        if action == RecoveryAction.COPY:
            text = await self._controller.copy_text(run_id)
            await self._copy_to_clipboard(text)
            return {"run_id": run_id}
        if selected:
            if action != RecoveryAction.INSERT:
                raise WisprError(ErrorCode.VALIDATION, "run", "destination option")
            destination = self._last_external_destination()
            if destination is None:
                raise WisprError(
                    ErrorCode.DESTINATION_UNVERIFIABLE, "run", "destination"
                )
            await self._controller.recover(
                run_id,
                action,
                expected_version=expected_version,
                acknowledge_uncertain=acknowledge,
                destination=cast(Any, destination),
            )
        else:
            await self._controller.recover(
                run_id,
                action,
                expected_version=expected_version,
                acknowledge_uncertain=acknowledge,
            )
        return {"run_id": run_id}

    def _prune(self) -> None:
        now = self._clock()
        for request_id, (_, recorded_at) in tuple(self._dedupe.items()):
            if now - recorded_at > self._dedupe_window_s:
                del self._dedupe[request_id]
        for request_id, expires in tuple(self._invalidated.items()):
            if now > expires:
                del self._invalidated[request_id]


def _required_string(payload: Mapping[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise WisprError(ErrorCode.VALIDATION, "command", name)
    return value
