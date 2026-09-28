"""OpenRouter's speech-to-text model list, read from its public models API."""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from wispr_clone import config
from wispr_clone.contracts.common import ErrorCode, ThirdPartyError

CACHE_S = 600.0


class OpenRouterCatalog:
    """List transcription models; cached so opening the page stays fast."""

    def __init__(
        self,
        *,
        base_url: str = config.OPENROUTER_ENDPOINT,
        timeout_s: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url.startswith("https://"):
            raise ThirdPartyError(
                "openrouter", "models", "endpoint", ErrorCode.VALIDATION
            )
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._clock = clock
        self._transport = transport
        self._cached: tuple[float, list[dict[str, object]]] | None = None

    async def list_models(self) -> list[dict[str, object]]:
        now = self._clock()
        if self._cached is not None and now - self._cached[0] < CACHE_S:
            return self._cached[1]
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_s, transport=self._transport
            ) as client:
                response = await client.get(
                    f"{self._base_url}/models",
                    params={"output_modalities": "transcription"},
                )
        except httpx.TimeoutException:
            raise ThirdPartyError(
                "openrouter", "models", "timeout", ErrorCode.STT_TIMEOUT
            ) from None
        except httpx.RequestError:
            raise ThirdPartyError(
                "openrouter", "models", "connect", ErrorCode.STT_UNAVAILABLE
            ) from None
        try:
            if response.status_code != 200:
                raise ValueError
            data = response.json()["data"]
            if not isinstance(data, list):
                raise ValueError
        except (ValueError, TypeError, KeyError):
            raise ThirdPartyError(
                "openrouter", "models", "bad response", ErrorCode.STT_UNAVAILABLE
            ) from None
        models: list[dict[str, object]] = []
        for item in data:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                continue
            name = item.get("name")
            models.append(
                {
                    "model_id": item["id"],
                    "display_name": name if isinstance(name, str) else item["id"],
                }
            )
        self._cached = (now, models)
        return models
