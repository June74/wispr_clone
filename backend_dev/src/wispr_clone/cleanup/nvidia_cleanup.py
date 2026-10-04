"""NVIDIA hosted cleanup with an ordered, bounded fallback chain.

Readiness means a key is configured, not that credits or access are verified.
Explicit model discovery uses the non-generating models endpoint; recurring
health checks never transmit dictated text or spend generation credits.
"""

from __future__ import annotations

import asyncio
import math
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from wispr_clone import config
from wispr_clone.cleanup.base import CleanupRequest
from wispr_clone.cleanup.prompt_builder import build_messages
from wispr_clone.contracts.common import ErrorCode, ThirdPartyError, WisprError

_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._:-]*")
_LOW_REASONING_MODELS = frozenset(
    {"z-ai/glm-5.3", "z-ai/glm-5.3-flash", "moonshotai/kimi-k3"}
)


class NvidiaCleanup:
    """Try each selected model at most once per dictation, in preference order."""

    def __init__(
        self,
        *,
        api_key: Callable[[], str | None],
        model_ids: tuple[str, ...] = config.NVIDIA_CLEANUP_MODEL_IDS,
        base_url: str = config.NVIDIA_ENDPOINT,
        timeout_s: float = 25.0,
        attempt_timeout_s: float = 10.0,
        cooldown_s: float = 60.0,
        max_cooldown_s: float = 300.0,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        try:
            parsed = urlsplit(base_url)
            endpoint_valid = (
                parsed.scheme == "https"
                and parsed.hostname == "integrate.api.nvidia.com"
                and parsed.username is None
                and parsed.password is None
                and parsed.port in (None, 443)
                and parsed.path.rstrip("/") == "/v1"
                and not parsed.query
                and not parsed.fragment
                and not any(
                    character.isspace() or ord(character) < 32 or ord(character) == 127
                    for character in base_url
                )
            )
        except (ValueError, TypeError):
            endpoint_valid = False
        if not endpoint_valid:
            raise WisprError(ErrorCode.VALIDATION, "cleanup.nvidia", "endpoint")
        if (
            not isinstance(model_ids, tuple)
            or not 1 <= len(model_ids) <= 12
            or any(
                not isinstance(model_id, str)
                or len(model_id) > 200
                or ".." in model_id
                or _MODEL_ID.fullmatch(model_id) is None
                for model_id in model_ids
            )
            or len(set(model_ids)) != len(model_ids)
        ):
            raise WisprError(ErrorCode.VALIDATION, "cleanup.nvidia", "model_ids")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
            for value in (timeout_s, attempt_timeout_s, cooldown_s, max_cooldown_s)
        ):
            raise WisprError(ErrorCode.VALIDATION, "cleanup.nvidia", "timeout")
        self._api_key = api_key
        self._model_ids = model_ids
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._attempt_timeout_s = attempt_timeout_s
        self._cooldown_s = cooldown_s
        self._max_cooldown_s = max_cooldown_s
        self._transport = transport
        self._clock = clock
        self._cooldown_until: dict[str, float] = {}
        self._client: httpx.AsyncClient | None = None
        self._closed = False

    @property
    def model_ids(self) -> tuple[str, ...]:
        return self._model_ids

    @property
    def ready(self) -> bool:
        return not self._closed and bool(self._api_key())

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._attempt_timeout_s,
                transport=self._transport,
                follow_redirects=False,
                trust_env=False,
            )
        return self._client

    def _headers(self) -> dict[str, str]:
        if self._closed:
            raise ThirdPartyError(
                "nvidia", "client", "closed", ErrorCode.CLEANUP_UNAVAILABLE
            )
        key = self._api_key()
        if not key:
            raise ThirdPartyError(
                "nvidia", "credentials", "missing key", ErrorCode.NVIDIA_API_KEY_MISSING
            )
        return {"Authorization": f"Bearer {key}"}

    @staticmethod
    def _check_auth(response: httpx.Response) -> None:
        if response.status_code in (401, 403):
            raise ThirdPartyError(
                "nvidia",
                "credentials",
                "key rejected",
                ErrorCode.NVIDIA_API_KEY_INVALID,
            )

    @staticmethod
    def _check_cancelled(request: CleanupRequest) -> None:
        if request.cancelled is not None and request.cancelled():
            # The controller sees its flag and persists the cancelled state.
            raise ThirdPartyError(
                "nvidia", "chat", "cancelled", ErrorCode.CLEANUP_UNAVAILABLE
            )

    def _cool_down(self, model_id: str, response: httpx.Response | None) -> None:
        delay = self._cooldown_s
        retry_after = response.headers.get("Retry-After") if response else None
        if retry_after:
            try:
                parsed_delay = float(retry_after)
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=timezone.utc)
                    parsed_delay = (
                        retry_at - datetime.now(timezone.utc)
                    ).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    parsed_delay = delay
            if math.isfinite(parsed_delay):
                delay = max(1.0, parsed_delay)
        self._cooldown_until[model_id] = self._clock() + min(
            delay, self._max_cooldown_s
        )

    async def _poll_pending(
        self, response: httpx.Response, request: CleanupRequest
    ) -> httpx.Response:
        """Poll an invocation on the fixed host inside the existing attempt budget."""
        self._check_cancelled(request)
        raw_id = response.headers.get("NVCF-REQID", "")
        try:
            request_id = str(UUID(raw_id))
            if len(raw_id) != 36 or request_id != raw_id.lower():
                raise ValueError
        except ValueError:
            raise ThirdPartyError(
                "nvidia", "chat", "bad pending response", ErrorCode.CLEANUP_UNAVAILABLE
            ) from None
        while response.status_code == 202:
            self._check_cancelled(request)
            await asyncio.sleep(1.0)
            self._check_cancelled(request)
            response = await self._http().get(
                f"status/{request_id}", headers=self._headers()
            )
        return response

    async def clean(self, request: CleanupRequest) -> str:
        self._check_cancelled(request)
        self._headers()
        last_code = ErrorCode.CLEANUP_UNAVAILABLE
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._timeout_s
        try:
            async with asyncio.timeout_at(deadline):
                for index, model_id in enumerate(self._model_ids):
                    self._check_cancelled(request)
                    now = self._clock()
                    if now < self._cooldown_until.get(model_id, 0.0):
                        continue
                    # Reserve a share for every remaining eligible model so
                    # slow early attempts cannot starve the end of the chain.
                    eligible_count = sum(
                        now >= self._cooldown_until.get(candidate, 0.0)
                        for candidate in self._model_ids[index:]
                    )
                    remaining_s = deadline - loop.time()
                    if remaining_s <= 0:
                        raise TimeoutError
                    attempt_s = min(
                        self._attempt_timeout_s, remaining_s / eligible_count
                    )
                    body: dict[str, object] = {
                        "model": model_id,
                        "messages": build_messages(request),
                        "temperature": 0,
                        "stream": False,
                        "max_tokens": 4096,
                    }
                    if model_id in _LOW_REASONING_MODELS:
                        body["reasoning_effort"] = "low"
                    if model_id == "nvidia/nemotron-3.5-lightning-30b-a3b":
                        # NVIDIA's voice-agent example disables thinking to
                        # minimize latency for this hosted model.
                        body["chat_template_kwargs"] = {"enable_thinking": False}
                    try:
                        async with asyncio.timeout(attempt_s):
                            response = await self._http().post(
                                "chat/completions", headers=self._headers(), json=body
                            )
                            if response.status_code == 202:
                                response = await self._poll_pending(response, request)
                    except (httpx.TimeoutException, TimeoutError):
                        self._cool_down(model_id, None)
                        last_code = ErrorCode.CLEANUP_TIMEOUT
                        continue
                    except httpx.RequestError:
                        self._cool_down(model_id, None)
                        last_code = ErrorCode.CLEANUP_UNAVAILABLE
                        continue
                    self._check_cancelled(request)
                    self._check_auth(response)
                    # Credit exhaustion is account-wide; another model cannot help.
                    if response.status_code == 402:
                        raise ThirdPartyError(
                            "nvidia",
                            "chat",
                            "credits exhausted",
                            ErrorCode.CLEANUP_UNAVAILABLE,
                        )
                    if response.status_code in (404, 408, 409, 425, 429) or (
                        500 <= response.status_code <= 599
                    ):
                        self._cool_down(model_id, response)
                        last_code = ErrorCode.CLEANUP_UNAVAILABLE
                        continue
                    if response.status_code != 200:
                        raise ThirdPartyError(
                            "nvidia",
                            "chat",
                            "request rejected",
                            ErrorCode.CLEANUP_UNAVAILABLE,
                        )
                    try:
                        payload = response.json()
                        choice = payload["choices"][0]
                        message = choice["message"]
                        content = message["content"]
                        if (
                            not isinstance(content, str)
                            or not content.strip()
                            or choice.get("finish_reason") not in (None, "stop")
                            or message.get("tool_calls")
                            or message.get("refusal")
                        ):
                            raise ValueError
                    except (ValueError, UnicodeError, TypeError, KeyError, IndexError):
                        self._cool_down(model_id, None)
                        last_code = ErrorCode.CLEANUP_UNAVAILABLE
                        continue
                    self._cooldown_until.pop(model_id, None)
                    return content.strip()
        except TimeoutError:
            raise ThirdPartyError(
                "nvidia", "chat", "timeout", ErrorCode.CLEANUP_TIMEOUT
            ) from None
        self._check_cancelled(request)
        raise ThirdPartyError("nvidia", "chat", "chain exhausted", last_code)

    async def health(self) -> bool:
        """Local configuration check; it never generates or transmits text."""
        return self.ready

    async def list_models(self) -> list[dict[str, object]]:
        """Discover models without generating text or testing free eligibility."""
        headers = self._headers()
        try:
            async with asyncio.timeout(min(self._timeout_s, self._attempt_timeout_s)):
                response = await self._http().get("models", headers=headers)
        except (httpx.TimeoutException, TimeoutError):
            raise ThirdPartyError(
                "nvidia", "models", "timeout", ErrorCode.CLEANUP_TIMEOUT
            ) from None
        except httpx.RequestError:
            raise ThirdPartyError(
                "nvidia", "models", "request failed", ErrorCode.CLEANUP_UNAVAILABLE
            ) from None
        self._check_auth(response)
        if response.status_code != 200:
            raise ThirdPartyError(
                "nvidia", "models", "request rejected", ErrorCode.CLEANUP_UNAVAILABLE
            )
        try:
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(
                payload.get("data"), list
            ):
                raise ValueError
            discovered: list[dict[str, object]] = []
            seen: set[str] = set()
            for item in payload["data"]:
                model_id = item.get("id") if isinstance(item, dict) else None
                if (
                    isinstance(model_id, str)
                    and len(model_id) <= 200
                    and ".." not in model_id
                    and _MODEL_ID.fullmatch(model_id) is not None
                    and model_id not in seen
                ):
                    seen.add(model_id)
                    discovered.append({"model_id": model_id, "display_name": model_id})
            return discovered
        except (ValueError, UnicodeError, TypeError):
            raise ThirdPartyError(
                "nvidia", "models", "bad response", ErrorCode.CLEANUP_UNAVAILABLE
            ) from None

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._client is not None:
            await self._client.aclose()
