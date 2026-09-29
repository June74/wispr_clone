"""Per-pixel-alpha, non-activating Windows HUD drawn with GDI+."""

from __future__ import annotations

import ctypes
import importlib
import logging
import os
import queue
import shutil
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any, cast

from wispr_clone import config
from wispr_clone.ui.hud_model import (
    HUD_SPEC,
    STATUS_LABELS,
    HudTimer,
    classify_hit,
    layout,
    status_color,
)

logger = logging.getLogger(__name__)

_WM_APP = 0x8000
_WM_COMMAND = _WM_APP + 7
_WM_TIMER = 0x0113
_TIMER_ID = 1
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOACTIVATE = 0x0010
_SWP_SHOWWINDOW = 0x0040
_ULW_ALPHA = 2
_WS_POPUP = 0x80000000
_WS_EX_LAYERED = 0x00080000
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_NOACTIVATE = 0x08000000
_WS_EX_TOPMOST = 0x00000008
_WM_NCCREATE = 0x0081
_WM_DESTROY = 0x0002
_WM_MOUSEACTIVATE = 0x0021
_WM_NCHITTEST = 0x0084
_WM_MOUSEMOVE = 0x0200
_WM_MOUSELEAVE = 0x02A3
_WM_LBUTTONUP = 0x0202
_HTCLIENT = 1
_HTTRANSPARENT = -1
_MA_NOACTIVATE = 3
_TME_LEAVE = 0x00000002
_WINDOW_CLASS = "WisprCloneNativeHud"

# The class procedure and class registration outlive every NativeHud instance.
# WM_NCCREATE arrives before CreateWindowExW returns its hwnd, so instances are
# temporarily indexed by their creating thread during that call.
_window_lock = threading.RLock()
_windows: dict[int, NativeHud] = {}
_pending_windows: dict[int, NativeHud] = {}
_window_class_registered = False
_window_proc: Any = None


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    ]


