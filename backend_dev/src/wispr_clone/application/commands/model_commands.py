"""Command handlers for model readiness and selection."""

from __future__ import annotations

from collections.abc import Mapping

from wispr_clone.application.api import CommandSpec
from wispr_clone.application.model_service import ModelService
from wispr_clone.contracts.common import ErrorCode, WisprError


class ModelCommands:
    """Expose model service operations through the validated command API."""

    def __init__(self, service: ModelService) -> None:
        self._service = service

    def specs(self) -> dict[str, CommandSpec]:
        return {
            "models_status": CommandSpec(self._status, mutating=False),
            "models_test": CommandSpec(self._test, mutating=False),
            "models_select": CommandSpec(self._select, mutating=True),
        }

    async def _status(self, _: Mapping[str, object]) -> Mapping[str, object]:
        return {"models": await self._service.status()}

    async def _test(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        model_id = payload.get("model_id")
        if not isinstance(model_id, str):
            raise WisprError(ErrorCode.VALIDATION, "models", "model_id") from None
        return await self._service.test(model_id)

    async def _select(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        model_id = payload.get("model_id")
        if not isinstance(model_id, str):
            raise WisprError(ErrorCode.VALIDATION, "models", "model_id") from None
        return await self._service.select(model_id)
