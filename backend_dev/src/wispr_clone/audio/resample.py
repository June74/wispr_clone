"""Mono conversion and sample-rate conversion for captured audio."""

from typing import Any

import numpy as np
import soxr  # type: ignore[import-untyped]

TARGET_RATE = 16_000


def streaming_resampler(source_rate: int) -> Any:
    """Create the stateful mono stream used for one capture session."""
    return soxr.ResampleStream(
        source_rate, TARGET_RATE, 1, dtype="float32", quality="HQ"
    )


def to_mono_16k(samples: np.ndarray, source_rate: int) -> np.ndarray:
    """Average channels, resample if needed, and return contiguous float32 mono."""
    audio = np.asarray(samples, dtype=np.float32)
    if audio.ndim == 2:
        audio = audio.mean(axis=1, dtype=np.float32)
    elif audio.ndim != 1:
        raise ValueError("samples must have shape (n,) or (n, channels)")
    if source_rate <= 0:
        raise ValueError("source_rate must be positive")
    if source_rate != TARGET_RATE and audio.size:
        audio = soxr.resample(audio, source_rate, TARGET_RATE, quality="HQ")
    return np.ascontiguousarray(audio, dtype=np.float32)
