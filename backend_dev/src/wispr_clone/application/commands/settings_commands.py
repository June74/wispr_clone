"""Handlers for settings and reconnect state snapshots."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping

from wispr_clone.application.api import CommandSpec
from wispr_clone.application.model_service import ModelService
from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.history.repo import HistoryRepo
from wispr_clone.pipeline.run_controller import RunController
from wispr_clone.settings.secret_store import MemorySecretStore, SecretStore
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
        secret_store: SecretStore | None = None,
        model_service: ModelService | None = None,
    ) -> None:
        self._store = store
        self._history = history
        self._controller = controller
        self._session_token = session_token
        self._readiness = readiness
        self._secret_store = secret_store or MemorySecretStore()
        self._model_service = model_service

    def specs(self) -> dict[str, CommandSpec]:
        return {
            "settings_get": CommandSpec(self._get, mutating=False),
            "settings_update": CommandSpec(self._update, mutating=True),
            "state_get": CommandSpec(self._state, mutating=False, needs_session=False),
            "secret_set": CommandSpec(self._secret_set, mutating=True),
            "secret_clear": CommandSpec(self._secret_clear, mutating=True),
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
            "secrets": {
                "openrouter_api_key": {
                    "configured": bool(self._secret_store.get("openrouter_api_key"))
                }
            },
        }

    async def _secret_set(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        name, value = payload.get("name"), payload.get("value")
        if name != "openrouter_api_key" or not isinstance(value, str):
            raise WisprError(ErrorCode.VALIDATION, "secrets", "name") from None
        self._secret_store.set(name, value)
        if self._model_service is not None:
            await self._model_service.poll()
        return {"configured": True}

    async def _secret_clear(
        self, payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        name = payload.get("name")
        if name != "openrouter_api_key":
            raise WisprError(ErrorCode.VALIDATION, "secrets", "name") from None
        self._secret_store.clear(name)
        if self._model_service is not None:
            await self._model_service.poll()
        return {"configured": False}

    @staticmethod
    def _settings_data(settings: object) -> dict[str, object]:
        dump = getattr(settings, "model_dump", None)
        if not callable(dump):
            raise WisprError(ErrorCode.STORAGE_ERROR, "settings", "serialization")
        data = dump(mode="json")
        if not isinstance(data, dict):
            raise WisprError(ErrorCode.STORAGE_ERROR, "settings", "serialization")
        return data
