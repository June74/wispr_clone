"""G4b desktop check (disposable, not product code): Korean IME detection, Unicode typing vs
exclusion-flagged paste in Notepad, and UI Automation read-back in a Devin field.

Run with Windows Python that has pywin32 + uiautomation (the g2 experiment venv):
    python g4b_ime_check.py OUT.json

The user is guided by top-most message boxes. The script never presses Enter, never prints the
contents of any field (only whether the test phrase appeared exactly once more), and restores the
clipboard's text afterwards.
"""

from __future__ import annotations

import ctypes
import json
import sys
import time
from ctypes import wintypes

import uiautomation as auto
import win32clipboard
import win32con

user32 = ctypes.WinDLL("user32", use_last_error=True)
imm32 = ctypes.WinDLL("imm32")

PHRASE = "wispr check 한글 123"
MB_OK, MB_YESNO, IDYES = 0x0, 0x4, 6
MB_FLAGS = 0x40 | 0x40000 | 0x1000  # information icon, top-most, system-modal
WM_IME_CONTROL, IMC_GETCONVERSIONMODE, IMC_GETOPENSTATUS = 0x0283, 0x0001, 0x0005
IME_CMODE_NATIVE = 0x0001  # Hangul input when set


def box(text: str, yes_no: bool = False) -> bool:
    r = user32.MessageBoxW(0, text, "Wispr Clone desktop check", (MB_YESNO if yes_no else MB_OK) | MB_FLAGS)
    return r == IDYES


def wait(seconds: float) -> None:
    time.sleep(seconds)


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD), ("hwndActive", wintypes.HWND),
                ("hwndFocus", wintypes.HWND), ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND), ("rcCaret", wintypes.RECT)]


def foreground_info() -> dict:
    hwnd = user32.GetForegroundWindow()
    pid = wintypes.DWORD()
    tid = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    gti = GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
    user32.GetGUIThreadInfo(tid, ctypes.byref(gti))
    focus = gti.hwndFocus or hwnd
    layout = user32.GetKeyboardLayout(tid) & 0xFFFF
    ime_wnd = imm32.ImmGetDefaultIMEWnd(focus)
    open_status = conv = None
    if ime_wnd:
        open_status = user32.SendMessageW(ime_wnd, WM_IME_CONTROL, IMC_GETOPENSTATUS, 0)
        conv = user32.SendMessageW(ime_wnd, WM_IME_CONTROL, IMC_GETCONVERSIONMODE, 0)
    ctrl = auto.GetFocusedControl()
    return {
        "exe": exe_name(pid.value),
        "langid": hex(layout),
        "korean_layout": layout == 0x0412,
        "ime_open": None if open_status is None else bool(open_status),
        "hangul_mode": None if conv is None else bool(conv & IME_CMODE_NATIVE),
        "focused_control": getattr(ctrl, "ControlTypeName", None),
    }


def exe_name(pid: int) -> str:
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    buf = ctypes.create_unicode_buffer(1024)
    size = wintypes.DWORD(1024)
    ok = h and ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
    if h:
        ctypes.windll.kernel32.CloseHandle(h)
    return buf.value.rsplit("\\", 1)[-1] if ok else "?"


def field_text() -> str | None:
    ctrl = auto.GetFocusedControl()
    if ctrl is None:
        return None
    for getter in (lambda c: c.GetValuePattern().Value, lambda c: c.GetTextPattern().DocumentRange.GetText(-1)):
        try:
            value = getter(ctrl)
            if isinstance(value, str):
                return value
        except Exception:
            continue
    return None


