"""Metadata-only model registry with local endpoint boundary checks."""

import ipaddress
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from wispr_clone import config
from wispr_clone.contracts.common import ErrorCode, WisprError

ModelRole = Literal["stt", "cleanup"]


@dataclass(frozen=True, slots=True)
class ModelInfo:
    """Descriptive metadata for a supported inference model."""

    model_id: str
    role: ModelRole
    display_name: str
    local: bool
    runtime: str
    endpoint: str | None


class ModelRegistry:
    """Immutable-in-practice registration-order catalog of model metadata."""

    def __init__(self, models: Iterable[ModelInfo]) -> None:
        ordered = tuple(models)
        indexed: dict[str, ModelInfo] = {}
        for model in ordered:
            if not model.model_id or model.model_id in indexed:
                raise WisprError(
                    ErrorCode.VALIDATION, "models.registry", "model_id"
                ) from None
            if (
                model.local
                and model.endpoint is not None
                and not is_loopback_endpoint(model.endpoint)
            ):
                raise WisprError(
                    ErrorCode.NON_LOOPBACK_ENDPOINT,
                    "models.registry",
                    "endpoint",
                ) from None
            indexed[model.model_id] = model
        self._models = ordered
        self._by_id = indexed

    def list_models(self, role: ModelRole | None = None) -> tuple[ModelInfo, ...]:
        """List models in registration order, optionally filtered by role."""
        if role is None:
            return self._models
        return tuple(model for model in self._models if model.role == role)

    def get(self, model_id: str) -> ModelInfo | None:
        """Return metadata for a known identifier."""
        return self._by_id.get(model_id)

    def role_of(self, model_id: str) -> str | None:
        """Return the registered role, or None when the identifier is unknown."""
        model = self.get(model_id)
        return model.role if model is not None else None

    def is_local(self, model_id: str) -> bool:
        """Return whether a known model is local; unknown identifiers are false."""
        model = self.get(model_id)
        return model.local if model is not None else False


def is_loopback_endpoint(url: str) -> bool:
    """Return whether a valid HTTP(S) URL uses a loopback IP literal host."""
    try:
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            return False
        host = parsed.hostname
        if host is None:
            return False
        return ipaddress.ip_address(host).is_loopback
    except (ValueError, TypeError):
        return False


def default_registry() -> ModelRegistry:
    """Build the two selected local models in stable UI order."""
    return ModelRegistry(
        (
            ModelInfo(
                "voxtral-mini-4b-realtime-2602",
                "stt",
                "Voxtral Mini 4B Realtime",
                True,
                "transcribe-cpp",
                None,
            ),
            ModelInfo(
                config.LM_STUDIO_MODEL_ID,
                "cleanup",
                "Llama 3.1 8B Instruct",
                True,
                "lmstudio",
                config.LM_STUDIO_ENDPOINT,
            ),
        )
    )
