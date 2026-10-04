"""Hosted cleanup boundaries use real httpx requests with an offline transport."""

import asyncio
import json
import traceback
from contextlib import asynccontextmanager

import httpx
import pytest

from wispr_clone import config
from wispr_clone.cleanup.base import CleanupRequest
from wispr_clone.cleanup.nvidia_cleanup import NvidiaCleanup
from wispr_clone.cleanup.prompt_builder import build_messages
from wispr_clone.contracts.common import ErrorCode, ThirdPartyError, WisprError

pytestmark = pytest.mark.unit
KEY = "nvapi-test-private-key"
MODELS = config.NVIDIA_CLEANUP_MODEL_IDS


def completion(text="hello world again", finish_reason="stop"):
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {"content": text},
                    "finish_reason": finish_reason,
                }
            ]
        },
    )


@asynccontextmanager
async def engine(handler, **kwargs):
    adapter = NvidiaCleanup(
        api_key=kwargs.pop("api_key", lambda: KEY),
        transport=httpx.MockTransport(handler),
        **kwargs,
    )
    try:
        yield adapter
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_success_uses_fixed_host_auth_and_shared_cleanup_prompt() -> None:
    calls = []
    request = CleanupRequest(
        "hello um world again", ("OpenWhispr",), "Keep identifiers"
    )

    def handler(http_request):
        calls.append(http_request)
        return completion(" hello world again ")

    async with engine(handler) as adapter:
        assert await adapter.clean(request) == "hello world again"
        assert adapter.model_ids == MODELS
    assert len(calls) == 1
    assert str(calls[0].url) == config.NVIDIA_ENDPOINT + "/chat/completions"
    assert calls[0].headers["Authorization"] == "Bearer " + KEY
    body = json.loads(calls[0].content)
    assert body["model"] == MODELS[0]
    assert body["messages"] == build_messages(request)
    assert body["stream"] is False
    assert body["temperature"] == 0 and body["max_tokens"] == 4096
    assert "reasoning_effort" not in body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model_ids",
    [MODELS, (MODELS[0], "z-ai/glm-5.3-flash", MODELS[2])],
)
async def test_fallback_order_and_supported_reasoning_parameters(model_ids) -> None:
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        return completion() if body["model"] == model_ids[2] else httpx.Response(429)

    async with engine(handler, model_ids=model_ids) as adapter:
        assert (
            await adapter.clean(CleanupRequest("hello world again"))
            == "hello world again"
        )
    assert [body["model"] for body in bodies] == list(model_ids)
    assert "reasoning_effort" not in bodies[0]
    assert [body["reasoning_effort"] for body in bodies[1:]] == ["low", "low"]


@pytest.mark.asyncio
async def test_nemotron_cleanup_disables_thinking_for_only_that_model() -> None:
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return completion()

    for model_id in ("nvidia/nemotron-3.5-lightning-30b-a3b", MODELS[0]):
        async with engine(handler, model_ids=(model_id,)) as adapter:
            assert (
                await adapter.clean(CleanupRequest("hello world again"))
                == "hello world again"
            )
    assert bodies[0].get("chat_template_kwargs") == {"enable_thinking": False}
    assert "reasoning_effort" not in bodies[0]
    assert "chat_template_kwargs" not in bodies[1]
    assert bodies[0]["messages"] == bodies[1]["messages"]


@pytest.mark.asyncio
async def test_queued_response_polls_only_the_fixed_host_until_completed() -> None:
    request_id = "7fd81c6e-cd14-4e10-a7cd-864ebf33881a"
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "POST":
            return httpx.Response(
                202,
                headers={
                    "NVCF-REQID": request_id,
                    "Location": "https://untrusted.invalid/collect-key",
                },
            )
        if len(calls) == 2:
            return httpx.Response(202)
        return completion()

    async with engine(handler) as adapter:
        assert (
            await adapter.clean(CleanupRequest("hello world again"))
            == "hello world again"
        )
    assert [request.method for request in calls] == ["POST", "GET", "GET"]
    assert [str(request.url) for request in calls[1:]] == [
        config.NVIDIA_ENDPOINT + "/status/" + request_id,
        config.NVIDIA_ENDPOINT + "/status/" + request_id,
    ]
    assert all(request.headers["Authorization"] == "Bearer " + KEY for request in calls)


