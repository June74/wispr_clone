"""T-UI-012/016/017: the native pill's layout, timer, and hit rules."""

from __future__ import annotations

import pytest

from wispr_clone.ui.hud_model import (
    HUD_SPEC,
    STATUS_LABELS,
    hud_visible,
    layout,
    status_color,
)


@pytest.mark.unit
def test_T_UI_012_pill_content_and_layout() -> None:
    assert HUD_SPEC["width"] == 272
    assert HUD_SPEC["height"] == 44
    assert HUD_SPEC["radius"] == 22
    assert HUD_SPEC["shadow_margin"] == 14
    assert STATUS_LABELS == {
        "recording": "Listening",
        "processing": "Working",
        "awaiting_destination": "Working",
        "awaiting_cleanup_choice": "Needs attention",
        "error": "Could not confirm",
        "uncertain": "Could not confirm",
        "idle": "Ready",
    }
    assert status_color("recording") == "#6fb58b"
    assert status_color("processing") == "#d4a954"
    assert status_color("awaiting_destination") == "#d4a954"
    assert status_color("awaiting_cleanup_choice") == "#e0848b"
    assert not hud_visible("idle")
    for status in ("recording", "processing", "awaiting_destination"):
        assert hud_visible(status)

    for scale in (1, 1.5):
        result = layout(scale)
        pill = result.pill_rect
        label = result.label_rect
        timer = result.timer_rect
        cancel = result.cancel_rect
        assert result.window_width == 300 * scale
        assert result.window_height == 72 * scale
        assert (pill.left, pill.top, pill.right, pill.bottom) == (
            14 * scale,
            14 * scale,
            286 * scale,
            58 * scale,
        )
        assert result.dot_center == (34 * scale, 36 * scale)
        assert result.dot_radius == 4 * scale
        assert label.left == 50 * scale
        assert label.right <= timer.left
        assert label.top >= pill.top
        assert label.bottom <= pill.bottom
        assert timer.right == cancel.left - 12 * scale
        assert timer.right - timer.left >= 38 * scale
        assert cancel.right - cancel.left == 28 * scale
        assert cancel.bottom - cancel.top == 28 * scale
        assert cancel.right == pill.right - 6 * scale
        assert (cancel.top + cancel.bottom) / 2 == (pill.top + pill.bottom) / 2
        assert not hasattr(result, "wave_rect")


@pytest.mark.unit
def test_T_UI_016_timer_formats_and_freezes_with_fake_clock() -> None:
    from wispr_clone.ui.hud_model import HudTimer, format_timer

    assert [format_timer(seconds) for seconds in (0, 7, 65)] == [
        "0:00",
        "0:07",
        "1:05",
    ]
    now = [100.0]
    timer = HudTimer(clock=lambda: now[0])
    timer.set_status("recording")
    assert timer.text == "0:00"
    now[0] += 7
    assert timer.text == "0:07"
    now[0] += 58
    assert timer.text == "1:05"
    timer.set_status("processing")
    now[0] += 30
    assert timer.text == "1:05"
    timer.set_status("awaiting_destination")
    now[0] += 30
    assert timer.text == "1:05"
    timer.set_status("recording")
    assert timer.text == "0:00"
    now[0] += 7
    assert timer.text == "0:07"


@pytest.mark.unit
@pytest.mark.parametrize("scale", [1, 1.5])
def test_T_UI_017_hit_classification(scale: float) -> None:
    from wispr_clone.ui.hud_model import classify_hit

    result = layout(scale)
    cancel = result.cancel_rect
    pill = result.pill_rect
    assert (
        classify_hit(
            result, (cancel.left + cancel.right) / 2, (cancel.top + cancel.bottom) / 2
        )
        == "cancel"
    )
    assert classify_hit(result, result.dot_center[0], result.dot_center[1]) == "client"
    assert classify_hit(result, pill.left - 1, result.dot_center[1]) == "transparent"
    assert classify_hit(result, pill.left, pill.top) == "transparent"