class _TRACKMOUSEEVENT(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("hwndTrack", wintypes.HWND),
        ("dwHoverTime", wintypes.DWORD),
    ]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class NativeHud:
    """Own a Windows layered HUD on a dedicated message-loop thread."""

    def __init__(self, on_cancel: Any = None) -> None:
        self.available = False
        self._hwnd: int | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._closed = threading.Event()
        self._commands: queue.SimpleQueue[tuple[str, dict[str, Any]]] = (
            queue.SimpleQueue()
        )
        self._on_cancel = on_cancel
        self._status = "idle"
        self._timer = HudTimer(time.monotonic)
        self._shown = False
        self._last_draw = 0.0
        self._scale = 1.0
        self._apis: tuple[Any, Any, Any] | None = None
        self.frames_drawn = 0
        self._drawing_reference_loaded = False
        self._window_position = (0, 0)
        self._hover = False
        if sys.platform != "win32":
            return
        self._thread = threading.Thread(
            target=self._run, name="wispr-native-hud", daemon=True
        )
        self._thread.start()
        if self._ready.wait(2.0):
            self.available = bool(self._hwnd)
        if not self.available:
            logger.warning("NATIVE_HUD_START_FAILED")

    def _post(self, name: str, **payload: Any) -> None:
        try:
            if not self.available or not self._hwnd or not self._apis:
                return
            self._commands.put((name, payload))
            user32 = self._apis[0]
            if not user32.PostMessageW(self._hwnd, _WM_COMMAND, 0, 0):
                logger.warning("NATIVE_HUD_POST_FAILED")
        except Exception:
            logger.warning("NATIVE_HUD_POST_FAILED")

    def show(self) -> None:
        self._post("show")

    def hide(self) -> None:
        self._post("hide")

    def publish_event(self, event: dict[str, Any]) -> None:
        try:
            name = event.get("name")
            if name == "run:state":
                status = event.get("status")
                if isinstance(status, str):
                    self._post("state", status=status)
        except Exception:
            logger.warning("NATIVE_HUD_EVENT_FAILED")

    def destroy(self) -> None:
        try:
            if not self.available or not self._hwnd or not self._apis:
                return
            self._commands.put(("destroy", {}))
            self._apis[0].PostMessageW(self._hwnd, _WM_COMMAND, 0, 0)
            self._closed.wait(2.0)
            if self._thread is not None and self._thread.is_alive():
                logger.warning("NATIVE_HUD_DESTROY_TIMEOUT")
        except Exception:
            logger.warning("NATIVE_HUD_DESTROY_FAILED")

    def _run(self) -> None:
        try:
            win_dll = cast(Any, getattr(ctypes, "WinDLL"))
            user32 = win_dll("user32", use_last_error=True)
            gdi32 = win_dll("gdi32", use_last_error=True)
            kernel32 = win_dll("kernel32", use_last_error=True)
            self._declare_apis(user32, gdi32, kernel32)
            self._apis = (user32, gdi32, kernel32)
            self._scale = self._get_scale(user32)
            self._register_window_class(user32, kernel32)
            wc = _WNDCLASSW()
            wc.hInstance = kernel32.GetModuleHandleW(None)
            thread_key = threading.get_native_id()
            with _window_lock:
                _pending_windows[thread_key] = self
            ex = _WS_EX_LAYERED | _WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE | _WS_EX_TOPMOST
            hwnd = user32.CreateWindowExW(
                ex,
                _WINDOW_CLASS,
                "Wispr Clone HUD",
                _WS_POPUP,
                0,
                0,
                1,
                1,
                None,
                None,
                wc.hInstance,
                None,
            )
            with _window_lock:
                _pending_windows.pop(thread_key, None)
            if not hwnd:
                self._ready.set()
                return
            self._hwnd = int(hwnd)
            user32.SetTimer(hwnd, _TIMER_ID, 33, None)
            self._ready.set()
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            user32.DestroyWindow(hwnd)
            with _window_lock:
                _windows.pop(int(hwnd), None)
        except Exception:
            logger.warning("NATIVE_HUD_START_FAILED")
            self._ready.set()
        finally:
            self._closed.set()

    @staticmethod
    def _register_window_class(user32: Any, kernel32: Any) -> None:
        global _window_class_registered, _window_proc
        with _window_lock:
            if _window_class_registered:
                return
            callback_type = cast(Any, getattr(ctypes, "WINFUNCTYPE"))(
                ctypes.c_ssize_t,
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            )
            _window_proc = callback_type(_dispatch_window_message)
            wc = _WNDCLASSW()
            wc.lpfnWndProc = ctypes.cast(_window_proc, ctypes.c_void_p).value
            wc.hInstance = kernel32.GetModuleHandleW(None)
            wc.lpszClassName = _WINDOW_CLASS
            if not user32.RegisterClassW(ctypes.byref(wc)):
                error = cast(Any, getattr(ctypes, "get_last_error"))()
                if error != 1410:
                    raise OSError(error, "RegisterClassW failed")
            _window_class_registered = True

    @staticmethod
    def _declare_apis(user32: Any, gdi32: Any, kernel32: Any) -> None:
        signatures = {
            user32: {
                "DefWindowProcW": (
                    [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM],
                    ctypes.c_ssize_t,
                ),
                "RegisterClassW": ([ctypes.POINTER(_WNDCLASSW)], wintypes.ATOM),
                "CreateWindowExW": (
                    [
                        wintypes.DWORD,
                        wintypes.LPCWSTR,
                        wintypes.LPCWSTR,
                        wintypes.DWORD,
                        ctypes.c_int,
                        ctypes.c_int,
                        ctypes.c_int,
                        ctypes.c_int,
                        wintypes.HWND,
                        wintypes.HMENU,
                        wintypes.HINSTANCE,
                        wintypes.LPVOID,
                    ],
                    wintypes.HWND,
                ),
                "GetMessageW": (
                    [
                        ctypes.POINTER(wintypes.MSG),
                        wintypes.HWND,
                        wintypes.UINT,
                        wintypes.UINT,
                    ],
                    ctypes.c_int,
                ),
                "TranslateMessage": ([ctypes.POINTER(wintypes.MSG)], wintypes.BOOL),
                "DispatchMessageW": ([ctypes.POINTER(wintypes.MSG)], ctypes.c_ssize_t),
                "PostMessageW": (
                    [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM],
                    wintypes.BOOL,
                ),
                "PostQuitMessage": ([ctypes.c_int], None),
                "SetTimer": (
                    [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p],
                    ctypes.c_size_t,
                ),
                "KillTimer": ([wintypes.HWND, ctypes.c_size_t], wintypes.BOOL),
                "SetWindowPos": (
                    [
                        wintypes.HWND,
                        wintypes.HWND,
                        ctypes.c_int,
                        ctypes.c_int,
                        ctypes.c_int,
                        ctypes.c_int,
                        wintypes.UINT,
                    ],
                    wintypes.BOOL,
                ),
                "ShowWindow": ([wintypes.HWND, ctypes.c_int], wintypes.BOOL),
                "DestroyWindow": ([wintypes.HWND], wintypes.BOOL),
                "MonitorFromPoint": ([wintypes.POINT, wintypes.DWORD], wintypes.HANDLE),
                "GetMonitorInfoW": (
                    [wintypes.HANDLE, ctypes.POINTER(_MONITORINFO)],
                    wintypes.BOOL,
                ),
                "GetDC": ([wintypes.HWND], wintypes.HDC),
                "ReleaseDC": ([wintypes.HWND, wintypes.HDC], ctypes.c_int),
                "UpdateLayeredWindow": (
                    [
                        wintypes.HWND,
                        wintypes.HDC,
                        ctypes.POINTER(wintypes.POINT),
                        ctypes.POINTER(wintypes.SIZE),
                        wintypes.HDC,
                        ctypes.POINTER(wintypes.POINT),
                        wintypes.COLORREF,
                        ctypes.POINTER(_BLENDFUNCTION),
                        wintypes.DWORD,
                    ],
                    wintypes.BOOL,
                ),
                "SystemParametersInfoW": (
                    [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT],
                    wintypes.BOOL,
                ),
                "TrackMouseEvent": ([ctypes.POINTER(_TRACKMOUSEEVENT)], wintypes.BOOL),
            },
            gdi32: {
                "CreateCompatibleDC": ([wintypes.HDC], wintypes.HDC),
                "SelectObject": ([wintypes.HDC, wintypes.HGDIOBJ], wintypes.HGDIOBJ),
                "DeleteObject": ([wintypes.HGDIOBJ], wintypes.BOOL),
                "DeleteDC": ([wintypes.HDC], wintypes.BOOL),
            },
            kernel32: {"GetModuleHandleW": ([wintypes.LPCWSTR], wintypes.HMODULE)},
        }
        for dll, functions in cast(Any, signatures).items():
            for name, (args, result) in functions.items():
                function = getattr(dll, name)
                function.argtypes = args
                function.restype = result

    def _get_scale(self, user32: Any) -> float:
        try:
            win_dll = cast(Any, getattr(ctypes, "WinDLL"))
            shcore = win_dll("shcore", use_last_error=True)
            get_dpi = shcore.GetDpiForMonitor
            get_dpi.argtypes = [
                wintypes.HANDLE,
                ctypes.c_int,
                ctypes.POINTER(wintypes.UINT),
                ctypes.POINTER(wintypes.UINT),
            ]
            get_dpi.restype = ctypes.c_long
            monitor = user32.MonitorFromPoint(wintypes.POINT(0, 0), 2)
            xdpi, ydpi = wintypes.UINT(), wintypes.UINT()
            if (
                monitor
                and get_dpi(monitor, 0, ctypes.byref(xdpi), ctypes.byref(ydpi)) == 0
                and xdpi.value
            ):
                return xdpi.value / 96
        except Exception:
            pass
        try:
            dpi = cast(Any, getattr(ctypes, "WinDLL"))(
                "user32", use_last_error=True
            ).GetDpiForSystem()
            return float(dpi) / 96 if dpi else 1.0
        except Exception:
            return 1.0

    def _drain_commands(self, hwnd: int) -> None:
        apis = self._apis
        if apis is None:
            return
        while not self._commands.empty():
            name, payload = self._commands.get()
            if name == "show":
                self._shown = True
                self._position(hwnd)
                apis[0].SetWindowPos(
                    hwnd,
                    wintypes.HWND(-1),
                    0,
                    0,
                    0,
                    0,
                    _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE | _SWP_SHOWWINDOW,
                )
                self._draw(hwnd)
            elif name == "hide":
                self._shown = False
                apis[0].ShowWindow(hwnd, 0)
            elif name == "state":
                status = payload["status"]
                self._status = status
                self._timer.set_status(status)
                self._draw(hwnd)
            elif name == "destroy":
                self._shown = False
                apis[0].ShowWindow(hwnd, 0)
                apis[0].DestroyWindow(hwnd)

    def _position(self, hwnd: int) -> None:
        apis = self._apis
        if apis is None:
            return
        user32 = apis[0]
        monitor = user32.MonitorFromPoint(wintypes.POINT(0, 0), 2)
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(info)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            logger.warning("NATIVE_HUD_MONITOR_FAILED")
            return
        spec = layout(self._scale)
        x = (
            info.rcWork.left
            + (info.rcWork.right - info.rcWork.left - int(spec.window_width)) // 2
        )
        y = info.rcWork.bottom - int(48 * self._scale) - int(spec.window_height)
        self._window_position = (x, y)
        user32.SetWindowPos(
            hwnd,
            wintypes.HWND(-1),
            x,
            y,
            int(spec.window_width),
            int(spec.window_height),
            _SWP_NOACTIVATE | _SWP_SHOWWINDOW,
        )

    def _animate(self, hwnd: int) -> None:
        if not self._shown:
            return
        apis = self._apis
        if apis is None:
            return
        if self._status != "recording":
            return
        now = time.monotonic()
        interval = 0.033
        try:
            reduced = wintypes.BOOL()
            if (
                apis[0].SystemParametersInfoW(0x1042, 0, ctypes.byref(reduced), 0)
                and not reduced.value
            ):
                interval = 0.25
        except Exception:
            pass
        if now - self._last_draw < interval:
            return
        self._draw(hwnd)

    def _draw(self, hwnd: int) -> None:
        resources: list[Any] = []
        try:
            if not self._drawing_reference_loaded:
                clr = importlib.import_module("clr")
                clr.AddReference("System.Drawing")
                self._drawing_reference_loaded = True
            importlib.import_module("System")
            drawing = cast(Any, importlib.import_module("System.Drawing"))
            drawing_2d = cast(Any, importlib.import_module("System.Drawing.Drawing2D"))
            drawing_imaging = cast(
                Any, importlib.import_module("System.Drawing.Imaging")
            )
            drawing_text = cast(Any, importlib.import_module("System.Drawing.Text"))
            Bitmap = drawing.Bitmap
            Color = drawing.Color
            Font = drawing.Font
            FontFamily = drawing.FontFamily
            FontStyle = drawing.FontStyle
            Graphics = drawing.Graphics
            GraphicsPath = drawing_2d.GraphicsPath
            LineCap = drawing_2d.LineCap
            GraphicsUnit = drawing.GraphicsUnit
            Pen = drawing.Pen
            SolidBrush = drawing.SolidBrush
            SmoothingMode = drawing_2d.SmoothingMode
            PixelFormat = drawing_imaging.PixelFormat
            PrivateFontCollection = drawing_text.PrivateFontCollection
            TextRenderingHint = drawing_text.TextRenderingHint

            def track(resource: Any) -> Any:
                resources.append(resource)
                return resource

            spec = layout(self._scale)
            width, height = int(spec.window_width), int(spec.window_height)
            bitmap = track(Bitmap(width, height, PixelFormat.Format32bppPArgb))
            graphics = track(Graphics.FromImage(bitmap))
            graphics.SmoothingMode = SmoothingMode.AntiAlias
            graphics.Clear(Color.Transparent)

            def pill(x: float, y: float, w: float, radius: float) -> Any:
                path = track(GraphicsPath())
                diameter = radius * 2
                path.AddArc(x, y, diameter, diameter, 90, 180)
                path.AddArc(x + w - diameter, y, diameter, diameter, 270, 180)
                path.CloseFigure()
                return path

            pill_rect = spec.pill_rect
            px, py = pill_rect.left, pill_rect.top
            pw = pill_rect.right - px
            for i in range(10, 0, -1):
                grow = i * 1.1 * self._scale
                alpha = int(10 * (1 - i / 11))
                graphics.FillPath(
                    track(SolidBrush(Color.FromArgb(alpha + 4, 0, 0, 0))),
                    pill(
                        px - grow,
                        py - grow + 5 * self._scale,
                        pw + 2 * grow,
                        HUD_SPEC["radius"] * self._scale + grow,
                    ),
                )
            graphics.FillPath(
                track(SolidBrush(Color.FromArgb(242, 27, 22, 29))),
                pill(px, py, pw, HUD_SPEC["radius"] * self._scale),
            )
            graphics.DrawPath(
                track(Pen(Color.FromArgb(22, 255, 255, 255), self._scale)),
                pill(
                    px + 0.5 * self._scale,
                    py + 0.5 * self._scale,
                    pw - self._scale,
                    HUD_SPEC["radius"] * self._scale - 0.5 * self._scale,
                ),
            )

            cx, cy = spec.dot_center
            radius = spec.dot_radius
            rgb = status_color(self._status)
            dot = tuple(int(rgb[i : i + 2], 16) for i in (1, 3, 5))
            if self._status == "recording":
                phase = (time.monotonic() % 1.4) / 1.4
                pulse_radius = radius + self._scale * (2 + 6 * phase)
                graphics.DrawEllipse(
                    track(
                        Pen(Color.FromArgb(int(120 * (1 - phase)), *dot), self._scale)
                    ),
                    cx - pulse_radius,
                    cy - pulse_radius,
                    pulse_radius * 2,
                    pulse_radius * 2,
                )
            graphics.FillEllipse(
                track(SolidBrush(Color.FromArgb(255, *dot))),
                cx - radius,
                cy - radius,
                radius * 2,
                radius * 2,
            )

            font = self._font(PrivateFontCollection, FontFamily)
            graphics.TextRenderingHint = TextRenderingHint.AntiAliasGridFit
            label = STATUS_LABELS.get(self._status, "Ready")
            text_font = track(
                Font(
                    font,
                    HUD_SPEC["label_size"] * self._scale,
                    FontStyle.Regular,
                    GraphicsUnit.Pixel,
                )
            )
            available = spec.label_rect.right - spec.label_rect.left
            while label and graphics.MeasureString(label, text_font).Width > available:
                label = label[:-2] + "…" if len(label) > 1 else ""
            measured = graphics.MeasureString(label, text_font)
            graphics.DrawString(
                label,
                text_font,
                track(SolidBrush(Color.White)),
                spec.label_rect.left,
                cy - measured.Height / 2,
            )
            timer = self._timer.text
            timer_font = track(
                Font(
                    "Cascadia Mono",
                    12 * self._scale,
                    FontStyle.Regular,
                    GraphicsUnit.Pixel,
                )
            )
            timer_brush = track(SolidBrush(Color.FromArgb(179, 255, 255, 255)))
            graphics.DrawString(
                timer,
                timer_font,
                timer_brush,
                spec.timer_rect.left,
                cy - 7 * self._scale,
            )
            button = spec.cancel_rect
            bx, by = button.left + 14 * self._scale, button.top + 14 * self._scale
            if self._hover:
                graphics.FillEllipse(
                    track(SolidBrush(Color.FromArgb(26, 255, 255, 255))),
                    button.left,
                    button.top,
                    28 * self._scale,
                    28 * self._scale,
                )
            cross = track(
                Pen(
                    Color.White if self._hover else Color.FromArgb(179, 255, 255, 255),
                    1.5 * self._scale,
                )
            )
            cross.StartCap = LineCap.Round
            cross.EndCap = LineCap.Round
            graphics.DrawLine(
                cross,
                bx - 4 * self._scale,
                by - 4 * self._scale,
                bx + 4 * self._scale,
                by + 4 * self._scale,
            )
            graphics.DrawLine(
                cross,
                bx + 4 * self._scale,
                by - 4 * self._scale,
                bx - 4 * self._scale,
                by + 4 * self._scale,
            )
            self._push(hwnd, bitmap)
            self._last_draw = time.monotonic()
        except Exception:
            logger.warning("NATIVE_HUD_DRAW_FAILED")
        finally:
            for resource in reversed(resources):
                try:
                    resource.Dispose()
                except Exception:
                    logger.warning("NATIVE_HUD_RESOURCE_DISPOSE_FAILED")

    def _font(self, private_font_collection: Any, font_family_type: Any) -> Any:
        if getattr(self, "_font_family", None) is None:
            try:
                local = (
                    Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
                    / "WisprClone"
                    / "cache"
                    / "fonts"
                    / "geist.ttf"
                )
                local.parent.mkdir(parents=True, exist_ok=True)
                if not local.exists():
                    source = config.resource_root() / "web" / "assets" / "geist.ttf"
                    shutil.copyfile(source, local)
                collection = private_font_collection()
                collection.AddFontFile(str(local))
                families = cast(Any, list)(collection.Families)
                self._font_collection = collection
                self._font_family = next(
                    (family for family in families if family.Name == "Geist Medium"),
                    None,
                )
            except Exception:
                self._font_family = None
        if self._font_family is not None:
            return self._font_family
        return font_family_type("Segoe UI")

    def _push(self, hwnd: int, bitmap: Any) -> None:
        apis = self._apis
        if apis is None:
            return
        user32, gdi32, _ = apis
        screen = user32.GetDC(None)
        memory = gdi32.CreateCompatibleDC(screen)
        color = cast(Any, importlib.import_module("System.Drawing")).Color
        hbitmap = bitmap.GetHbitmap(color.FromArgb(0))
        hbitmap_handle = ctypes.c_void_p(hbitmap.ToInt64())
        old = gdi32.SelectObject(memory, hbitmap_handle)
        position = wintypes.POINT(*self._window_position)
        size = wintypes.SIZE(bitmap.Width, bitmap.Height)
        source = wintypes.POINT(0, 0)
        blend = _BLENDFUNCTION(0, 0, 255, 1)
        ok = user32.UpdateLayeredWindow(
            hwnd,
            screen,
            ctypes.byref(position),
            ctypes.byref(size),
            memory,
            ctypes.byref(source),
            0,
            ctypes.byref(blend),
            _ULW_ALPHA,
        )
        gdi32.SelectObject(memory, old)
        gdi32.DeleteObject(hbitmap_handle)
        gdi32.DeleteDC(memory)
        user32.ReleaseDC(None, screen)
        if not ok:
            logger.warning("NATIVE_HUD_LAYER_UPDATE_FAILED")
        else:
            self.frames_drawn += 1


