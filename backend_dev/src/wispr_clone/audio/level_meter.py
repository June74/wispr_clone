"""FFT-based frequency band levels for the recording waveform."""

import numpy as np

BAND_COUNT = 12


def band_levels(samples: np.ndarray, sample_rate: int = 16_000) -> list[float]:
    """Return twelve log-spaced peak spectral levels normalized from -60 to 0 dBFS."""
    values = np.asarray(samples, dtype=np.float64).reshape(-1)
    if values.size == 0 or not np.any(values):
        return [0.0] * BAND_COUNT
    window = np.hanning(values.size)
    spectrum = np.abs(np.fft.rfft(values * window)) * (2.0 / window.sum())
    frequencies = np.fft.rfftfreq(values.size, d=1.0 / sample_rate)
    edges = np.geomspace(80.0, 7600.0, BAND_COUNT + 1)
    levels: list[float] = []
    for low, high in zip(edges[:-1], edges[1:], strict=True):
        indices = np.flatnonzero((frequencies >= low) & (frequencies < high))
        if indices.size:
            peak = float(np.max(spectrum[indices]))
        else:
            nearest = int(np.argmin(np.abs(frequencies - (low + high) / 2.0)))
            peak = float(spectrum[nearest])
        decibels = 20.0 * np.log10(max(peak, 1e-12))
        levels.append(float(np.clip((decibels + 60.0) / 60.0, 0.0, 1.0)))
    return levels
