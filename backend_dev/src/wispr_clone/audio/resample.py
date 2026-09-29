"""Streaming sample-rate conversion for captured audio."""

from typing import Any

import soxr  # type: ignore[import-untyped]

TARGET_RATE = 16_000


def streaming_resampler(source_rate: int) -> Any:
    """Create the stateful mono stream used for one capture session."""
    return soxr.ResampleStream(
        source_rate, TARGET_RATE, 1, dtype="float32", quality="HQ"
    )
