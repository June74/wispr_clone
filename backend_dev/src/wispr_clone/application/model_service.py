"""Model readiness, provider model lists, validated selection and model loading."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from copy import deepcopy

from wispr_clone.cleanup.base import CleanupEngine
from wispr_clone.contracts.common import ErrorCode, ThirdPartyError, WisprError
from wispr_clone.contracts.events import EventSink, ModelStatusItem
from wispr_clone.models.registry import ModelInfo, ModelRegistry
from wispr_clone.settings.schema import settings_to_data
from wispr_clone.settings.store import SettingsStore
from wispr_clone.stt.base import SttEngine

logger = logging.getLogger(__name__)

ModelLister = Callable[[], Awaitable[list[dict[str, object]]]]
CATALOG_TIMEOUT_S = 12.0
LOAD_RETRY_S = 60.0


class ModelService:
    """Aggregate model health, list pickable models, keep the cleanup model loaded."""

    def __init__(
        self,
        registry: ModelRegistry,
        store: SettingsStore,
        *,
        stt_for: Callable[[str], SttEngine | None],
        cleanup_for: Callable[[str], CleanupEngine | None],
        events: EventSink,
        health_timeout_s: float = 3.0,
        list_stt: ModelLister | None = None,
        list_cleanup: ModelLister | None = None,
        load_cleanup: Callable[[str], Awaitable[bool]] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._registry = registry
        self._store = store
        self._stt_for = stt_for
        self._cleanup_for = cleanup_for
        self._events = events
        self._health_timeout_s = health_timeout_s
        self._last_published: list[ModelStatusItem] | None = None
        self._publication_lock = asyncio.Lock()
        self._generation = 0
        self._list_stt = list_stt
        self._list_cleanup = list_cleanup
        self._load_cleanup = load_cleanup
        self._clock = clock
        self._loading: str | None = None
        self._load_retry_at: dict[str, float] = {}

    async def status(self) -> list[ModelStatusItem]:
        settings = self._store.current()
        models: list[ModelStatusItem] = []
        for role, model_id in (
            ("stt", settings.stt_model_id),
            ("cleanup", settings.cleanup_model_id),
        ):
            models.append(await self._readiness(model_id, role))
        return models

    async def test(self, model_id: str, role: str | None = None) -> dict[str, object]:
        model = self._known_model(model_id, role)
        return dict(await self._readiness(model_id, model.role))

    async def catalog(self) -> dict[str, object]:
        """Models the user can pick per role, read live from each provider.

        The current selection is always listed, flagged ``missing`` when the
        provider no longer offers it, so the picker never silently changes it.
        """
        settings = self._store.current()
        result: dict[str, object] = {}
        for role, lister, current in (
            ("stt", self._list_stt, settings.stt_model_id),
            ("cleanup", self._list_cleanup, settings.cleanup_model_id),
        ):
            models: list[dict[str, object]] = []
            error_code: str | None = None
            if lister is None:
                error_code = (
                    ErrorCode.STT_UNAVAILABLE
                    if role == "stt"
                    else ErrorCode.CLEANUP_UNAVAILABLE
                ).value
            else:
                try:
                    models = list(
                        await asyncio.wait_for(lister(), timeout=CATALOG_TIMEOUT_S)
                    )
                except ThirdPartyError as error:
                    error_code = error.error_code.value
                except TimeoutError:
                    error_code = (
                        ErrorCode.STT_TIMEOUT
                        if role == "stt"
                        else ErrorCode.CLEANUP_TIMEOUT
                    ).value
            if not any(model.get("model_id") == current for model in models):
                known = self._registry.get(current)
                models.insert(
                    0,
                    {
                        "model_id": current,
                        "display_name": known.display_name if known else current,
                        "missing": error_code is None,
                    },
                )
            result[role] = {"models": models, "error_code": error_code}
        return result

    async def keep_cleanup_loaded(self, *, force: bool = False) -> None:
        """Ask LM Studio to load the selected cleanup model when it is not loaded.

        Failed loads are retried after LOAD_RETRY_S unless ``force`` (a new
        selection). Never raises: this runs from a background timer.
        """
        settings = self._store.current()
        model_id = settings.cleanup_model_id
        if (
            self._load_cleanup is None
            or not settings.cleanup_enabled
            or self._loading is not None
            or (not force and self._clock() < self._load_retry_at.get(model_id, 0.0))
        ):
            return
        self._loading = model_id
        try:
            await self.poll()
            loaded = await self._load_cleanup(model_id)
            self._load_retry_at.pop(model_id, None)
            if loaded:
                logger.info("CLEANUP_MODEL_LOADED")
        except Exception:
            logger.warning("CLEANUP_MODEL_LOAD_FAILED")
            self._load_retry_at[model_id] = self._clock() + LOAD_RETRY_S
        finally:
            self._loading = None
            await self.poll()

    async def select(self, model_id: str, role: str | None = None) -> dict[str, object]:
        model = self._known_model(model_id, role)
        async with self._publication_lock:
            self._generation += 1
            settings = await self._store.update({f"{model.role}_model_id": model_id})
            models = await self.status()
            self._events.publish({"name": "models:status", "models": deepcopy(models)})
            self._last_published = deepcopy(models)
            return {"settings": settings_to_data(settings), "models": deepcopy(models)}

    async def poll(self) -> None:
        try:
            generation = self._generation
            models = await self.status()
            async with self._publication_lock:
                if generation != self._generation:
                    return
                if models != self._last_published:
                    self._events.publish(
                        {"name": "models:status", "models": deepcopy(models)}
                    )
                    self._last_published = deepcopy(models)
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
                # The OpenRouter engine is ready exactly when an API key is saved.
                error_code = ErrorCode.API_KEY_MISSING.value
        else:
            cleanup_engine = self._cleanup_for(model_id)
            if cleanup_engine is None:
                error_code = ErrorCode.CLEANUP_UNAVAILABLE.value
            else:
                try:
                    health = await asyncio.wait_for(
                        cleanup_engine.health(), timeout=self._health_timeout_s
                    )
                    ready = health is True
                    if not ready:
                        error_code = (
                            ErrorCode.MODEL_LOADING
                            if self._loading == model_id
                            else ErrorCode.CLEANUP_UNAVAILABLE
                        ).value
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

    def _known_model(self, model_id: str, role: str | None = None) -> ModelInfo:
        model = (
            self._registry.get(model_id)
            if role is None
            else self._registry.resolve(role, model_id)
        )
        if model is None:
            raise WisprError(ErrorCode.VALIDATION, "models", "model_id") from None
        return model
