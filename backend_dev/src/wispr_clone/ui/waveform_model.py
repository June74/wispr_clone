"""Frame-based port of the runtime canvas waveform model."""

from __future__ import annotations

import math
from collections.abc import Sequence

N = 29
W = 340
H = 72
SCALE = 2
CENTER = 36
REST = 2
OPACITY = tuple(0.30 + 0.55 * math.sin(math.pi * index / 28) for index in range(N))


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _interpolate(values: Sequence[float], position: float) -> float:
    at = _clamp(position, 0, len(values) - 1)
    low = math.floor(at)
    high = min(len(values) - 1, low + 1)
    return values[low] + (values[high] - values[low]) * (at - low)


def _smooth_sample(values: Sequence[float], position: float, radius: int) -> float:
    total = 0.0
    weights = 0
    for offset in range(-radius, radius + 1):
        weight = radius + 1 - abs(offset)
        total += _interpolate(values, position + offset) * weight
        weights += weight
    return total / weights


def targets(level: float, bands: Sequence[float], wave: Sequence[float]) -> list[float]:
    return [
        REST
        + 57
        * _clamp(level)
        * (
            0.025
            + 0.84 * _smooth_sample(bands, index / 28 * 31, 1)
            + 0.135 * abs(_smooth_sample(wave, index / 28 * 127, 2))
        )
        for index in range(N)
    ]


def resampleBands(bands: Sequence[float]) -> list[float]:
    values = [
        _clamp(float(bands[index]) if index < len(bands) else 0.0)
        for index in range(12)
    ]
    return [_interpolate(values, index * 11 / 31) for index in range(32)]


def levelFromBands(bands: Sequence[float]) -> float:
    return _clamp(
        max(
            0.0,
            *(
                float(bands[index]) if index < len(bands) else 0.0
                for index in range(12)
            ),
        )
    )


def X(index: int) -> float:
    return 44 + 9 * index


def smoothLevel(current: float, target: float, dt: float) -> float:
    next_level = current + (target - current) * (
        1 - math.exp(-dt / (0.045 if target > current else 0.150))
    )
    if target == 0 and next_level < 0.008:
        next_level = 0
    return next_level


def smoothBands(
    current32: Sequence[float], target32: Sequence[float], dt: float
) -> list[float]:
    return [
        current + (target32[index] - current) * (1 - math.exp(-dt / 0.07))
        for index, current in enumerate(current32)
    ]


class WaveformModel:
    """Stateful port: update inputs, then tick with elapsed seconds."""

    def __init__(self) -> None:
        self.mode = "idle"
        self.level = 0.0
        self.bands = [0.0] * 32
        self.target_level = 0.0
        self.target_bands = [0.0] * 32
        self.heights: list[float] = [float(REST)] * N

    def update(self, bands12: Sequence[float], running: bool) -> None:
        values = bands12 if len(bands12) == 12 else [0.0] * 12
        self.target_bands = resampleBands(values)
        self.target_level = levelFromBands(values)
        self.mode = "active" if running else "idle"

    def tick(self, dt: float) -> list[float]:
        dt = min(0.08, dt or 0.016)
        self.level = smoothLevel(self.level, self.target_level, dt)
        self.bands = smoothBands(self.bands, self.target_bands, dt)
        paint_dt = min(0.15, max(0.008, dt))
        desired = targets(self.level, self.bands, [0.0] * 128)
        immediate = self.level == 0
        for index, target in enumerate(desired):
            easing = (
                1
                if immediate
                else 1
                - math.exp(
                    -paint_dt / (0.045 if target > self.heights[index] else 0.110)
                )
            )
            self.heights[index] += (target - self.heights[index]) * easing
        return self.heights.copy()


# Python callers use snake_case while the port retains the source names above.
resample_bands = resampleBands
level_from_bands = levelFromBands
smooth_level = smoothLevel
smooth_bands = smoothBands
