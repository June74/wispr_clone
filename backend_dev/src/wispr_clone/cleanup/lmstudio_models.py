"""LM Studio model management: list downloaded chat models and load one.

Uses LM Studio's native v1 REST API (LM Studio 0.4+). A model loaded through
``/api/v1/models/load`` has no idle TTL and is not auto-evicted by just-in-time
loads, unlike a model loaded on demand by a chat request, so cleanup stays
available. Chat requests are still only sent once the model reports loaded.
"""

from __future__ import annotations

import asyncio

import httpx

from wispr_clone import config
from wispr_clone.cleanup.lmstudio_cleanup import _is_loopback_endpoint
from wispr_clone.contracts.common import ErrorCode, ThirdPartyError

# LM Studio reports some speech models as type "llm"; they cannot clean text.
_SPEECH_ARCHITECTURES = ("voxtral", "whisper")


class LmStudioModels:
    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:1234",
        timeout_s: float = 5.0,
        load_timeout_s: float = 180.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not _is_loopback_endpoint(base_url):
            raise ThirdPartyError(
                "lmstudio", "models", "endpoint", ErrorCode.NON_LOOPBACK_ENDPOINT
            )
        self._base_url = base_url.rstrip("/").removesuffix("/v1")
        self._timeout_s = timeout_s
        self._load_timeout_s = load_timeout_s
        self._transport = transport
        self._load_lock = asyncio.Lock()

    def _client(self, timeout_s: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout_s,
            transport=self._transport,
            trust_env=False,
        )

    async def _models(self) -> list[dict[str, object]]:
        try:
            async with self._client(self._timeout_s) as client:
                response = await client.get("/api/v1/models")
        except httpx.TimeoutException:
            raise ThirdPartyError(
                "lmstudio", "models", "timeout", ErrorCode.CLEANUP_TIMEOUT
            ) from None
        except httpx.RequestError:
            raise ThirdPartyError(
                "lmstudio", "models", "connect", ErrorCode.CLEANUP_UNAVAILABLE
            ) from None
        try:
            if response.status_code >= 400:
                raise ValueError
            models = response.json()["models"]
            if not isinstance(models, list):
                raise ValueError
        except (ValueError, TypeError, KeyError):
            raise ThirdPartyError(
                "lmstudio", "models", "bad response", ErrorCode.CLEANUP_UNAVAILABLE
            ) from None
        return [model for model in models if isinstance(model, dict)]

    async def list_chat_models(self) -> list[dict[str, object]]:
        """Downloaded models that can clean text, with their load state."""
        listed = []
        for model in await self._models():
            key = model.get("key")
            architecture = str(model.get("architecture") or "").lower()
            if (
                model.get("type") != "llm"
                or not isinstance(key, str)
                or any(name in architecture for name in _SPEECH_ARCHITECTURES)
            ):
                continue
            name = model.get("display_name")
            listed.append(
                {
                    "model_id": key,
                    "display_name": name if isinstance(name, str) else key,
                    "loaded": bool(model.get("loaded_instances")),
                    "size_bytes": model.get("size_bytes"),
                }
            )
        return listed

    async def is_loaded(self, model_id: str) -> bool:
        return any(
            model.get("key") == model_id and bool(model.get("loaded_instances"))
            for model in await self._models()
        )

    async def ensure_loaded(self, model_id: str) -> bool:
        """Load ``model_id`` unless it already is; return whether it loaded now.

        One load at a time: a second caller waits and then sees it loaded.
        """
        async with self._load_lock:
            if await self.is_loaded(model_id):
                return False
            try:
                async with self._client(self._load_timeout_s) as client:
                    response = await client.post(
                        "/api/v1/models/load", json={"model": model_id}
                    )
            except httpx.TimeoutException:
                raise ThirdPartyError(
                    "lmstudio", "load", "timeout", ErrorCode.MODEL_LOAD_FAILED
                ) from None
            except httpx.RequestError:
                raise ThirdPartyError(
                    "lmstudio", "load", "connect", ErrorCode.CLEANUP_UNAVAILABLE
                ) from None
            if response.status_code >= 400:
                raise ThirdPartyError(
                    "lmstudio",
                    "load",
                    f"http {response.status_code}",
                    ErrorCode.MODEL_LOAD_FAILED,
                )
            return True


def default_models() -> LmStudioModels:
    return LmStudioModels(base_url=config.LM_STUDIO_ENDPOINT)
