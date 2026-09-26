"""Direct CUDA model loading, streaming and cancellation probes."""

import array
import importlib
import math
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.gpu,
    pytest.mark.probe("transcribe-cpp"),
    pytest.mark.skipif(sys.platform != "win32", reason="Windows CUDA model probe only"),
]

GGUF = Path(
    r"C:\Users\2006i\.lmstudio\models\handy-computer\Voxtral-Mini-4B-Realtime-2602-gguf\Voxtral-Mini-4B-Realtime-2602-Q4_K_M.gguf"
)


def _prerequisites():
    try:
        native = importlib.import_module("transcribe_cpp")
    except ImportError as exc:
        pytest.skip(f"transcribe_cpp missing: {type(exc).__name__}")
    if not GGUF.is_file():
        pytest.skip(f"GGUF missing: {GGUF}")
    device = next((item for item in native.backends() if item.name == "CUDA0"), None)
    if device is None:
        pytest.skip("CUDA0 backend missing")
    return native, device


def _free_vram_mib():
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return int(result.stdout.strip().splitlines()[0].strip())


def test_P_TCPP_002_load_warm_and_streaming_capability(record_property):
    native, device = _prerequisites()
    before = _free_vram_mib()
    record_property("free_vram_before_mib", before)
    started = time.perf_counter()
    with native.Model(GGUF, device=device) as model:
        load_s = time.perf_counter() - started
        after_load = _free_vram_mib()
        started = time.perf_counter()
        with model.session() as session:
            session.run(array.array("f", [0.0]) * 16_000)
        warm_s = time.perf_counter() - started
        assert model.capabilities.supports_streaming is True
        record_property("model_backend", str(model.backend))
    after_close = _free_vram_mib()
    record_property("transcribe_cpp_version", native.__version__)
    record_property("load_s", round(load_s, 3))
    record_property("warmup_s", round(warm_s, 3))
    record_property("free_vram_after_load_mib", after_load)
    record_property("vram_delta_mib", before - after_load)
    record_property("free_vram_after_close_mib", after_close)


def test_P_TCPP_003_live_pace_feed_finalize_and_cancel(record_property):
    native, device = _prerequisites()
    before = _free_vram_mib()
    record_property("free_vram_before_mib", before)
    max_feed_s = 0.0
    result = {}
    with native.Model(GGUF, device=device) as model:
        with model.session() as warm:
            warm.run(array.array("f", [0.0]) * 16_000)
        with model.session() as session:
            started = time.perf_counter()
            with session.stream() as stream:
                for index in range(63):  # approximately five seconds at 80 ms per chunk
                    due = started + index * 0.08
                    remaining = due - time.perf_counter()
                    if remaining > 0:
                        time.sleep(remaining)
                    if index < 31:
                        chunk = array.array("f", [0.0]) * 1_280
                    else:
                        chunk = array.array(
                            "f",
                            (
                                0.05 * math.sin(2 * math.pi * 440 * sample / 16_000)
                                for sample in range(index * 1_280, (index + 1) * 1_280)
                            ),
                        )
                    t0 = time.perf_counter()
                    stream.feed(chunk)
                    max_feed_s = max(max_feed_s, time.perf_counter() - t0)
                t0 = time.perf_counter()
                stream.finalize()
                finalize_s = time.perf_counter() - t0
        assert max_feed_s < 0.5

        def run_long():
            try:
                with model.session() as session:
                    result["session"] = session
                    result["started"].set()
                    session.run(array.array("f", [0.0]) * (16_000 * 120))
                    result["outcome"] = "completed"
            except BaseException as exc:
                result["outcome"] = exc

        result["started"] = threading.Event()
        worker = threading.Thread(target=run_long, daemon=True)
        worker.start()
        assert result["started"].wait(timeout=10)
        time.sleep(0.3)
        cancel_start = time.perf_counter()
        result["session"].cancel()
        worker.join(timeout=2)
        cancel_s = time.perf_counter() - cancel_start
        assert not worker.is_alive(), "native run did not abort within two seconds"
        assert isinstance(result.get("outcome"), native.Aborted)
    after = _free_vram_mib()
    record_property("transcribe_cpp_version", native.__version__)
    record_property("max_feed_s", round(max_feed_s, 3))
    record_property("finalize_s", round(finalize_s, 3))
    record_property("cancel_s", round(cancel_s, 3))
    record_property("free_vram_after_mib", after)
