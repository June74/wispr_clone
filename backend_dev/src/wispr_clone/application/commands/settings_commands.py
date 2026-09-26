"""Handlers for settings and reconnect state snapshots."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping

from wispr_clone.application.api import CommandSpec
from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.history.repo import HistoryRepo
from wispr_clone.pipeline.run_controller import RunController
from wispr_clone.settings.store import SettingsStore


class SettingsCommands:
    def __init__(
        self,
        store: SettingsStore,
        history: HistoryRepo,
        controller: RunController,
        *,
        session_token: Callable[[], str],
        readiness: Callable[[], Awaitable[list[dict[str, object]]]],
    ) -> None:
        self._store = store
        self._history = history
        self._controller = controller
        self._session_token = session_token
        self._readiness = readiness

    def specs(self) -> dict[str, CommandSpec]:
        return {
            "settings_get": CommandSpec(self._get, mutating=False),
            "settings_update": CommandSpec(self._update, mutating=True),
            "state_get": CommandSpec(self._state, mutating=False, needs_session=False),
        }

    async def _get(self, _: Mapping[str, object]) -> Mapping[str, object]:
        return self._settings_data(await self._store.load())

    async def _update(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        patch = payload.get("patch")
        if not isinstance(patch, dict):
            raise WisprError(ErrorCode.VALIDATION, "settings", "patch")
        updated = await self._store.update(patch)
        return self._settings_data(updated)

    async def _state(self, _: Mapping[str, object]) -> Mapping[str, object]:
        settings = await self._store.load()
        models = await self._readiness()
        records = await self._history.list_runs()
        return {
            "session_token": self._session_token(),
            "settings": self._settings_data(settings),
            "models": models,
            "runs": [self._controller.run_snapshot(record) for record in records],
            "active_run_id": self._controller.active_run_id,
        }

    @staticmethod
    def _settings_data(settings: object) -> dict[str, object]:
        dump = getattr(settings, "model_dump", None)
        if not callable(dump):
            raise WisprError(ErrorCode.STORAGE_ERROR, "settings", "serialization")
        data = dump(mode="json")
        if not isinstance(data, dict):
            raise WisprError(ErrorCode.STORAGE_ERROR, "settings", "serialization")
        return data
