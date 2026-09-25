"""Read-only model state and synthetic LM Studio chat probes."""

import http.client
import json
import sys
import time
import urllib.error
import urllib.request

import pytest

pytestmark = [
    pytest.mark.gpu,
    pytest.mark.probe("lmstudio"),
    pytest.mark.skipif(sys.platform != "win32", reason="Windows LM Studio probe only"),
]

HOST = "127.0.0.1"
PORT = 1234
MODEL = "meta-llama-3.1-8b-instruct"


def _models():
    try:
        with urllib.request.urlopen(
            f"http://{HOST}:{PORT}/api/v0/models", timeout=3
        ) as response:
            return json.load(response).get("data", [])
    except (OSError, urllib.error.URLError) as exc:
        pytest.skip(f"LM Studio not running on loopback: {type(exc).__name__}")


def _loaded_model():
    model = next((item for item in _models() if item.get("id") == MODEL), None)
    if model is None or model.get("state") != "loaded":
        pytest.skip("model not loaded; not loading it")
    return model


def _chat(prompt, *, stream=False, max_tokens=40):
    body = json.dumps(
        {
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": max_tokens,
            "stream": stream,
        }
    ).encode()
    request = urllib.request.Request(
        f"http://{HOST}:{PORT}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)["choices"][0]["message"]["content"]


def test_P_LMS_001_pinned_model_is_loaded(record_property):
    model = _loaded_model()
    record_property("model_id", MODEL)
    record_property("model_state", model["state"])
    record_property("quantization", model.get("quantization"))
    record_property("loaded_context_length", model.get("loaded_context_length"))


def test_P_LMS_002_temperature_zero_is_repeatable(record_property):
    _loaded_model()
    prompt = "Reply with exactly one word: cobalt."
    started = time.perf_counter()
    first = _chat(prompt)
    first_s = time.perf_counter() - started
    started = time.perf_counter()
    second = _chat(prompt)
    second_s = time.perf_counter() - started
    assert isinstance(first, str) and first.strip()
    assert first == second
    record_property("model_id", MODEL)
    record_property("first_chat_s", round(first_s, 3))
    record_property("second_chat_s", round(second_s, 3))


def test_P_LMS_003_stream_disconnect_and_followup(record_property):
    _loaded_model()
    body = json.dumps(
        {
            "model": MODEL,
            "messages": [
                {"role": "user", "content": "Count from 1 to 600, one number per line."}
            ],
            "temperature": 0,
            "max_tokens": 1500,
            "stream": True,
        }
    )
    connection = http.client.HTTPConnection(HOST, PORT, timeout=60)
    started = time.perf_counter()
    try:
        connection.request(
            "POST",
            "/v1/chat/completions",
            body,
            {"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        assert response.status == 200
        while True:
            line = response.readline()
            assert line, "stream ended before its first event"
            if line.startswith(b"data:"):
                break
        first_event_s = time.perf_counter() - started
    finally:
        if connection.sock is not None:
            connection.sock.close()
        connection.close()
    started = time.perf_counter()
    followup = _chat("Reply with one word: ready.")
    followup_s = time.perf_counter() - started
    assert isinstance(followup, str) and followup.strip()
    record_property("model_id", MODEL)
    record_property("first_stream_event_s", round(first_event_s, 3))
    record_property("followup_after_disconnect_s", round(followup_s, 3))
