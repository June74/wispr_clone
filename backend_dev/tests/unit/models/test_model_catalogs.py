"""T-MOD-001..004: live model lists and LM Studio loading (fake HTTP only)."""

from __future__ import annotations

import json

import httpx
import pytest

from wispr_clone.cleanup.lmstudio_models import LmStudioModels
from wispr_clone.contracts.common import ErrorCode, ThirdPartyError
from wispr_clone.stt.openrouter_catalog import CACHE_S, OpenRouterCatalog

LMS_MODELS = {
    "models": [
        {
            "type": "llm",
            "key": "meta-llama-3.1-8b-instruct",
            "architecture": "llama",
            "display_name": "Meta Llama 3.1 8B Instruct",
            "loaded_instances": [{"id": "x"}],
            "size_bytes": 5,
        },
        {
            "type": "llm",
            "key": "qwen/qwen3-8b",
            "architecture": "qwen3",
            "display_name": "Qwen3 8B",
            "loaded_instances": [],
        },
        {
            "type": "llm",
            "key": "voxtral-mini-4b-realtime-2602",
            "architecture": "voxtral_realtime",
            "loaded_instances": [],
        },
        {"type": "embedding", "key": "text-embedding-nomic", "loaded_instances": []},
    ]
}


def lmstudio(handler) -> LmStudioModels:
    return LmStudioModels(
        base_url="http://127.0.0.1:1234/v1", transport=httpx.MockTransport(handler)
    )


@pytest.mark.asyncio
async def test_T_MOD_001_lists_chat_models_without_speech_or_embeddings() -> None:
    models = lmstudio(lambda request: httpx.Response(200, json=LMS_MODELS))
    listed = await models.list_chat_models()
    assert [(m["model_id"], m["display_name"], m["loaded"]) for m in listed] == [
        ("meta-llama-3.1-8b-instruct", "Meta Llama 3.1 8B Instruct", True),
        ("qwen/qwen3-8b", "Qwen3 8B", False),
    ]


@pytest.mark.asyncio
async def test_T_MOD_002_loads_only_when_not_loaded_through_v1_api() -> None:
    requests: list[tuple[str, str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        requests.append((request.method, request.url.path, body))
        if request.method == "POST":
            return httpx.Response(200, json={"status": "loaded"})
        return httpx.Response(200, json=LMS_MODELS)

    models = lmstudio(handler)
    assert await models.ensure_loaded("meta-llama-3.1-8b-instruct") is False
    assert await models.ensure_loaded("qwen/qwen3-8b") is True
    assert requests == [
        ("GET", "/api/v1/models", None),
        ("GET", "/api/v1/models", None),
        ("POST", "/api/v1/models/load", {"model": "qwen/qwen3-8b"}),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(500), ErrorCode.MODEL_LOAD_FAILED),
        (httpx.ConnectError("refused"), ErrorCode.CLEANUP_UNAVAILABLE),
    ],
)
async def test_T_MOD_002_load_failures_are_normalized(
    response: object, code: ErrorCode
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"models": []})
        if isinstance(response, Exception):
            raise response
        return response  # type: ignore[return-value]

    with pytest.raises(ThirdPartyError) as caught:
        await lmstudio(handler).ensure_loaded("qwen/qwen3-8b")
    assert caught.value.error_code == code


@pytest.mark.unit
def test_T_MOD_003_lmstudio_must_be_loopback() -> None:
    with pytest.raises(ThirdPartyError) as caught:
        LmStudioModels(base_url="http://192.168.1.5:1234")
    assert caught.value.error_code == ErrorCode.NON_LOOPBACK_ENDPOINT


@pytest.mark.asyncio
async def test_T_MOD_004_openrouter_transcription_models_are_cached() -> None:
    calls: list[httpx.URL] = []
    now = [0.0]

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "openai/whisper-large-v3-turbo", "name": "Whisper Turbo"},
                    {"id": "deepgram/nova-3"},
                    {"name": "no id"},
                ]
            },
        )

    catalog = OpenRouterCatalog(
        clock=lambda: now[0], transport=httpx.MockTransport(handler)
    )
    first = await catalog.list_models()
    assert first == [
        {"model_id": "openai/whisper-large-v3-turbo", "display_name": "Whisper Turbo"},
        {"model_id": "deepgram/nova-3", "display_name": "deepgram/nova-3"},
    ]
    assert calls[0].params["output_modalities"] == "transcription"
    assert "authorization" not in {k.lower() for k in calls[0].params}
    now[0] = CACHE_S - 1
    assert await catalog.list_models() == first
    assert len(calls) == 1
    now[0] = CACHE_S + 1
    await catalog.list_models()
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_T_MOD_004_openrouter_outage_is_stt_unavailable() -> None:
    catalog = OpenRouterCatalog(
        transport=httpx.MockTransport(lambda r: httpx.Response(503))
    )
    with pytest.raises(ThirdPartyError) as caught:
        await catalog.list_models()
    assert caught.value.error_code == ErrorCode.STT_UNAVAILABLE
