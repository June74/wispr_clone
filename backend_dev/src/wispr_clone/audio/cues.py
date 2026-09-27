"""Soft start/stop ticks for recording, played through the Windows sound API.

The ticks are generated once as small WAV files in the app data directory and
played asynchronously, so a cue never delays the recording it announces.
"""

from __future__ import annotations

import io
import logging
import math
import struct
import sys
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

Cue = Literal["start", "stop"]
# A rising pair for start and a falling pair for stop, like a light "tick-tock".
_TONES: dict[Cue, tuple[float, float]] = {
    "start": (660.0, 880.0),
    "stop": (880.0, 587.0),
}
_RATE = 44_100
_NOTE_MS = 45
_VOLUME = 0.16


def tick_wav(first_hz: float, second_hz: float) -> bytes:
    """Two short sine notes with smooth fades, as 16-bit mono WAV bytes."""
    frames = bytearray()
    note = int(_RATE * _NOTE_MS / 1000)
    fade = int(_RATE * 0.008)
    for hz in (first_hz, second_hz):
        for index in range(note):
            envelope = min(1.0, index / fade, (note - index) / fade)
            sample = _VOLUME * envelope * math.sin(2 * math.pi * hz * index / _RATE)
            frames += struct.pack("<h", int(sample * 32767))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(_RATE)
        writer.writeframes(bytes(frames))
    return buffer.getvalue()


def _play_file(path: Path) -> None:
    if sys.platform != "win32":
        return
    import winsound

    winsound.PlaySound(
        str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
    )


class SoundCues:
    """Play a cue by name; failures are logged, never raised into a run."""

    def __init__(
        self, directory: Path, *, play_file: Callable[[Path], None] | None = None
    ) -> None:
        self._directory = directory
        self._ready: dict[Cue, Path] = {}
        self._play_file = play_file
        if self._play_file is None and sys.platform == "win32":
            self._play_file = _play_file

    def _path(self, cue: Cue) -> Path:
        path = self._ready.get(cue)
        if path is None:
            # Rewritten once per launch so a changed tone never plays a stale file.
            path = self._directory / f"cue_{cue}.wav"
            self._directory.mkdir(parents=True, exist_ok=True)
            path.write_bytes(tick_wav(*_TONES[cue]))
            self._ready[cue] = path
        return path

    def play(self, cue: Cue) -> None:
        if self._play_file is None:
            return
        try:
            self._play_file(self._path(cue))
        except Exception:
            logger.warning("SOUND_CUE_FAILED")
