"""T-AUD-CUE-001/002: recording cues are valid WAVs and never break a run."""

from __future__ import annotations

import io
import wave
from pathlib import Path

import pytest

from wispr_clone.audio.cues import SoundCues, tick_wav


@pytest.mark.unit
def test_T_AUD_CUE_001_tick_is_short_quiet_mono_wav() -> None:
    data = tick_wav(660.0, 880.0)
    with wave.open(io.BytesIO(data)) as reader:
        assert (reader.getnchannels(), reader.getsampwidth()) == (1, 2)
        seconds = reader.getnframes() / reader.getframerate()
        frames = reader.readframes(reader.getnframes())
    assert 0.05 < seconds < 0.15
    samples = [
        int.from_bytes(frames[i : i + 2], "little", signed=True)
        for i in range(0, len(frames), 2)
    ]
    assert max(abs(sample) for sample in samples) < 0.2 * 32767
    assert abs(samples[0]) < 200 and abs(samples[-1]) < 200  # faded, no click


@pytest.mark.unit
def test_T_AUD_CUE_002_play_writes_each_cue_once_and_swallows_failures(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    played: list[Path] = []
    cues = SoundCues(tmp_path / "cues", play_file=played.append)
    cues.play("start")
    cues.play("stop")
    cues.play("start")
    assert [path.name for path in played] == [
        "cue_start.wav",
        "cue_stop.wav",
        "cue_start.wav",
    ]
    assert played[0].read_bytes() != played[1].read_bytes()

    def broken(_path: Path) -> None:
        raise OSError("no audio device")

    SoundCues(tmp_path / "other", play_file=broken).play("stop")
    assert "SOUND_CUE_FAILED" in caplog.text
