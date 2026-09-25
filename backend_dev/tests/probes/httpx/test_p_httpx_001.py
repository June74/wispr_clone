"""P-HTTPX-001: isolated httpx 0.28.1 timeout and cancellation contract."""

import asyncio

import httpx
import pytest


@pytest.mark.probe("httpx")
@pytest.mark.asyncio
async def test_P_HTTPX_001_timeout_and_cancel_propagate():
    assert httpx.__version__ == "0.28.1"
    calls = []

    def timeout_handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(timeout_handler)
    ) as client:
        with pytest.raises(httpx.TimeoutException):
            await client.get("http://127.0.0.1:1234/synthetic")
    assert len(calls) == 1

    entered = asyncio.Event()
    release = asyncio.Event()
    cancelled = asyncio.Event()
    calls.clear()

    async def blocked_handler(request):
        calls.append(request)
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return httpx.Response(200)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(blocked_handler)
    ) as client:
        task = asyncio.create_task(client.get("http://127.0.0.1:1234/synthetic"))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert cancelled.is_set()
            assert len(calls) == 1
        finally:
            release.set()
