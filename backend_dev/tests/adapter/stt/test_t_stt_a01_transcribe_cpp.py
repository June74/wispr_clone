"""Real Voxtral adapter lifecycle on generated, non-speech audio."""

import asyncio
import importlib.util
import math
import subprocess
import sys
import time
import wave
from pathlib import Path

import pytest

from wispr_clone.stt.voxtral_transcribe_cpp import VoxtralTranscribeCpp

pytestmark = [
    pytest.mark.gpu,
    pytest.mark.adapter("transcribe-cpp"),
    pytest.mark.skipif(
        sys.platform != "win32", reason="Windows CUDA adapter test only"
    ),
]

GGUF = Path(
    r"C:\Users\2006i\.lmstudio\models\handy-computer\Voxtral-Mini-4B-Realtime-2602-gguf\Voxtral-Mini-4B-Realtime-2602-Q4_K_M.gguf"
)


def _free_vram_mib():
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return int(result.stdout.strip().splitlines()[0].strip())


def test_T_STT_A01_real_adapter_file_and_close(tmp_path, record_property):
    if importlib.util.find_spec("transcribe_cpp") is None:
        pytest.skip("transcribe_cpp missing")
    if not GGUF.is_file():
        pytest.skip(f"GGUF missing: {GGUF}")
    wav = tmp_path / "generated_tone_silence.wav"
    import array

    samples = array.array(
        "h",
        (
            int(1000 * math.sin(2 * math.pi * 440 * i / 16_000)) if i < 8_000 else 0
            for i in range(16_000)
        ),
    )
    with wave.open(str(wav), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16_000)
        writer.writeframes(samples.tobytes())

    async def exercise():
        adapter = VoxtralTranscribeCpp(GGUF)
        try:
            started = time.perf_counter()
            await adapter.start()
            load_s = time.perf_counter() - started
            assert adapter.ready
            started = time.perf_counter()
            text = await adapter.transcribe_file(wav)
            transcription_s = time.perf_counter() - started
            assert isinstance(text, str)
            return load_s, transcription_s
        finally:
            await adapter.close()

    before = _free_vram_mib()
    record_property("free_vram_before_mib", before)
    load_s, transcription_s = asyncio.run(exercise())
    after = _free_vram_mib()
    record_property("load_and_warm_s", round(load_s, 3))
    record_property("transcribe_file_s", round(transcription_s, 3))
    record_property("free_vram_after_close_mib", after)
