"""T-UI-012: the native HUD keeps the approved web labels and v2 geometry."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from wispr_clone.ui import hud_model

WEB = Path(__file__).resolve().parents[3] / "web"


def _value(obj: object, name: str) -> object:
    return obj[name] if isinstance(obj, dict) else getattr(obj, name)


@pytest.mark.unit
def test_T_UI_012_spec_and_labels_follow_approved_hud() -> None:
    spec = hud_model.HUD_SPEC
    for name, expected in {
        "width": 272,
        "height": 44,
        "padding_left": 16,
        "padding_right": 6,
        "gap": 12,
        "label_size": 12,
        "label_weight": 500,
        "dot_size": 8,
        "wave_width": 88,
        "wave_height": 28,
        "radius": 22,
        "shadow_margin": 14,
    }.items():
        assert _value(spec, name) == expected

    source = (WEB / "hud.js").read_text(encoding="utf-8")
    expression = re.search(r"label\.textContent\s*=\s*(.*?);", source, re.S)
    assert expression is not None
    condition = r"status\s*===\s*'[^']+'(?:\s*\|\|\s*status\s*===\s*'[^']+')*"
    branches = {
        status: label
        for matches, label in re.findall(
            rf"({condition})\s*\?\s*'([^']+)'", expression[1]
        )
        for status in re.findall(r"status\s*===\s*'([^']+)'", matches)
    }
    assert branches == {
        "recording": "Listening",
        "processing": "Working",
        "awaiting_destination": "Waiting for destination",
        "awaiting_cleanup_choice": "Needs attention",
        "error": "Could not confirm",
        "uncertain": "Could not confirm",
    }
    assert hud_model.STATUS_LABELS == {
        **branches,
        "idle": "Ready",
    }


@pytest.mark.unit
def test_T_UI_012_colors_visibility_and_layout() -> None:
    source = (WEB / "lib" / "view.js").read_text(encoding="utf-8")
    assert "status === 'recording') return { color: 'green'" in source
    assert "status === 'processing' || status === 'awaiting_destination'" in source
    assert "['awaiting_cleanup_choice', 'error', 'uncertain']" in source
    for status, color in {
        "recording": "#6fb58b",
        "processing": "#d4a954",
        "awaiting_destination": "#d4a954",
        "awaiting_cleanup_choice": "#e0848b",
        "error": "#e0848b",
        "uncertain": "#e0848b",
        "idle": "#8a8191",
        "done": "#8a8191",
    }.items():
        assert hud_model.status_color(status) == color
    assert hud_model.hud_visible("recording")
    assert hud_model.hud_visible("processing")
    assert hud_model.hud_visible("awaiting_destination")
    assert hud_model.hud_visible("awaiting_cleanup_choice")
    assert not hud_model.hud_visible("idle")

    for scale in (1, 1.5):
        result = hud_model.layout(scale)
        assert _value(result, "window_width") == round(300 * scale)
        assert _value(result, "window_height") == round(72 * scale)
        pill = _value(result, "pill_rect")
        wave = _value(result, "wave_rect")
        assert _value(pill, "right") - _value(pill, "left") == round(272 * scale)
        assert _value(pill, "bottom") - _value(pill, "top") == round(44 * scale)
        assert _value(wave, "right") == _value(pill, "right") - round(6 * scale)
        assert _value(wave, "right") - _value(wave, "left") == round(88 * scale)
        assert _value(wave, "bottom") - _value(wave, "top") == round(28 * scale)