@pytest.mark.asyncio
async def test_cancelling_a_queued_request_stops_polling_and_fallback() -> None:
    cancelled = [False]
    calls = []

    def handler(request):
        calls.append(request)
        cancelled[0] = True
        return httpx.Response(
            202,
            headers={
                "NVCF-REQID": "7fd81c6e-cd14-4e10-a7cd-864ebf33881a",
            },
        )

    async with engine(handler) as adapter:
        with pytest.raises(ThirdPartyError):
            await adapter.clean(
                CleanupRequest("hello world again", cancelled=lambda: cancelled[0])
            )
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "request_id", ["", "../../models", "https://untrusted.invalid/", "not-a-uuid"]
)
async def test_queued_request_ids_cannot_redirect_credentials(request_id) -> None:
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(202, headers={"NVCF-REQID": request_id})

    async with engine(handler) as adapter:
        with pytest.raises(ThirdPartyError) as caught:
            await adapter.clean(CleanupRequest("hello world again"))
        assert caught.value.error_code == ErrorCode.CLEANUP_UNAVAILABLE
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_queued_request_respects_the_existing_attempt_timeout() -> None:
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            202, headers={"NVCF-REQID": "7fd81c6e-cd14-4e10-a7cd-864ebf33881a"}
        )

    async with engine(
        handler, model_ids=(MODELS[0],), attempt_timeout_s=0.01
    ) as adapter:
        with pytest.raises(ThirdPartyError) as caught:
            await adapter.clean(CleanupRequest("hello world again"))
        assert caught.value.error_code == ErrorCode.CLEANUP_TIMEOUT
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_rate_limit_cooldown_restores_the_preferred_model() -> None:
    now = [1000.0]
    calls = []

    def handler(request):
        model = json.loads(request.content)["model"]
        calls.append(model)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "5"})
        return completion()

    async with engine(handler, clock=lambda: now[0]) as adapter:
        assert (
            await adapter.clean(CleanupRequest("hello world again"))
            == "hello world again"
        )
        now[0] += 4
        await adapter.clean(CleanupRequest("hello world again"))
        now[0] += 2
        await adapter.clean(CleanupRequest("hello world again"))
    assert calls == [MODELS[0], MODELS[1], MODELS[1], MODELS[0]]


@pytest.mark.asyncio
@pytest.mark.parametrize("retry_after", ["9999999999", "garbage", "NaN", "inf"])
async def test_retry_after_is_bounded_and_malformed_values_use_default(
    retry_after,
) -> None:
    now = [1000.0]
    calls = []

    def handler(request):
        model = json.loads(request.content)["model"]
        calls.append(model)
        return (
            httpx.Response(429, headers={"Retry-After": retry_after})
            if len(calls) == 1
            else completion()
        )

    async with engine(handler, clock=lambda: now[0], max_cooldown_s=10.0) as adapter:
        await adapter.clean(CleanupRequest("hello world again"))
        now[0] += 9
        await adapter.clean(CleanupRequest("hello world again"))
        now[0] += 2
        await adapter.clean(CleanupRequest("hello world again"))
    assert calls == [MODELS[0], MODELS[1], MODELS[1], MODELS[0]]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [404, 408, 409, 425, 429, 500, 502, 503, 504])
