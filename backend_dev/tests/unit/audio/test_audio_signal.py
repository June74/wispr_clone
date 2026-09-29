"""T-AUD signal processing and WAV acceptance with generated tones only."""

import importlib
import wave

import numpy as np
import pytest


def tone(rate: int, seconds: float = 1.0, amplitude: float = 1.0) -> np.ndarray:
    frames = np.arange(round(rate * seconds), dtype=np.float64)
    return (amplitude * np.sin(2 * np.pi * 1000 * frames / rate)).astype(np.float32)


@pytest.mark.unit
def test_T_AUD_004_fft_bands_track_level_and_silence():
    meter = importlib.import_module("wispr_clone.audio.level_meter")
    full = meter.band_levels(tone(16_000), 16_000)
    quiet = meter.band_levels(tone(16_000, amplitude=10 ** (-30 / 20)), 16_000)
    silent = meter.band_levels(np.zeros(16_000, dtype=np.float32), 16_000)
    assert len(full) == len(quiet) == len(silent) == meter.BAND_COUNT == 12
    assert all(
        type(value) is float and 0 <= value <= 1 for value in full + quiet + silent
    )
    assert silent == [0.0] * 12
    # Twelve logarithmic bands from 80 to 7600 Hz put 1 kHz in band index 6.
    assert max(range(12), key=full.__getitem__) == 6
    assert quiet[6] == pytest.approx(0.5, abs=0.1)
    assert full[6] > quiet[6]


@pytest.mark.unit
def test_T_AUD_004_too_short_chunk_returns_finite_levels():
    meter = importlib.import_module("wispr_clone.audio.level_meter")
    for source in (np.array([], dtype=np.float32), np.array([0.5], dtype=np.float32)):
        levels = meter.band_levels(source)
        assert len(levels) == meter.BAND_COUNT
        assert all(
            type(level) is float and np.isfinite(level) and 0 <= level <= 1
            for level in levels
        )


@pytest.mark.unit
def test_T_AUD_005_wav_writer_valid_after_normal_and_partial_close(tmp_path):
    writer_module = importlib.import_module("wispr_clone.audio.wav_writer")
    values = np.array([-1.0, -0.5, 0.0, 0.5, 1.0], dtype=np.float32)
    for parts in ((values[:2], values[2:]), (values[:2],)):
        path = tmp_path / f"audio_{len(parts)}.wav"
        writer = writer_module.WavWriter(path)
        for part in parts:
            writer.write(part)
        expected = np.concatenate(parts)
        assert writer.frames_written == len(expected)
        writer.close()
        writer.close()
        with wave.open(str(path), "rb") as wav:
            assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (
                16_000,
                1,
                2,
            )
            assert wav.getnframes() == len(expected)
            decoded = np.frombuffer(wav.readframes(len(expected)), dtype="<i2") / 32768
        np.testing.assert_allclose(decoded, expected, atol=1 / 32768)

    empty_path = tmp_path / "audio_empty.wav"
    writer = writer_module.WavWriter(empty_path)
    writer.close()
    writer.close()
    assert not empty_path.exists()

    clipped_path = tmp_path / "audio_clipped.wav"
    writer = writer_module.WavWriter(clipped_path)
    writer.write(np.array([-2.0, 2.0], dtype=np.float32))
    writer.close()
    with wave.open(str(clipped_path), "rb") as wav:
        clipped = np.frombuffer(wav.readframes(2), dtype="<i2")
    np.testing.assert_array_equal(clipped, np.array([-32768, 32767]))
