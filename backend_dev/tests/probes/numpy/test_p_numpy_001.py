"""P-NUMPY-001: isolated FFT contract for the locked NumPy build."""

import numpy as np
import pytest


@pytest.mark.probe("numpy")
def test_P_NUMPY_001_known_sine_fft_peak():
    assert np.__version__ == "2.5.3"
    rate = 16_000
    samples = np.sin(2 * np.pi * 1000 * np.arange(rate) / rate)
    spectrum = np.fft.rfft(samples)
    assert np.argmax(np.abs(spectrum)) == 1000
    assert np.fft.rfftfreq(rate, 1 / rate)[1000] == 1000
