"""Security regressions for the cloud STT exception boundary."""

import array
import logging

import httpx
import pytest

from wispr_clone.contracts.common import ThirdPartyError
from wispr_clone.stt.openrouter_whisper import OpenRouterWhisper

FAKE_KEY = "sk-or-v1-test-exception-context"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_T_STT_025_transport_error_does_not_retain_key_in_exception_graph(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    engine = OpenRouterWhisper(
        api_key=lambda: FAKE_KEY, transport=httpx.MockTransport(fail)
    )
    session = engine.start_session()
    session.push_audio(array.array("f", [0.25]))
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ThirdPartyError) as caught:
            await session.finish()

    error = caught.value
    assert FAKE_KEY not in caplog.text
    assert FAKE_KEY not in str(error)
    assert FAKE_KEY not in repr(error)
    assert FAKE_KEY not in repr(error.args)
    assert FAKE_KEY not in repr(error.__cause__)
    assert FAKE_KEY not in repr(error.__context__)
    assert FAKE_KEY not in repr(vars(error))
    # Python's ``raise ... from None`` suppresses display, but can still retain
    # an httpx RequestError whose request holds the Authorization header.
    assert error.__context__ is None
    await engine.close()