async def test_model_unavailability_and_transient_errors_try_next_model(status) -> None:
    calls = []

    def handler(request):
        calls.append(json.loads(request.content)["model"])
        return httpx.Response(status) if len(calls) == 1 else completion()

    async with engine(handler) as adapter:
        assert (
            await adapter.clean(CleanupRequest("hello world again"))
            == "hello world again"
        )
    assert calls == list(MODELS[:2])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,error",
    [
        (401, ErrorCode.NVIDIA_API_KEY_INVALID),
        (403, ErrorCode.NVIDIA_API_KEY_INVALID),
        (402, ErrorCode.CLEANUP_UNAVAILABLE),
        (400, ErrorCode.CLEANUP_UNAVAILABLE),
        (307, ErrorCode.CLEANUP_UNAVAILABLE),
    ],
)
async def test_auth_account_credits_bad_requests_and_redirects_stop_chain(
    status, error
) -> None:
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status, headers={"Location": "https://untrusted.invalid/"}, text=KEY
        )

    async with engine(handler) as adapter:
        with pytest.raises(ThirdPartyError) as caught:
            await adapter.clean(CleanupRequest("hello world again"))
        assert caught.value.error_code == error
        assert KEY not in str(caught.value) and KEY not in caught.value.detail
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_exhausted_chain_is_finite_and_cooldowns_avoid_repeating_requests() -> (
    None
):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content)["model"])
        return httpx.Response(429)

    async with engine(handler) as adapter:
        for _ in range(2):
            with pytest.raises(ThirdPartyError) as caught:
                await adapter.clean(CleanupRequest("hello world again"))
            assert caught.value.error_code == ErrorCode.CLEANUP_UNAVAILABLE
    assert calls == list(MODELS)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "finish_reason", ["length", "content_filter", "tool_calls", "function_call"]
)
async def test_truncated_filtered_or_tool_completions_are_never_insertable(
    finish_reason,
) -> None:
    calls = []

    def handler(request):
        calls.append(request)
        return (
            completion("hello world", finish_reason)
            if len(calls) == 1
            else completion()
        )

    async with engine(handler) as adapter:
        assert (
            await adapter.clean(CleanupRequest("hello world again"))
            == "hello world again"
        )
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [None, [], {}, {"choices": []}, {"choices": [{"message": {"content": ""}}]}],
)
async def test_malformed_or_empty_response_tries_next_model(payload) -> None:
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=payload) if len(calls) == 1 else completion()

    async with engine(handler) as adapter:
        assert (
            await adapter.clean(CleanupRequest("hello world again"))
            == "hello world again"
        )
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_per_attempt_timeout_allows_fallback_within_total_budget() -> None:
    calls = []

    async def handler(request):
        calls.append(json.loads(request.content)["model"])
        if len(calls) == 1:
            await asyncio.Event().wait()
        return completion()

    async with engine(handler, timeout_s=1.0, attempt_timeout_s=0.01) as adapter:
        assert (
            await adapter.clean(CleanupRequest("hello world again"))
            == "hello world again"
        )
    assert calls == list(MODELS[:2])


@pytest.mark.asyncio
async def test_slow_preferred_models_reserve_time_for_the_last_fallback() -> None:
    model_ids = (*MODELS, "nvidia/nemotron-3.5-lightning-30b-a3b")
    calls = []

    async def handler(request):
        model = json.loads(request.content)["model"]
        calls.append(model)
        if model != model_ids[-1]:
            await asyncio.Event().wait()
        return completion()

    async with engine(
        handler, model_ids=model_ids, timeout_s=0.4, attempt_timeout_s=0.2
    ) as adapter:
        assert (
            await adapter.clean(CleanupRequest("hello world again"))
            == "hello world again"
        )
    assert calls == list(model_ids)


@pytest.mark.asyncio
async def test_cooled_models_do_not_reduce_the_remaining_attempt_budget() -> None:
    calls = []
    seeded_cooldown = False

    async def handler(request):
        model = json.loads(request.content)["model"]
        calls.append(model)
        if not seeded_cooldown and model == MODELS[0]:
            return httpx.Response(429)
        if seeded_cooldown:
            await asyncio.sleep(0.2)
        return completion()

    async with engine(
        handler, model_ids=MODELS[:2], timeout_s=0.3, attempt_timeout_s=0.3
    ) as adapter:
        await adapter.clean(CleanupRequest("hello world again"))
        seeded_cooldown = True
        assert (
            await adapter.clean(CleanupRequest("hello world again"))
            == "hello world again"
        )
    assert calls == [MODELS[0], MODELS[1], MODELS[1]]


