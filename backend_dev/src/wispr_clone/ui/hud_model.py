"""Pure layout and state rules for the native pill HUD."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

HUD_SPEC = {
    "width": 272,
    "height": 44,
    "padding_left": 16,
    "padding_right": 6,
    "gap": 12,
    "label_size": 12,
    "dot_size": 8,
    "radius": 22,
    "shadow_margin": 14,
}

STATUS_LABELS = {
    "recording": "Listening",
    "awaiting_destination": "Working",
    "processing": "Working",
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
    label_rect: Rect
    timer_rect: Rect
    cancel_rect: Rect


class HudTimer:
    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._elapsed = 0.0
        self._started: float | None = None

    def set_status(self, status: str) -> None:
        now = self._clock()
        if status == "recording":
            if self._started is None:
                self._elapsed = 0.0
                self._started = now
        elif self._started is not None:
            self._elapsed += now - self._started
            self._started = None

    @property
    def text(self) -> str:
        elapsed = self._elapsed
        if self._started is not None:
            elapsed += self._clock() - self._started
        return format_timer(elapsed)


def format_timer(seconds: float) -> str:
    whole_seconds = max(0, int(seconds))
    return f"{whole_seconds // 60}:{whole_seconds % 60:02d}"


def classify_hit(hud_layout: HudLayout, x: float, y: float) -> str:
    pill = hud_layout.pill_rect
    radius = HUD_SPEC["radius"] * (pill.right - pill.left) / HUD_SPEC["width"]
    if not (pill.left <= x < pill.right and pill.top <= y < pill.bottom):
        return "transparent"
    corner_x = min(max(x, pill.left + radius), pill.right - radius)
    corner_y = min(max(y, pill.top + radius), pill.bottom - radius)
    if (x - corner_x) ** 2 + (y - corner_y) ** 2 > radius**2:
        return "transparent"
    button = hud_layout.cancel_rect
    cx, cy = (button.left + button.right) / 2, (button.top + button.bottom) / 2
    button_radius = (button.right - button.left) / 2
    if (x - cx) ** 2 + (y - cy) ** 2 <= button_radius**2:
        return "cancel"
    return "client"


def status_color(status: str) -> str:
    return _COLORS.get(status, _IDLE_COLOR)


def layout(scale: float) -> HudLayout:
    margin = HUD_SPEC["shadow_margin"] * scale
    x = y = margin
    width = HUD_SPEC["width"] * scale
    height = HUD_SPEC["height"] * scale
    center_y = y + height / 2
    dot_radius = HUD_SPEC["dot_size"] * scale / 2
    dot_x = x + HUD_SPEC["padding_left"] * scale + dot_radius
    label_x = dot_x + dot_radius + HUD_SPEC["gap"] * scale
    right = x + width - HUD_SPEC["padding_right"] * scale
    cancel_size = 28 * scale
    cancel_rect = Rect(
        right - cancel_size,
        center_y - cancel_size / 2,
        right,
        center_y + cancel_size / 2,
    )
    timer_right = cancel_rect.left - HUD_SPEC["gap"] * scale
    timer_rect = Rect(timer_right - 38 * scale, y, timer_right, y + height)
    label_rect = Rect(label_x, y, timer_rect.left - HUD_SPEC["gap"] * scale, y + height)
    return HudLayout(
        window_width=(HUD_SPEC["width"] + 2 * HUD_SPEC["shadow_margin"]) * scale,
        window_height=(HUD_SPEC["height"] + 2 * HUD_SPEC["shadow_margin"]) * scale,
        pill_rect=Rect(x, y, x + width, y + height),
        dot_center=(dot_x, center_y),
        dot_radius=dot_radius,
        label_rect=label_rect,
        timer_rect=timer_rect,
        cancel_rect=cancel_rect,
    )
