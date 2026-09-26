"""Read-only model readiness and validated model selection."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from wispr_clone.cleanup.base import CleanupEngine
from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.contracts.events import EventSink, ModelStatusItem
from wispr_clone.models.registry import ModelInfo, ModelRegistry
from wispr_clone.settings.schema import settings_to_data
from wispr_clone.settings.store import SettingsStore
from wispr_clone.stt.base import SttEngine


class ModelService:
    """Aggregate selected-model health without changing engine lifecycle."""

    def __init__(
        self,
        registry: ModelRegistry,
        store: SettingsStore,
        *,
        stt_for: Callable[[str], SttEngine | None],
        cleanup_for: Callable[[str], CleanupEngine | None],
        events: EventSink,
        health_timeout_s: float = 3.0,
    ) -> None:
        self._registry = registry
        self._store = store
        self._stt_for = stt_for
        self._cleanup_for = cleanup_for
        self._events = events
        self._health_timeout_s = health_timeout_s
        self._last_published: list[dict[str, object]] | None = None

    async def status(self) -> list[ModelStatusItem]:
        settings = self._store.current()
        models: list[ModelStatusItem] = []
        for role, model_id in (
            ("stt", settings.stt_model_id),
            ("cleanup", settings.cleanup_model_id),
        ):
            models.append(await self._readiness(model_id, role))
        return models

    async def test(self, model_id: str) -> dict[str, object]:
        model = self._known_model(model_id)
        self._enforce_local_only(model_id, model.local)
        return dict(await self._readiness(model_id, model.role))

    async def select(self, model_id: str) -> dict[str, object]:
        model = self._known_model(model_id)
        settings = await self._store.update({f"{model.role}_model_id": model_id})
        models = await self.status()
        self._events.publish({"name": "models:status", "models": models})
        self._last_published = [dict(item) for item in models]
        return {"settings": settings_to_data(settings), "models": models}

    async def poll(self) -> None:
        try:
            models = await self.status()
            if models != self._last_published:
                self._events.publish({"name": "models:status", "models": models})
                self._last_published = [dict(item) for item in models]
        except Exception:
            # A background health poll must not break its scheduler or expose details.
            return

    async def _readiness(self, model_id: str, role: str) -> ModelStatusItem:
        ready = False
        error_code: str | None = None
        if role == "stt":
            stt_engine = self._stt_for(model_id)
            if stt_engine is None:
                error_code = ErrorCode.STT_UNAVAILABLE.value
            elif stt_engine.ready:
                ready = True
            else:
                error_code = ErrorCode.MODEL_LOAD_FAILED.value
        else:
            cleanup_engine = self._cleanup_for(model_id)
            if cleanup_engine is None:
                error_code = ErrorCode.CLEANUP_UNAVAILABLE.value
            else:
                try:
                    ready = await asyncio.wait_for(
                        cleanup_engine.health(), timeout=self._health_timeout_s
                    )
                    if not ready:
                        error_code = ErrorCode.CLEANUP_UNAVAILABLE.value
                except TimeoutError:
                    error_code = ErrorCode.CLEANUP_TIMEOUT.value
                except Exception:
                    error_code = ErrorCode.CLEANUP_UNAVAILABLE.value
        return {
            "model_id": model_id,
            "role": role,
            "ready": ready,
            "error_code": error_code,
        }

    def _known_model(self, model_id: str) -> ModelInfo:
        model = self._registry.get(model_id)
        if model is None:
            raise WisprError(ErrorCode.VALIDATION, "models", "model_id") from None
        self._enforce_local_only(model_id, model.local)
        return model

    def _enforce_local_only(self, model_id: str, local: bool) -> None:
        if self._store.current().local_only and not local:
            raise WisprError(
                ErrorCode.CLOUD_MODEL_FORBIDDEN, "models", "model_id"
            ) from None