# ---- input ----
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _key(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    i = INPUT(type=1)
    i.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    return i


def send(inputs: list[INPUT]) -> int:
    arr = (INPUT * len(inputs))(*inputs)
    return user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def type_unicode(text: str) -> int:
    events: list[INPUT] = []
    raw = text.encode("utf-16-le")
    codes = [int.from_bytes(raw[i:i + 2], "little") for i in range(0, len(raw), 2)]
    for code in codes:
        events += [_key(scan=code, flags=0x0004), _key(scan=code, flags=0x0004 | 0x0002)]
    return send(events)


def paste_excluded(text: str) -> int:
    formats = [win32clipboard.RegisterClipboardFormat(n) for n in (
        "ExcludeClipboardContentFromMonitorProcessing", "CanIncludeInClipboardHistory", "CanUploadToCloudClipboard")]
    saved = clip_text()
    clip_set(text, formats)
    n = send([_key(0x11), _key(0x56), _key(0x56, flags=0x0002), _key(0x11, flags=0x0002)])
    time.sleep(0.4)
    clip_set(saved, formats) if saved is not None else clip_clear()
    return n


def clip_open() -> None:
    for _ in range(20):
        try:
            win32clipboard.OpenClipboard()
            return
        except Exception:
            time.sleep(0.05)
    raise RuntimeError("clipboard busy")


def clip_text() -> str | None:
    clip_open()
    try:
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
        return None
    finally:
        win32clipboard.CloseClipboard()


def clip_set(text: str, exclusion_formats: list[int]) -> None:
    clip_open()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        for f in exclusion_formats:
            win32clipboard.SetClipboardData(f, b"\x00\x00\x00\x00")
    finally:
        win32clipboard.CloseClipboard()


def clip_clear() -> None:
    clip_open()
    try:
        win32clipboard.EmptyClipboard()
    finally:
        win32clipboard.CloseClipboard()


def insert_step(name: str, how: str) -> dict:
    before = field_text()
    info = foreground_info()
    sent = type_unicode(PHRASE) if how == "unicode" else paste_excluded(PHRASE)
    time.sleep(0.6)
    after = field_text()
    readable = before is not None and after is not None
    appeared_once = readable and after.count(PHRASE) == before.count(PHRASE) + 1
    looked_right = box(f"{name}\n\nDoes the field now show exactly:\n\n    {PHRASE}\n\n(Yes / No)", yes_no=True)
    return {"step": name, "method": how, "events_accepted": sent, "target": info,
            "read_back_available": readable, "read_back_exact_once": appeared_once,
            "user_saw_exact_text": looked_right}


def main(out: str) -> None:
    results: dict = {"phrase_chars": len(PHRASE), "steps": []}
    box("Desktop check (about 5 minutes).\n\nPrepare: open Notepad with an empty document.\n"
        "Each step: read the box, click OK, then within 5 seconds click where it says.\nNothing is ever sent or submitted.")

    box("Step 1 of 6 — IME detection (Korean mode)\n\nAfter OK: click into Notepad and switch your IME to 한 (Korean) mode.")
    wait(6); results["steps"].append({"step": "ime_korean_mode", "target": foreground_info()})

    box("Step 2 of 6 — Notepad, Korean mode, TYPING\n\nAfter OK: click at the end of the Notepad text (IME still 한).")
    wait(5); results["steps"].append(insert_step("Notepad, Korean mode, typing", "unicode"))

    box("Step 3 of 6 — Notepad, Korean mode, PASTE\n\nAfter OK: click at the end of the Notepad text (IME still 한).")
    wait(5); results["steps"].append(insert_step("Notepad, Korean mode, paste", "paste"))

    box("Step 4 of 6 — IME detection (English mode)\n\nAfter OK: click into Notepad and switch your IME to A (English) mode.")
    wait(6); results["steps"].append({"step": "ime_english_mode", "target": foreground_info()})

    box("Step 5 of 6 — Notepad, English mode, TYPING\n\nAfter OK: click at the end of the Notepad text (IME in A mode).")
    wait(5); results["steps"].append(insert_step("Notepad, English mode, typing", "unicode"))

    box("Step 6 of 6 — Devin read-back, PASTE\n\nAfter OK: click into a Devin message box (do NOT press Enter).\n"
        "Afterwards delete the test text from that box yourself.")
    wait(5); results["steps"].append(insert_step("Devin message box, paste", "paste"))

    box("Done. Please delete the test text from the Devin box.\nYou can close Notepad without saving.")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(sys.argv[1])
