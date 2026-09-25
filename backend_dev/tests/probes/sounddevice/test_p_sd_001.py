"""P-SD-001 queries PortAudio devices but never opens an input stream."""

import importlib
from importlib.metadata import version

import pytest


@pytest.mark.probe("sounddevice")
def test_P_SD_001_import_and_query_available_input_devices():
    try:
        sd = importlib.import_module("sounddevice")
    except (ImportError, OSError) as exc:
        pytest.skip(
            f"sounddevice or PortAudio unavailable: {type(exc).__name__}: {exc}"
        )
    assert version("sounddevice") == "0.5.6"
    try:
        devices = sd.query_devices()
    except (OSError, RuntimeError) as exc:
        pytest.skip(f"PortAudio device query unavailable: {type(exc).__name__}: {exc}")
    assert isinstance(devices, list)
    if not any(device["max_input_channels"] > 0 for device in devices):
        pytest.skip("No PortAudio input device is available; real mic is tier H")
