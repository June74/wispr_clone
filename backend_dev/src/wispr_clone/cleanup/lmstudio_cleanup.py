"""LM Studio adapter using its loaded-model API and OpenAI-compatible chat API."""

import ipaddress
from urllib.parse import urlsplit

import httpx

from wispr_clone import config
from wispr_clone.cleanup.base import CleanupRequest
from wispr_clone.cleanup.prompt_builder import build_messages
from wispr_clone.contracts.common import ErrorCode, ThirdPartyError, WisprError


def _is_loopback_endpoint(url: str) -> bool:
    """Accept only valid HTTP(S) URLs with loopback IP literal hosts."""
    try:
        if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
            return False
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            return False
        if "@" in parsed.netloc:
            return False
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            return False
        host = parsed.hostname
        return host is not None and ipaddress.ip_address(host).is_loopback
    except (ValueError, TypeError):
        return False


class LmStudioCleanup:
    """Cleanup engine whose readiness check prevents LM Studio auto-loading."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:1234",
        model_id: str = config.LM_STUDIO_MODEL_ID,
        timeout_s: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not _is_loopback_endpoint(base_url):
            raise WisprError(ErrorCode.NON_LOOPBACK_ENDPOINT, "cleanup", "endpoint")
        self._base_url = base_url.rstrip("/")
        self._model_id = model_id
        self._timeout = httpx.Timeout(timeout_s)
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                transport=self._transport,
            )
        return self._client

    async def _models_loaded(self) -> bool:
        client = self._get_client()
        try:
            response = await client.get("/api/v0/models")
        except httpx.TimeoutException:
            raise ThirdPartyError(
                "lmstudio", "models", "timeout", ErrorCode.CLEANUP_TIMEOUT
            ) from None
        except httpx.RequestError:
            raise ThirdPartyError(
                "lmstudio", "models", "connect", ErrorCode.CLEANUP_UNAVAILABLE
            ) from None
        if response.status_code >= 400:
            raise ThirdPartyError(
                "lmstudio",
                "models",
                f"http {response.status_code}",
                ErrorCode.CLEANUP_UNAVAILABLE,
            )
        try:
            payload = response.json()
            data = payload["data"]
            return any(
                isinstance(model, dict)
                and model.get("id") == self._model_id
                and model.get("state") == "loaded"
                for model in data
            )
        except (ValueError, TypeError, KeyError):
            raise ThirdPartyError(
                "lmstudio", "models", "bad response", ErrorCode.CLEANUP_UNAVAILABLE
            ) from None

    async def clean(self, request: CleanupRequest) -> str:
        """Check readiness before sending one non-streaming cleanup request."""
        if not await self._models_loaded():
            raise ThirdPartyError(
                "lmstudio", "models", "not loaded", ErrorCode.CLEANUP_UNAVAILABLE
            )
        client = self._get_client()
        try:
            response = await client.post(
                "/v1/chat/completions",
                json={
                    "model": self._model_id,
                    "messages": build_messages(request),
                    "temperature": 0,
                    "stream": False,
                },
            )
        except httpx.TimeoutException:
            raise ThirdPartyError(
                "lmstudio", "chat", "timeout", ErrorCode.CLEANUP_TIMEOUT
            ) from None
        except httpx.RequestError:
            raise ThirdPartyError(
                "lmstudio", "chat", "connect", ErrorCode.CLEANUP_UNAVAILABLE
            ) from None
        if response.status_code >= 400:
            raise ThirdPartyError(
                "lmstudio",
                "chat",
                f"http {response.status_code}",
                ErrorCode.CLEANUP_UNAVAILABLE,
            )
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError
        except (ValueError, TypeError, KeyError, IndexError):
            raise ThirdPartyError(
                "lmstudio", "chat", "bad response", ErrorCode.CLEANUP_UNAVAILABLE
            ) from None
        return content.strip()

    async def health(self) -> bool:
        """Return readiness without sending a chat request."""
        try:
            return await self._models_loaded()
        except Exception:
            return False

    async def aclose(self) -> None:
        """Close the lazily created HTTP client, if any."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
