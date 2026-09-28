"""Handlers for operating-system integration: launch at login."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from wispr_clone.application.api import CommandSpec
from wispr_clone.contracts.common import ErrorCode, WisprError


class SystemCommands:
    def __init__(
        self,
        *,
        autostart_status: Callable[[], Mapping[str, bool]],
        autostart_set: Callable[[bool], Mapping[str, bool]],
    ) -> None:
        self._status = autostart_status
        self._set = autostart_set

    def specs(self) -> dict[str, CommandSpec]:
        return {
            "autostart_get": CommandSpec(self._get, mutating=False),
            "autostart_set": CommandSpec(self._update, mutating=True),
        }

    async def _get(self, _: Mapping[str, object]) -> Mapping[str, object]:
        return dict(self._status())

    async def _update(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        enabled = payload.get("enabled")
        if not isinstance(enabled, bool):
            raise WisprError(ErrorCode.VALIDATION, "autostart", "enabled")
        try:
            return dict(self._set(enabled))
        except OSError:
            raise WisprError(ErrorCode.STORAGE_ERROR, "autostart", "registry") from None
