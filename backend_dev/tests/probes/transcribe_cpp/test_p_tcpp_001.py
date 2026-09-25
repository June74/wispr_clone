"""Isolated transcribe_cpp 0.2.3 import/API probe; no model required."""

import importlib

import pytest


@pytest.mark.probe("transcribe-cpp")
@pytest.mark.windows
def test_P_TCPP_001_installed_api_and_cpu_backend():
    try:
        native = importlib.import_module("transcribe_cpp")
    except ImportError as exc:
        pytest.skip(f"transcribe_cpp is not importable: {type(exc).__name__}")
    assert native.__version__ == "0.2.3"
    assert any(device.name == "CPU" for device in native.backends())
    for name in (
        "Model",
        "Session",
        "Stream",
        "StreamText",
        "Aborted",
        "TranscribeError",
        "ModelLoadError",
        "ModelFileNotFound",
        "OutOfMemory",
    ):
        assert hasattr(native, name), name
    assert issubclass(native.Aborted, native.TranscribeError)
    for cls, required in (
        (native.Model, ("session", "close")),
        (native.Session, ("run", "stream", "cancel", "close", "__enter__", "__exit__")),
        (native.Stream, ("feed", "finalize", "text", "__enter__", "__exit__")),
    ):
        for name in required:
            assert hasattr(cls, name), f"{cls.__name__}.{name}"
