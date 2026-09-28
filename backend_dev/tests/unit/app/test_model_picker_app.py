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
