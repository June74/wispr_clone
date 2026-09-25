"""P-SOXR-001: isolated resampler length and tone contract."""

from importlib.metadata import version

import numpy as np
import pytest
import soxr


@pytest.mark.probe("soxr")
def test_P_SOXR_001_length_and_tone_survive_48k_to_16k():
    assert version("soxr") == "1.1.0"
    source_rate = 48_000
    output_rate = 16_000
    signal = np.sin(2 * np.pi * 1000 * np.arange(source_rate) / source_rate).astype(
        np.float32
    )
    output = soxr.resample(signal, source_rate, output_rate, quality="HQ")
    assert abs(len(output) - 16_000) <= 1
    peak = int(np.argmax(np.abs(np.fft.rfft(output))))
    frequency = np.fft.rfftfreq(len(output), 1 / output_rate)[peak]
    assert abs(frequency - 1000) <= 20
