"""Lazy 16 kHz mono PCM WAV output."""

import wave
from array import array
from pathlib import Path
from sys import byteorder
from typing import Any


class WavWriter:
    """Write clipped float samples as little-endian mono 16-bit PCM."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._wave: wave.Wave_write | None = None
        self._frames_written = 0
        self._closed = False

    def open(self) -> None:
        """Create the WAV file and its header, if it has not been opened."""
        if self._closed:
            return
        if self._wave is None:
            writer = wave.open(str(self._path), "wb")
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(16_000)
            self._wave = writer

    def write(self, samples: Any) -> None:
        """Append float32 samples, clipping before PCM conversion."""
        if self._closed:
            raise ValueError("cannot write to a closed WAV")
        self.open()
        if self._wave is None:
            raise RuntimeError("WAV writer failed to open")
        encoded = array("h")
        for sample in samples:
            clipped = min(1.0, max(-1.0, float(sample)))
            scale = 32768.0 if clipped < 0 else 32767.0
            encoded.append(round(clipped * scale))
        if byteorder != "little":
            encoded.byteswap()
        self._wave.writeframesraw(encoded.tobytes())
        self._frames_written += len(encoded)

    def close(self) -> None:
        """Finalize the header and close the file; repeated calls are harmless."""
        if self._closed:
            return
        self._closed = True
        if self._wave is not None:
            self._wave.close()
            self._wave = None

    @property
    def frames_written(self) -> int:
        """Number of audio frames appended so far."""
        return self._frames_written
