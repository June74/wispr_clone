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

SETTINGS_SCHEMA_VERSION: int = 3


class ModelCatalog(Protocol):
    """The model metadata needed to validate a settings selection."""

    def role_of(self, model_id: str) -> str | None: ...


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
    stt_model_id: str = "openai/whisper-large-v3-turbo"
    cleanup_model_id: str = "meta-llama-3.1-8b-instruct"
    cleanup_enabled: bool = True
    cleanup_instructions: str = Field(default="", max_length=2000)
    theme: Literal["system", "light", "dark"] = "light"
    sound_cues: bool = False
    idle_jump_seconds: float = Field(default=config.IDLE_JUMP_SECONDS, ge=0.5, le=10.0)
    return_settle_seconds: float = Field(
        default=config.RETURN_SETTLE_SECONDS, ge=0.1, le=2.0
    )
    destination_wait_limit_seconds: int = Field(
        default=config.DESTINATION_WAIT_LIMIT_SECONDS, ge=60, le=3600
    )


UpgradeStep = Callable[[dict[str, object]], dict[str, object]]


def _upgrade_v1(data: dict[str, object]) -> dict[str, object]:
    data["schema_version"] = 2
    if data.get("stt_model_id") == "voxtral-mini-4b-realtime-2602":
        data["stt_model_id"] = "openai/whisper-large-v3-turbo"
    data["local_only"] = False
    return data


def _upgrade_v2(data: dict[str, object]) -> dict[str, object]:
    data.pop("local_only", None)
    data["schema_version"] = 3
    return data


UPGRADE_STEPS: Mapping[int, UpgradeStep] = {1: _upgrade_v1, 2: _upgrade_v2}


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

    for role, field in (("stt", "stt_model_id"), ("cleanup", "cleanup_model_id")):
        model_id = getattr(settings, field)
        if not _model_is_usable(catalog, role, model_id):
            raise WisprError(ErrorCode.VALIDATION, "settings.schema", field) from None
    return settings


def _model_is_usable(catalog: ModelCatalog, role: str, model_id: str) -> bool:
    """Whether a registered or discovered identifier is valid for its role.

    Registered models must match their role. Other identifiers are accepted
    when the catalog knows how to discover models for the role (``accepts``).
    """
    known = catalog.role_of(model_id)
    if known is not None:
        return known == role
    accepts = getattr(catalog, "accepts", None)
    if callable(accepts) and accepts(role, model_id):
        return True
    return False


def settings_to_data(settings: Settings) -> dict[str, object]:
    """Return JSON-compatible settings data without mutable model internals."""
    return settings.model_dump(mode="json")