def _dispatch_window_message(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
    instance: NativeHud | None
    with _window_lock:
        instance = _windows.get(int(hwnd))
        if instance is None and msg == _WM_NCCREATE:
            instance = _pending_windows.get(threading.get_native_id())
            if instance is not None:
                _windows[int(hwnd)] = instance
    if instance is None:
        return 0
    try:
        apis = instance._apis
        if apis is None:
            return 0
        user32 = apis[0]
        if msg == _WM_MOUSEACTIVATE:
            return _MA_NOACTIVATE
        if msg == _WM_NCHITTEST:
            sx = ctypes.c_short(lparam & 0xFFFF).value
            sy = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            x, y = sx - instance._window_position[0], sy - instance._window_position[1]
            hit = classify_hit(layout(instance._scale), x, y)
            return _HTTRANSPARENT if hit == "transparent" else _HTCLIENT
        if msg == _WM_MOUSEMOVE:
            tracking = _TRACKMOUSEEVENT(
                ctypes.sizeof(_TRACKMOUSEEVENT), _TME_LEAVE, hwnd, 0
            )
            user32.TrackMouseEvent(ctypes.byref(tracking))
            x, y = (
                ctypes.c_short(lparam & 0xFFFF).value,
                ctypes.c_short((lparam >> 16) & 0xFFFF).value,
            )
            button = layout(instance._scale).cancel_rect
            hover = button.left <= x < button.right and button.top <= y < button.bottom
            if hover != instance._hover:
                instance._hover = hover
                instance._draw(hwnd)
            return 0
        if msg == _WM_MOUSELEAVE:
            if instance._hover:
                instance._hover = False
                instance._draw(hwnd)
            return 0
        if msg == _WM_LBUTTONUP:
            x, y = (
                ctypes.c_short(lparam & 0xFFFF).value,
                ctypes.c_short((lparam >> 16) & 0xFFFF).value,
            )
            if (
                classify_hit(layout(instance._scale), x, y) == "cancel"
                and instance._on_cancel is not None
            ):
                try:
                    threading.Thread(
                        target=instance._on_cancel, name="wispr-hud-cancel", daemon=True
                    ).start()
                except Exception:
                    logger.warning("NATIVE_HUD_CANCEL_FAILED")
            return 0
        if msg == _WM_COMMAND:
            instance._drain_commands(hwnd)
            return 0
        if msg == _WM_TIMER:
            instance._animate(hwnd)
            return 0
        if msg == _WM_DESTROY:
            user32.KillTimer(hwnd, _TIMER_ID)
            with _window_lock:
                _windows.pop(int(hwnd), None)
            user32.PostQuitMessage(0)
            return 0
        return int(user32.DefWindowProcW(hwnd, msg, wparam, lparam))
    except Exception:
        logger.warning("NATIVE_HUD_WINDOW_FAILED")
        apis = instance._apis
        if apis is not None:
            return int(apis[0].DefWindowProcW(hwnd, msg, wparam, lparam))
        return 0
