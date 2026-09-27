"""API secret commands expose configuration status, never key material."""

from __future__ import annotations

import json
import os
import sys

import pytest

from wispr_clone.application.api import Api
from wispr_clone.application.commands.model_commands import ModelCommands
from wispr_clone.application.commands.settings_commands import SettingsCommands
from wispr_clone.application.model_service import ModelService
from wispr_clone.contracts.common import ErrorCode
from wispr_clone.models.registry import default_registry
from wispr_clone.settings.schema import default_settings

FAKE_KEY = "sk-or-v1-test-secret-command"
NAME = "openrouter_api_key"


class SettingsStub:
    def current(self):
        return default_settings()

    async def load(self):
        return self.current()


class HistoryStub:
    async def list_runs(self):
        return []


class ControllerStub:
    active_run_id = None


class EventsStub:
    def __init__(self):
        self.events = []

    def publish(self, event):
        self.events.append(event)


class SttStub:
    def __init__(self, secrets):
        self.secrets = secrets

    @property
    def ready(self):
        return self.secrets.get(NAME) is not None


class CleanupStub:
    async def health(self):
        return True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_T_APP_030_secret_commands_and_readiness() -> None:
    from wispr_clone.settings.secret_store import MemorySecretStore

    secrets = MemorySecretStore()
    events = EventsStub()
    settings = SettingsStub()
    stt = SttStub(secrets)
    service = ModelService(
        default_registry(),
        settings,
        stt_for=lambda _model_id: stt,
        cleanup_for=lambda _model_id: CleanupStub(),
        events=events,
    )
    commands = SettingsCommands(
        settings,
        HistoryStub(),
        ControllerStub(),
        session_token=lambda: "session-test",
        readiness=service.status,
        secret_store=secrets,
        model_service=service,
    )
    api = Api(
        {**commands.specs(), **ModelCommands(service).specs()},
        session_token="session-test",
        clock=lambda: 100.0,
    )
    before = await api.call("state_get", {})
    assert before.ok is True
    assert before.data["secrets"] == {NAME: {"configured": False}}
    status = await api.call("models_status", {"session_token": "session-test"})
    assert status.ok is True
    assert status.data["models"][0]["error_code"] == "api_key_missing"

    payload = {"session_token": "session-test", "deadline": 105.0}
    set_result = await api.call(
        "secret_set", {**payload, "name": NAME, "value": FAKE_KEY}
    )
    assert set_result.ok is True
    assert set_result.data == {"configured": True}
    configured = await api.call("state_get", {})
    assert configured.data["secrets"] == {NAME: {"configured": True}}
    status = await api.call("models_status", {"session_token": "session-test"})
    assert status.data["models"][0]["ready"] is True
    assert any(event["name"] == "models:status" for event in events.events)
    assert FAKE_KEY not in json.dumps(
        [set_result.data, configured.data, status.data, events.events]
    )

    unknown = await api.call(
        "secret_set", {**payload, "name": "other_secret", "value": FAKE_KEY}
    )
    assert (unknown.ok, unknown.error) == (False, ErrorCode.VALIDATION)
    cleared = await api.call("secret_clear", {**payload, "name": NAME})
    assert cleared.ok is True
    assert cleared.data == {"configured": False}
    final = await api.call("state_get", {})
    assert final.data["secrets"] == {NAME: {"configured": False}}


@pytest.mark.unit
@pytest.mark.skipif(os.name == "nt", reason="non-Windows development boundary")
def test_T_APP_031_real_factory_never_uses_volatile_key_store_outside_self_test(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from wispr_clone.app import real_factories
    from wispr_clone.settings.secret_store import MemorySecretStore

    monkeypatch.setattr(sys, "argv", ["wispr-clone"])
    factory = real_factories()
    assert factory.secret_store is not None
    assert not isinstance(factory.secret_store(), MemorySecretStore)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_T_APP_032_secret_set_normalizes_pasted_key_boundaries() -> None:
    from wispr_clone.settings.secret_store import MemorySecretStore

    secrets = MemorySecretStore()
    settings = SettingsStub()
    stt = SttStub(secrets)
    service = ModelService(
        default_registry(),
        settings,
        stt_for=lambda _model_id: stt,
        cleanup_for=lambda _model_id: CleanupStub(),
        events=EventsStub(),
    )
    commands = SettingsCommands(
        settings,
        HistoryStub(),
        ControllerStub(),
        session_token=lambda: "session-test",
        readiness=service.status,
        secret_store=secrets,
        model_service=service,
    )
    api = Api(commands.specs(), session_token="session-test", clock=lambda: 100.0)
    payload = {"session_token": "session-test", "deadline": 105.0, "name": NAME}

    for boundary in (
        " ",
        "\n",
        "\r\n",
        "\u00a0",
        "\u200b",
        "\u200c",
        "\u200d",
        "\u2060",
        "\ufeff",
    ):
        result = await api.call(
            "secret_set", {**payload, "value": boundary + FAKE_KEY + boundary}
        )
        assert result.ok is True, repr(boundary)
        assert result.data == {"configured": True}
        assert secrets.get(NAME) == FAKE_KEY

    invalid_values = [
        FAKE_KEY + character + FAKE_KEY
        for character in (" ", "\u200b", "\u200c", "\u200d", "\u2060", "\ufeff")
    ] + [" \r\n\u00a0", "\u200b\ufeff"]
    for invalid in invalid_values:
        result = await api.call("secret_set", {**payload, "value": invalid})
        assert (result.ok, result.error) == (False, ErrorCode.VALIDATION)
        assert secrets.get(NAME) == FAKE_KEY
