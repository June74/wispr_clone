"""Opt-in live endpoint check; never used by the default offline suite."""

import base64
import io
import math
import os
import struct
import sys
import wave

import httpx
import pytest

from wispr_clone.config import app_data_dir

pytestmark = [pytest.mark.probe("httpx"), pytest.mark.manual]


def _key() -> str | None:
    if sys.platform == "win32":
        from wispr_clone.settings.secret_store import DpapiSecretStore

        saved = DpapiSecretStore(app_data_dir() / "secrets").get("openrouter_api_key")
        if saved:
            return saved
    return os.environ.get("OPENROUTER_API_KEY")


def _tone() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setparams((1, 2, 16_000, 0, "NONE", "not compressed"))
        writer.writeframes(
            b"".join(
                struct.pack("<h", int(4000 * math.sin(2 * math.pi * 440 * n / 16_000)))
                for n in range(32_000)
            )
        )
    return output.getvalue()


@pytest.mark.asyncio
async def test_P_OPENROUTER_001_deepinfra_transcription(record_property) -> None:
    if os.environ.get("WISPR_NETWORK_PROBES") != "1":
        pytest.skip("network probes require WISPR_NETWORK_PROBES=1")
    key = _key()
    if not key:
        pytest.skip("OpenRouter key unavailable")
    body = {
        "model": "openai/whisper-large-v3-turbo",
        "input_audio": {"data": base64.b64encode(_tone()).decode(), "format": "wav"},
        "provider": {"only": ["deepinfra"], "allow_fallbacks": False},
    }
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {key}"},
            json=body,
        )
    assert response.status_code == 200, f"HTTP {response.status_code}"
    parsed = response.json()
    assert isinstance(parsed.get("text"), str)
    usage = parsed.get("usage")
    assert isinstance(usage, dict)
    assert isinstance(usage.get("cost"), (int, float))
    record_property("usage_cost_usd", usage["cost"])
    provider = parsed.get("provider") or response.headers.get("x-openrouter-provider")
    if provider is not None:
        assert "deepinfra" in str(provider).lower()