@pytest.mark.asyncio
async def test_total_budget_stops_chain_before_attempt_budget_finishes() -> None:
    calls = []

    async def handler(request):
        calls.append(request)
        await asyncio.Event().wait()

    async with engine(
        handler, model_ids=(MODELS[0],), timeout_s=0.01, attempt_timeout_s=1.0
    ) as adapter:
        with pytest.raises(ThirdPartyError) as caught:
            await adapter.clean(CleanupRequest("hello world again"))
        assert caught.value.error_code == ErrorCode.CLEANUP_TIMEOUT
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_task_cancellation_propagates_without_fallback() -> None:
    entered = asyncio.Event()
    calls = []

    async def handler(request):
        calls.append(request)
        entered.set()
        await asyncio.Event().wait()

    async with engine(handler) as adapter:
        task = asyncio.create_task(adapter.clean(CleanupRequest("hello world again")))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_run_cancel_callback_stops_fallback_requests() -> None:
    cancelled = [False]
    calls = []

    def handler(request):
        calls.append(request)
        cancelled[0] = True
        return httpx.Response(429)

    async with engine(handler) as adapter:
        with pytest.raises(ThirdPartyError) as caught:
            await adapter.clean(
                CleanupRequest("hello world again", cancelled=lambda: cancelled[0])
            )
        assert caught.value.error_code == ErrorCode.CLEANUP_UNAVAILABLE
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_key_clear_takes_effect_before_next_fallback_request() -> None:
    key = [KEY]
    calls = []

    def handler(request):
        calls.append(request)
        key[0] = None
        return httpx.Response(429)

    async with engine(handler, api_key=lambda: key[0]) as adapter:
        with pytest.raises(ThirdPartyError) as caught:
            await adapter.clean(CleanupRequest("hello world again"))
        assert caught.value.error_code == ErrorCode.NVIDIA_API_KEY_MISSING
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_health_missing_key_discovery_and_close_never_send_chat() -> None:
    key = [None]
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": MODELS[0]},
                    {"id": "vendor/custom-model"},
                    {"id": MODELS[0]},
                    {"id": "bad id"},
                    {"id": 123},
                    None,
                ]
            },
        )

    async with engine(handler, api_key=lambda: key[0]) as adapter:
        assert await adapter.health() is False
        for operation in (
            adapter.list_models,
            lambda: adapter.clean(CleanupRequest("private")),
        ):
            with pytest.raises(ThirdPartyError) as caught:
                await operation()
            assert caught.value.error_code == ErrorCode.NVIDIA_API_KEY_MISSING
        assert calls == []
        key[0] = KEY
        assert await adapter.health() is True
        assert calls == []
        models = await adapter.list_models()
        assert [item["model_id"] for item in models] == [
            MODELS[0],
            "vendor/custom-model",
        ]
        assert calls[0].method == "GET" and calls[0].url.path == "/v1/models"
        assert calls[0].headers["Authorization"] == "Bearer " + KEY
        await adapter.aclose()
        await adapter.aclose()
        assert await adapter.health() is False
        with pytest.raises(ThirdPartyError):
            await adapter.clean(CleanupRequest("private"))
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_http_errors_do_not_expose_keys_transcript_or_response_details() -> None:
    private = "PRIVATE_TRANSCRIPT_SENTINEL"

    def handler(request):
        raise httpx.ConnectError(KEY + private, request=request)

    async with engine(handler, model_ids=(MODELS[0],)) as adapter:
        with pytest.raises(ThirdPartyError) as caught:
            await adapter.clean(CleanupRequest(private))
        rendered = "".join(traceback.format_exception(caught.value))
        assert KEY not in rendered and private not in rendered
        assert KEY not in caught.value.detail and private not in caught.value.detail


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://integrate.api.nvidia.com/v1",
        "https://untrusted.invalid/v1",
        "https://integrate.api.nvidia.com.evil.invalid/v1",
        "https://key@integrate.api.nvidia.com/v1",
        "https://integrate.api.nvidia.com:bad/v1",
        "https://integrate.api.nvidia.com/v1?redirect=evil",
        "https://integrate.api.nvidia.com/v1#part",
    ],
)
def test_endpoint_cannot_redirect_credentials_to_another_host(endpoint) -> None:
    with pytest.raises(WisprError) as caught:
        NvidiaCleanup(api_key=lambda: KEY, base_url=endpoint)
    assert caught.value.error_code == ErrorCode.VALIDATION
