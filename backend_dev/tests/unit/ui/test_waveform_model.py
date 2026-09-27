"""T-UI-013: the Python port agrees with Node's real waveform renderer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wispr_clone.ui import waveform_model

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "waveform_golden.json"


@pytest.mark.unit
def test_T_UI_013_sampling_and_targets_match_golden() -> None:
    golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert waveform_model.level_from_bands(golden["input"]) == pytest.approx(
        golden["level"]
    )
    assert waveform_model.resample_bands(golden["input"]) == pytest.approx(
        golden["bands"], abs=1e-6
    )
    assert waveform_model.targets(
        golden["level"], golden["bands"], golden["wave"]
    ) == pytest.approx(golden["targets"], abs=1e-6)


@pytest.mark.unit
def test_T_UI_013_sixty_frames_match_real_canvas_path() -> None:
    golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
    model = waveform_model.WaveformModel()
    model.update(golden["input"], True)
    assert len(golden["frames"]) == 60
    for index, expected in enumerate(golden["frames"]):
        assert model.tick(0.032) == pytest.approx(expected, abs=1e-5), index
