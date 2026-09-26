"""Strict, versioned settings values and schema upgrades."""

from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from wispr_clone import config
from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.contracts.shortcuts import (
    format_binding,
    parse_binding,
    validate_bindings,
)

SETTINGS_SCHEMA_VERSION: int = 1


class ModelCatalog(Protocol):
    """The model metadata needed to validate a settings selection."""

    def role_of(self, model_id: str) -> str | None: ...

    def is_local(self, model_id: str) -> bool: ...


class Settings(BaseModel):
    """Immutable user preferences validated before use or persistence."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    schema_version: int = SETTINGS_SCHEMA_VERSION
    recording_mode: Literal["toggle", "hold"] = "toggle"
    dictation_shortcut: str = Field(
        default="ctrl+shift+space", min_length=1, max_length=64
    )
    cancel_shortcut: str = Field(default="escape", min_length=1, max_length=64)
    microphone_id: str | None = Field(default=None, min_length=1, max_length=256)
    stt_model_id: str = "voxtral-mini-4b-realtime-2602"
    cleanup_model_id: str = "meta-llama-3.1-8b-instruct"
    cleanup_enabled: bool = True
    cleanup_instructions: str = Field(default="", max_length=2000)
    local_only: bool = True
    theme: Literal["system", "light", "dark"] = "light"
    idle_jump_seconds: float = Field(default=config.IDLE_JUMP_SECONDS, ge=0.5, le=10.0)
    return_settle_seconds: float = Field(
        default=config.RETURN_SETTLE_SECONDS, ge=0.1, le=2.0
    )
    destination_wait_limit_seconds: int = Field(
        default=config.DESTINATION_WAIT_LIMIT_SECONDS, ge=60, le=3600
    )


UpgradeStep = Callable[[dict[str, object]], dict[str, object]]
UPGRADE_STEPS: Mapping[int, UpgradeStep] = {}


def default_settings() -> Settings:
    """Construct settings with the current schema's pinned defaults."""
    return Settings()


def parse_settings(
    data: Mapping[str, object],
    catalog: ModelCatalog,
    *,
    upgrade_steps: Mapping[int, UpgradeStep] = UPGRADE_STEPS,
) -> Settings:
    """Upgrade and validate stored data, then enforce model selection policy."""
    upgraded = deepcopy(dict(data))
    version = upgraded.get("schema_version")
    if type(version) is not int:
        raise WisprError(
            ErrorCode.VALIDATION, "settings.schema", "schema_version"
        ) from None
    if version > SETTINGS_SCHEMA_VERSION:
        raise WisprError(
            ErrorCode.VALIDATION, "settings.schema", "schema_version"
        ) from None

    while version < SETTINGS_SCHEMA_VERSION:
        step = upgrade_steps.get(version)
        if step is None:
            raise WisprError(
                ErrorCode.VALIDATION, "settings.schema", "schema_version"
            ) from None
        try:
            result = step(deepcopy(upgraded))
        except Exception:
            raise WisprError(
                ErrorCode.VALIDATION, "settings.schema", "schema_version"
            ) from None
        if not isinstance(result, dict):
            raise WisprError(
                ErrorCode.VALIDATION, "settings.schema", "schema_version"
            ) from None
        upgraded = result
        next_version = upgraded.get("schema_version")
        if type(next_version) is not int or next_version != version + 1:
            raise WisprError(
                ErrorCode.VALIDATION, "settings.schema", "schema_version"
            ) from None
        version = next_version

    try:
        settings = Settings.model_validate(upgraded)
    except ValidationError as error:
        fields = sorted(
            {
                str(location[0])
                for item in error.errors(include_input=False)
                if (location := item.get("loc"))
            }
        )
        raise WisprError(
            ErrorCode.VALIDATION,
            "settings.schema",
            ", ".join(fields) if fields else "settings",
        ) from None

    try:
        dictation_binding = parse_binding(settings.dictation_shortcut)
    except WisprError:
        raise WisprError(
            ErrorCode.VALIDATION, "settings.schema", "dictation_shortcut"
        ) from None
    try:
        cancel_binding = parse_binding(settings.cancel_shortcut)
    except WisprError:
        raise WisprError(
            ErrorCode.VALIDATION, "settings.schema", "cancel_shortcut"
        ) from None
    try:
        validate_bindings(dictation_binding, cancel_binding)
    except WisprError:
        raise WisprError(
            ErrorCode.VALIDATION,
            "settings.schema",
            "dictation_shortcut, cancel_shortcut",
        ) from None
    settings = settings.model_copy(
        update={
            "dictation_shortcut": format_binding(dictation_binding),
            "cancel_shortcut": format_binding(cancel_binding),
        }
    )

    if catalog.role_of(settings.stt_model_id) != "stt":
        raise WisprError(
            ErrorCode.VALIDATION, "settings.schema", "stt_model_id"
        ) from None
    if catalog.role_of(settings.cleanup_model_id) != "cleanup":
        raise WisprError(
            ErrorCode.VALIDATION, "settings.schema", "cleanup_model_id"
        ) from None
    if settings.local_only and not catalog.is_local(settings.stt_model_id):
        raise WisprError(
            ErrorCode.CLOUD_MODEL_FORBIDDEN, "settings.schema", "stt_model_id"
        ) from None
    if settings.local_only and not catalog.is_local(settings.cleanup_model_id):
        raise WisprError(
            ErrorCode.CLOUD_MODEL_FORBIDDEN, "settings.schema", "cleanup_model_id"
        ) from None
    return settings


def settings_to_data(settings: Settings) -> dict[str, object]:
    """Return JSON-compatible settings data without mutable model internals."""
    return settings.model_dump(mode="json")
