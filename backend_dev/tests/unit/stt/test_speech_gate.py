"""T-STT-030/031: only speech is sent; silence phrases are not pasted."""

from __future__ import annotations

import numpy as np
import pytest

from wispr_clone.stt.speech_gate import (
    PAD_AFTER_S,
    PAD_BEFORE_S,
    drop_hallucination,
    find_speech,
)

RATE = 16_000


def pcm(*parts: np.ndarray) -> bytes:
    audio = np.concatenate(parts)
    return (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()


def tone(seconds: float, amplitude: float = 0.3) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    return amplitude * np.sin(2 * np.pi * 220 * t)


def noise(seconds: float, level: float = 0.002, seed: int = 1) -> np.ndarray:
    return np.random.default_rng(seed).normal(0, level, int(seconds * RATE))


@pytest.mark.unit
def test_T_STT_030_trims_silence_around_speech() -> None:
    found = find_speech(pcm(noise(2.0), tone(1.0), noise(3.0, seed=2)), RATE)
    assert found is not None
    assert found.speech_s == pytest.approx(1.0, abs=0.05)
    kept_s = len(found.pcm) / 2 / RATE
    assert kept_s == pytest.approx(1.0 + PAD_BEFORE_S + PAD_AFTER_S, abs=0.05)


@pytest.mark.unit
@pytest.mark.parametrize(
    "audio",
    [
        noise(3.0),  # room noise only
        np.zeros(RATE * 2),  # digital silence
        np.concatenate([noise(1.0), tone(0.08, 0.8), noise(1.0, seed=3)]),  # a click
        np.zeros(10),  # shorter than one frame
    ],
    ids=["noise", "silence", "click", "tiny"],
)
def test_T_STT_030_no_speech_is_not_sent(audio: np.ndarray) -> None:
    assert find_speech(pcm(audio), RATE) is None


@pytest.mark.unit
def test_T_STT_030_speech_from_start_to_end_is_kept() -> None:
    found = find_speech(pcm(tone(2.0)), RATE)
    assert found is not None
    assert found.speech_s == pytest.approx(2.0, abs=0.05)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("text", "speech_s", "kept"),
    [
        ("Thank you.", 0.4, ""),
        (" thanks for watching! ", 1.0, ""),
        ("Thank you.", 2.0, "Thank you."),  # long enough to be really said
        ("Thank you for the report.", 0.8, "Thank you for the report."),
        ("Send it tomorrow.", 0.5, "Send it tomorrow."),
    ],
)
def test_T_STT_031_drops_only_bare_silence_phrases(
    text: str, speech_s: float, kept: str
) -> None:
    assert drop_hallucination(text, speech_s) == kept
