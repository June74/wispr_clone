"""T-APP-052: a model choice takes effect without restarting the app."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from ._support import Boundaries


class FakeLmStudio:
    def __init__(self) -> None:
        self.loads: list[str] = []

    async def list_chat_models(self) -> list[dict[str, object]]:
        return [
            {"model_id": "qwen/qwen3-8b", "display_name": "Qwen3 8B", "loaded": False}
        ]

    async def ensure_loaded(self, model_id: str) -> bool:
        self.loads.append(model_id)
        return True


@pytest.mark.asyncio
async def test_T_APP_052_select_switches_stt_and_loads_cleanup(tmp_path: Path) -> None:
    from wispr_clone.app import App

    boundaries = Boundaries()
    lmstudio = FakeLmStudio()
    switched: list[str] = []
    boundaries.stt.model = "openai/whisper-large-v3-turbo"  # type: ignore[attr-defined]
    boundaries.stt.use_model = switched.append  # type: ignore[attr-defined]
    app = App(
        replace(boundaries.factories(), lmstudio_models=lambda: lmstudio),
        data_dir=tmp_path,
    )
    app._loop = asyncio.get_running_loop()
    await app.startup()
    api = app.api
    base = {"session_token": api.session_token, "deadline": 1010.0}
    try:
        catalog = await api.call("models_catalog", {"session_token": api.session_token})
        assert catalog.ok
        assert [m["model_id"] for m in catalog.data["cleanup"]["models"]] == [
            "meta-llama-3.1-8b-instruct",
            "qwen/qwen3-8b",
        ]
        # No live speech list is configured in tests: reported, not raised.
        assert catalog.data["stt"]["error_code"] == "stt_unavailable"

        stt = await api.call(
            "models_select", {**base, "model_id": "deepgram/nova-3", "role": "stt"}
        )
        assert stt.ok
        assert switched == ["deepgram/nova-3"]
        assert app._settings.stt_model_id == "deepgram/nova-3"

        cleanup = await api.call(
            "models_select", {**base, "model_id": "qwen/qwen3-8b", "role": "cleanup"}
        )
        assert cleanup.ok
        for _ in range(50):
            if lmstudio.loads and lmstudio.loads[-1] == "qwen/qwen3-8b":
                break
            await asyncio.sleep(0.01)
        assert lmstudio.loads[-1] == "qwen/qwen3-8b"

        bad = await api.call("models_select", {**base, "model_id": "x", "role": "tts"})
        assert bad.error.value == "validation"
    finally:
        await app.shutdown()


@pytest.mark.asyncio
async def test_nvidia_provider_routes_cleanup_and_preserves_local_selection(
    tmp_path: Path,
) -> None:
    import json

    import httpx

    from wispr_clone import config
    from wispr_clone.app import App
    from wispr_clone.cleanup.base import CleanupRequest
    from wispr_clone.cleanup.nvidia_cleanup import NvidiaCleanup
    from wispr_clone.settings.secret_store import MemorySecretStore

    boundaries = Boundaries()
    lmstudio = FakeLmStudio()
    secrets = MemorySecretStore()
    engines = []
    attempted = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer nvapi-fake-test"
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "data": [{"id": model} for model in config.NVIDIA_CLEANUP_MODEL_IDS]
                },
            )
        model = json.loads(request.content)["model"]
        attempted.append(model)
        if model == config.NVIDIA_CLEANUP_MODEL_IDS[0]:
            return httpx.Response(429, headers={"Retry-After": "60"})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"content": "fixed text"}}
                ]
            },
        )

    def cloud(model_ids, key):
        engine = NvidiaCleanup(
            api_key=key, model_ids=model_ids, transport=httpx.MockTransport(respond)
        )
        engines.append(engine)
        return engine

    app = App(
        replace(
            boundaries.factories(),
            secret_store=lambda: secrets,
            nvidia_cleanup=cloud,
            lmstudio_models=lambda: lmstudio,
        ),
        data_dir=tmp_path,
    )
    app._loop = asyncio.get_running_loop()
    await app.startup()
    api = app.api
    base = {"session_token": api.session_token, "deadline": 1010.0}
    try:
        if app._load_task:
            await app._load_task
        local_loads = list(lmstudio.loads)
        updated = await api.call(
            "settings_update", {**base, "patch": {"cleanup_provider": "nvidia"}}
        )
        assert updated.ok
        if app._load_task:
            await app._load_task
        assert lmstudio.loads == local_loads
        status = await api.call("models_status", {"session_token": api.session_token})
        assert status.data["models"][1]["error_code"] == "nvidia_api_key_missing"
        saved = await api.call(
            "secret_set", {**base, "name": "nvidia_api_key", "value": "nvapi-fake-test"}
        )
        assert saved.ok
        state = await api.call("state_get", {})
        assert state.data["models"][1]["ready"] is True
        assert state.data["settings"]["cleanup_model_id"] == config.LM_STUDIO_MODEL_ID
        assert "nvapi-fake-test" not in json.dumps(state.data)
        catalog = await api.call("models_catalog", {"session_token": api.session_token})
        assert catalog.data["cleanup"]["provider"] == "nvidia"
        snapshot = dict(state.data["settings"])
        engine = app._cleanup_for_config(snapshot)
        assert await engine.clean(CleanupRequest(text="fixed text")) == "fixed text"
        assert attempted == list(config.NVIDIA_CLEANUP_MODEL_IDS[:2])
        new_order = [config.NVIDIA_CLEANUP_MODEL_IDS[-1]]
        changed = await api.call(
            "settings_update",
            {**base, "patch": {"nvidia_cleanup_model_ids": new_order}},
        )
        assert changed.ok
        assert app._cleanup_for_config(snapshot) is engine
        assert app._cleanup_for_config(changed.data) is not engine
        selected = await api.call(
            "models_select", {**base, "role": "cleanup", "model_id": "z-ai/glm-5.3"}
        )
        assert selected.ok
        assert selected.data["settings"]["nvidia_cleanup_model_ids"] == [
            "z-ai/glm-5.3",
            "moonshotai/kimi-k3",
        ]
        assert (
            selected.data["settings"]["cleanup_model_id"] == config.LM_STUDIO_MODEL_ID
        )
        restored = await api.call(
            "settings_update", {**base, "patch": {"cleanup_provider": "lmstudio"}}
        )
        assert restored.ok
        if app._load_task:
            await app._load_task
        assert len(lmstudio.loads) == len(local_loads) + 1
        assert lmstudio.loads[-1] == config.LM_STUDIO_MODEL_ID
    finally:
        await app.shutdown()
    assert engines and all([not await engine.health() for engine in engines])
