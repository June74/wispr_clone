"""Find the speech in a recording before it is sent for transcription.

Whisper-family models hallucinate on silence: a silent recording, or the quiet
tail after the last word, comes back as "Thank you." or "Thanks for watching!"
(common captions on silent video endings in their training data). So the
recording is trimmed to its speech, a recording without speech is not sent,
and a very short result that is only such a phrase is discarded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

FRAME_S = 0.02
# A frame is speech when it is this much louder than the recording's noise floor,
# and never below the absolute floor (so near-digital-silence noise is ignored).
ABOVE_NOISE_DB = 10.0
ABSOLUTE_FLOOR_DB = -50.0
# Clearly audible frames always count, so a recording that is speech from end to
# end (no quiet frames to measure the noise floor from) is not mistaken for noise.
ALWAYS_SPEECH_DB = -40.0
MIN_SPEECH_S = 0.2
PAD_BEFORE_S = 0.3
PAD_AFTER_S = 0.4
HALLUCINATION_MAX_SPEECH_S = 1.5
_HALLUCINATIONS = frozenset(
    {
        "thank you",
        "thank you very much",
        "thanks",
        "thanks for watching",
        "thank you for watching",
        "thank you so much for watching",
        "you",
        "bye",
    }
)


@dataclass(frozen=True, slots=True)
class Speech:
    pcm: bytes
    speech_s: float


def find_speech(pcm: bytes, sample_rate: int) -> Speech | None:
    """Trim 16-bit mono PCM to its speech (with margins); None when there is none."""
    samples = np.frombuffer(pcm[: len(pcm) - len(pcm) % 2], dtype="<i2")
    frame = max(1, int(sample_rate * FRAME_S))
    count = len(samples) // frame
    if count == 0:
        return None
    frames = samples[: count * frame].astype(np.float32).reshape(count, frame) / 32768
    level_db = 20 * np.log10(np.sqrt(np.mean(frames * frames, axis=1)) + 1e-9)
    noise_db = float(np.percentile(level_db, 10))
    threshold = max(ABSOLUTE_FLOOR_DB, min(noise_db + ABOVE_NOISE_DB, ALWAYS_SPEECH_DB))
    speech = level_db > threshold
    speech_s = float(np.count_nonzero(speech)) * FRAME_S
    if speech_s < MIN_SPEECH_S:
        return None
    indices = np.flatnonzero(speech)
    start = max(0, int(indices[0]) * frame - int(PAD_BEFORE_S * sample_rate))
    end = min(
        len(samples), (int(indices[-1]) + 1) * frame + int(PAD_AFTER_S * sample_rate)
    )
    return Speech(samples[start:end].astype("<i2").tobytes(), speech_s)


def drop_hallucination(text: str, speech_s: float) -> str:
    """Discard a result that is only a known silence phrase from a brief sound."""
    if speech_s >= HALLUCINATION_MAX_SPEECH_S:
        return text
    words = re.sub(r"[^\w\s]", " ", text.lower()).split()
    return "" if " ".join(words) in _HALLUCINATIONS else text
