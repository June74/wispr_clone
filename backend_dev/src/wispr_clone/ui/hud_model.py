"""Pure layout and state rules for the native pill HUD."""

from __future__ import annotations

from dataclasses import dataclass

HUD_SPEC = {
    "width": 272,
    "height": 44,
    "padding_left": 16,
    "padding_right": 6,
    "padding_y": 6,
    "gap": 12,
    "label_size": 12,
    "label_weight": 500,
    "dot_size": 8,
    "wave_width": 88,
    "wave_height": 28,
    "radius": 22,
    "shadow_margin": 14,
}

STATUS_LABELS = {
    "recording": "Listening",
    "processing": "Working",
    "awaiting_destination": "Waiting for destination",
    "awaiting_cleanup_choice": "Needs attention",
    "error": "Could not confirm",
    "uncertain": "Could not confirm",
    "idle": "Ready",
}

_COLORS = {
    "recording": "#6fb58b",
    "processing": "#d4a954",
    "awaiting_destination": "#d4a954",
    "awaiting_cleanup_choice": "#e0848b",
    "error": "#e0848b",
    "uncertain": "#e0848b",
}
_IDLE_COLOR = "#8a8191"


@dataclass(frozen=True, slots=True)
class Rect:
    left: float
    top: float
    right: float
    bottom: float


@dataclass(frozen=True, slots=True)
class HudLayout:
    window_width: float
    window_height: float
    pill_rect: Rect
    dot_center: tuple[float, float]
    dot_radius: float
    label_x: float
    wave_rect: Rect


def status_color(status: str) -> str:
    return _COLORS.get(status, _IDLE_COLOR)


def hud_visible(status: str) -> bool:
    return status in {
        "recording",
        "processing",
        "awaiting_destination",
        "awaiting_cleanup_choice",
    }


def layout(scale: float) -> HudLayout:
    margin = HUD_SPEC["shadow_margin"] * scale
    x = y = margin
    width = HUD_SPEC["width"] * scale
    height = HUD_SPEC["height"] * scale
    center_y = y + height / 2
    dot_x = x + HUD_SPEC["padding_left"] * scale
    dot_radius = HUD_SPEC["dot_size"] * scale / 2
    label_x = dot_x + dot_radius * 2 + HUD_SPEC["gap"] * scale
    wave_x = (
        x
        + (HUD_SPEC["width"] - HUD_SPEC["padding_right"] - HUD_SPEC["wave_width"])
        * scale
    )
    wave_y = center_y - HUD_SPEC["wave_height"] * scale / 2
    wave_width = HUD_SPEC["wave_width"] * scale
    wave_height = HUD_SPEC["wave_height"] * scale
    return HudLayout(
        window_width=(HUD_SPEC["width"] + 2 * HUD_SPEC["shadow_margin"]) * scale,
        window_height=(HUD_SPEC["height"] + 2 * HUD_SPEC["shadow_margin"]) * scale,
        pill_rect=Rect(x, y, x + width, y + height),
        dot_center=(dot_x, center_y),
        dot_radius=dot_radius,
        label_x=label_x,
        wave_rect=Rect(wave_x, wave_y, wave_x + wave_width, wave_y + wave_height),
    )
