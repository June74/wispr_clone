"""Phase -1.3 (G3) and -1.4 (G4) disposable desktop experiment. Not product code.

Run with Windows Python 3.12 in the experiment venv, from a PowerShell window:

    python g34_desktop.py

G3: does a pywebview HUD show/update/hide without taking focus from the app you type in?
    Variant A = pywebview show()/hide(); variant B = Win32 SW_SHOWNOACTIVATE + tool-window styles.
    Foreground focus is sampled every 20 ms; you also confirm your typing was not interrupted.
G4: clipboard exclusion from Win+V history (with a normal-copy control), clipboard restore,
    destination snapshot/verify, and paste vs Unicode SendInput into apps you choose.
    Text sent is synthetic. Enter is never pressed. Nothing is sent if the destination changed.

Saves results to %LOCALAPPDATA%\\wispr_clone\\experiments\\g2\\g34_results.json.
Window titles are stored only as short SHA-256 hashes.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import threading
import time
from ctypes import wintypes

import win32clipboard
import win32con
import win32gui
import win32process

OUT = os.path.join(os.environ["LOCALAPPDATA"], "wispr_clone", "experiments", "g2", "g34_results.json")
HUD_TITLE = "WC-G3-HUD-TEST"
RESULTS: dict = {"g3": {}, "g4": {}}

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


# ---------- helpers ----------

def save() -> None:
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, indent=2, ensure_ascii=False)


def ask(q: str) -> bool | None:
    """y / n / s(kip). Returns None for skip."""
    while True:
        a = input(f"  >> {q} [y/n/s=skip] ").strip().lower()
        if a in ("y", "n", "s"):
            return {"y": True, "n": False, "s": None}[a]


def countdown(n: int, what: str) -> None:
    for i in range(n, 0, -1):
        print(f"\r  {what} in {i}s ... ", end="", flush=True)
        time.sleep(1)
    print("\r" + " " * 60 + "\r", end="")


def exe_of(hwnd: int) -> str:
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return f"pid{pid}(no access)"
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        ok = kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
        kernel32.CloseHandle(h)
        return os.path.basename(buf.value) if ok else f"pid{pid}"
    except Exception as exc:
        return f"?({type(exc).__name__})"


def snapshot(hwnd: int | None = None) -> dict:
    hwnd = hwnd or win32gui.GetForegroundWindow()
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    title = win32gui.GetWindowText(hwnd)
    return {"hwnd": hwnd, "pid": pid, "exe": exe_of(hwnd), "class": win32gui.GetClassName(hwnd),
            "title_hash": hashlib.sha256(title.encode()).hexdigest()[:12]}


def same_destination(a: dict, b: dict) -> bool:
    return a["hwnd"] == b["hwnd"] and a["pid"] == b["pid"]


# ---------- SendInput ----------

ULONG_PTR = wintypes.WPARAM


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT


def _key(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    i = INPUT()
    i.type = 1  # INPUT_KEYBOARD
    i.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    return i


def send(inputs: list[INPUT]) -> tuple[int, int]:
    arr = (INPUT * len(inputs))(*inputs)
    n = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    return n, len(inputs)


def send_ctrl_v() -> tuple[int, int]:
    up = 2  # KEYEVENTF_KEYUP
    return send([_key(0x11), _key(0x56), _key(0x56, flags=up), _key(0x11, flags=up)])


def send_unicode(text: str) -> tuple[int, int]:
    assert "\n" not in text and "\r" not in text  # never press Enter
    units = text.encode("utf-16-le")
    seq = []
    for k in range(0, len(units), 2):
        cu = int.from_bytes(units[k:k + 2], "little")
        seq += [_key(scan=cu, flags=4), _key(scan=cu, flags=4 | 2)]  # KEYEVENTF_UNICODE
    return send(seq)


# ---------- clipboard ----------

EXCL = {name: win32clipboard.RegisterClipboardFormat(name) for name in (
    "ExcludeClipboardContentFromMonitorProcessing", "CanIncludeInClipboardHistory", "CanUploadToCloudClipboard")}


def _open() -> None:
    for _ in range(40):
        try:
            win32clipboard.OpenClipboard()
            return
        except Exception:
            time.sleep(0.05)
    raise RuntimeError("clipboard busy")


def clip_read_text() -> str | None:
    _open()
    try:
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
        return None
    finally:
        win32clipboard.CloseClipboard()


def clip_formats() -> list[int]:
    _open()
    try:
        fmts, f = [], 0
        while True:
            f = win32clipboard.EnumClipboardFormats(f)
            if not f:
                return fmts
            fmts.append(f)
    finally:
        win32clipboard.CloseClipboard()


def clip_write(text: str, exclude: bool) -> None:
    _open()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        if exclude:
            win32clipboard.SetClipboardData(EXCL["ExcludeClipboardContentFromMonitorProcessing"], b"\x00\x00\x00\x00")
            win32clipboard.SetClipboardData(EXCL["CanIncludeInClipboardHistory"], b"\x00\x00\x00\x00")
            win32clipboard.SetClipboardData(EXCL["CanUploadToCloudClipboard"], b"\x00\x00\x00\x00")
    finally:
        win32clipboard.CloseClipboard()


# ---------- G3 ----------

HUD_HTML = """<!doctype html><html><body style="margin:0;background:#1b191e;font:14px Segoe UI;color:#fff;
display:flex;align-items:center;gap:10px;padding:0 14px;height:100vh;overflow:hidden">
<div id="bar" style="width:36px;height:14px;border-radius:7px;background:#317356"></div>
<div id="t">HUD test</div>
<script>
const C=["#317356","#426c9b","#946414","#b3464c"];
function setState(i){document.getElementById('bar').style.background=C[i%4];
document.getElementById('t').textContent='HUD update '+i;return i;}
</script></body></html>"""


def g3_thread(win) -> None:
    try:
        win.events.loaded.wait(15)
        hwnd = win32gui.FindWindow(None, HUD_TITLE)
        RESULTS["g3"]["hud_hwnd_found"] = bool(hwnd)
        RESULTS["g3"]["hud_bridge_api"] = win.evaluate_js(
            "(window.pywebview && window.pywebview.api) ? Object.keys(window.pywebview.api).join(',') : ''")
        RESULTS["g3"]["runs"] = []

        def show_a():
            win.show()

        def hide_a():
            win.hide()

        def show_b():
            win32gui.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
            win32gui.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0040)

        def hide_b():
            win32gui.ShowWindow(hwnd, 0)

        variants = [("A_pywebview_show", show_a, hide_a), ("B_win32_noactivate", show_b, hide_b)]
        for vname, show, hide in variants:
            if vname.startswith("B"):
                ex = win32gui.GetWindowLong(hwnd, -20)
                win32gui.SetWindowLong(hwnd, -20, ex | 0x08000000 | 0x00000080 | 0x00000008)
            for target in ("Notepad", "VS Code"):
                print(f"\n[G3 · variant {vname[0]} · {target}]")
                print(f"  Press Enter here, then within 5 s click into {target} and KEEP TYPING")
                print("  (any letters) until this window says STOP (about 10 s).")
                if input("  Press Enter to start, or type s + Enter to skip: ").strip().lower() == "s":
                    continue
                countdown(5, f"Click into {target} and start typing")
                fg0 = snapshot()
                polls: list[int] = []
                stop = threading.Event()

                def poll() -> None:
                    while not stop.is_set():
                        polls.append(win32gui.GetForegroundWindow())
                        time.sleep(0.02)

                pt = threading.Thread(target=poll)
                pt.start()
                t0 = time.time()
                for cycle in range(8):
                    show()
                    for i in range(5):
                        win.evaluate_js(f"setState({cycle * 5 + i})")
                        time.sleep(0.1)
                    hide()
                    time.sleep(0.4)
                stop.set()
                pt.join()
                print("\a  *** STOP typing. Click back into this window. ***")
                run = {
                    "variant": vname, "target": target, "target_exe": fg0["exe"], "duration_s": round(time.time() - t0, 1),
                    "polls": len(polls),
                    "polls_foreground_changed": sum(1 for h in polls if h != fg0["hwnd"]),
                    "polls_hud_was_foreground": sum(1 for h in polls if h == hwnd),
                    "target_looks_wrong": fg0["exe"].lower() in ("windowsterminal.exe", "powershell.exe", "conhost.exe", "python.exe"),
                }
                run["user_saw_hud"] = ask("Did you see the small HUD appear and change colour?")
                run["user_typing_uninterrupted"] = ask(f"Did ALL your typing stay in {target}, with no missing letters?")
                RESULTS["g3"]["runs"].append(run)
                save()
    except Exception as exc:
        RESULTS["g3"]["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        save()
        win.destroy()


def run_g3() -> None:
    import webview  # only G3 needs it; it sets COM up in a way UI Automation cannot share
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    win = webview.create_window(HUD_TITLE, html=HUD_HTML, width=260, height=52,
                                x=(sw - 260) // 2, y=sh - 160, frameless=True, on_top=True,
                                focus=False, hidden=True, easy_drag=False, shadow=False)
    webview.start(g3_thread, (win,))


# ---------- G4 ----------

class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def idle_ms() -> int:
    lii = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    user32.GetLastInputInfo(ctypes.byref(lii))
    return (kernel32.GetTickCount() - lii.dwTime) & 0xFFFFFFFF


def last_input_tick() -> int:
    lii = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    user32.GetLastInputInfo(ctypes.byref(lii))
    return lii.dwTime


BROWSERS = ("chrome.exe", "msedge.exe", "brave.exe", "firefox.exe")


def uia():
    import uiautomation as auto  # imported lazily: only G4 needs it
    return auto


def rid(ctrl) -> tuple | None:
    try:
        return tuple(ctrl.Element.GetRuntimeId())
    except Exception:
        return None


def tabs_of(hwnd: int) -> list:
    auto = uia()
    out = []
    for c, _d in auto.WalkControl(auto.ControlFromHandle(hwnd), maxDepth=25):
        if c.ControlTypeName == "TabItemControl":
            out.append(c)
    return out


def selected_tab_rid(hwnd: int) -> tuple | None:
    for t in tabs_of(hwnd):
        try:
            if t.GetSelectionItemPattern().IsSelected:
                return rid(t)
        except Exception:
            pass
    return None


def select_tab(hwnd: int, tab_rid: tuple) -> bool:
    for t in tabs_of(hwnd):
        if rid(t) == tab_rid:
            try:
                t.GetSelectionItemPattern().Select()
                time.sleep(0.15)
                return True
            except Exception:
                return False
    return False


def field_on_screen() -> bool:
    f = uia().GetFocusedControl()
    try:
        r = f.BoundingRectangle
        return bool(f) and not f.IsOffscreen and r.width() > 0 and r.height() > 0
    except Exception:
        return False


def focused_rid() -> tuple | None:
    f = uia().GetFocusedControl()
    return rid(f) if f else None


def restore_focus(hwnd: int, field_rid: tuple, limit_s: float = 3.0) -> str:
    if focused_rid() == field_rid:
        return "already"
    auto = uia()
    t0 = time.time()
    for c, _d in auto.WalkControl(auto.ControlFromHandle(hwnd), maxDepth=60):
        if time.time() - t0 > limit_s:
            return "timeout"
        if rid(c) == field_rid:
            try:
                c.SetFocus()
                time.sleep(0.1)
            except Exception:
                return "setfocus_error"
            return "restored" if focused_rid() == field_rid else "setfocus_no_effect"
    return "not_found"


def bring_forward(hwnd: int) -> str:
    """Try progressively stronger ways to make hwnd the foreground window; report which worked."""
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.05)
    if win32gui.GetForegroundWindow() == hwnd:
        return "plain"
    send([_key(0x07), _key(0x07, flags=2)])  # unassigned virtual key: counts as our input, no side effects
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.05)
    if win32gui.GetForegroundWindow() == hwnd:
        return "after_null_key"
    fg = win32gui.GetForegroundWindow()
    fg_thread = user32.GetWindowThreadProcessId(fg, None)
    me = kernel32.GetCurrentThreadId()
    user32.AttachThreadInput(me, fg_thread, True)
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        user32.AttachThreadInput(me, fg_thread, False)
    time.sleep(0.05)
    return "attach_thread_input" if win32gui.GetForegroundWindow() == hwnd else "failed"


SCENARIOS = [
    ("devin_app_switch", "the Devin desktop chat box", "a DIFFERENT app, e.g. File Explorer or Notepad", "jump"),
    ("devin_internal_switch", "the Devin desktop chat box (optional)", "a DIFFERENT session/panel INSIDE Devin", "jump"),
    ("notepad", "an empty Notepad document", "a DIFFERENT app", "jump"),
    ("vscode", "an empty VS Code Untitled file", "a DIFFERENT app", "jump"),
    ("browser_tab_switch", "any text box in a Chrome/Edge tab (optional)", "ANOTHER TAB in the same browser window", "jump"),
    ("devin_return", "the Devin desktop chat box", "a DIFFERENT app, type a little, then COME BACK to the Devin chat box yourself", "return"),
]
IDLE_JUMP_MS, RETURN_SETTLE_MS, WAIT_LIMIT_S = 1000, 300, 45


def hybrid_scenario(key: str, target: str, away: str, mode: str, n: int) -> dict:
    rec: dict = {"scenario": key, "mode": mode}
    print(f"\n[G4 hybrid · {key}]  Target: {target}")
    if input("  Press Enter to run, or s + Enter to skip: ").strip().lower() == "s":
        return {"scenario": key, "skipped": True}
    countdown(5, "Click INTO the target text field (put the cursor there)")
    t_snap = snapshot()
    is_browser = t_snap["exe"].lower() in BROWSERS
    dest = {"hwnd": t_snap["hwnd"], "pid": t_snap["pid"], "field": focused_rid(),
            "tab": selected_tab_rid(t_snap["hwnd"]) if is_browser else None}
    rec["target"] = {"exe": t_snap["exe"], "browser": is_browser, "field_captured": dest["field"] is not None,
                     "tab_captured": dest["tab"] is not None}
    print("\a  Captured. Now switch to " + away + ".")
    if mode == "jump":
        print("  Type a few letters there for ~3 s, then take your HANDS OFF keyboard and mouse.")
    t_start = time.time()
    active_s, jumped, text = 0.0, False, f" [WC hybrid test {n}]"
    while time.time() - t_start < WAIT_LIMIT_S:
        time.sleep(0.05)
        fg = win32gui.GetForegroundWindow()
        away_now = fg != dest["hwnd"] or (is_browser and selected_tab_rid(fg) != dest["tab"])
        if time.time() - t_start < 3.0:
            continue  # give the user time to switch away first
        idle = idle_ms()
        if mode == "return":
            if not away_now and idle >= RETURN_SETTLE_MS and focused_rid() == dest["field"] and field_on_screen():
                rec["returned_after_s"] = round(time.time() - t_start, 1)
                rec["dispatch"] = send_unicode(text)
                break
            continue
        if idle < IDLE_JUMP_MS:
            active_s += 0.05
            continue
        # ---- idle jump ----
        jumped = True
        prev = win32gui.GetForegroundWindow()
        prev_is_browser = exe_of(prev).lower() in BROWSERS
        prev_tab = selected_tab_rid(prev) if prev_is_browser else None
        rec["waited_while_user_active_s"] = round(active_s, 1)
        rec["idle_ms_at_jump"] = idle
        t0 = time.perf_counter()
        rec["bring_forward"] = bring_forward(dest["hwnd"])
        tick_after_forward = last_input_tick()
        if is_browser:
            rec["tab_reselected"] = select_tab(dest["hwnd"], dest["tab"]) if dest["tab"] else "no tab captured"
        rec["field_focus"] = restore_focus(dest["hwnd"], dest["field"]) if dest["field"] else "no field captured"
        rec["field_on_screen"] = field_on_screen()
        verified = (win32gui.GetForegroundWindow() == dest["hwnd"] and focused_rid() == dest["field"]
                    and rec["field_on_screen"])
        user_input_during_jump = last_input_tick() != tick_after_forward
        rec["verified_before_dispatch"] = verified
        rec["user_input_during_jump"] = user_input_during_jump
        if verified and not user_input_during_jump:
            rec["dispatch"] = send_unicode(text)
            time.sleep(0.15)
        else:
            rec["dispatch"] = "aborted (not verified or user input)"
        # ---- return the user ----
        if prev == dest["hwnd"] and prev_tab:
            rec["restore"] = "tab:" + str(select_tab(prev, prev_tab))
        else:
            rec["restore"] = "window:" + bring_forward(prev)
            if prev_tab:
                select_tab(prev, prev_tab)
        rec["jump_ms"] = round((time.perf_counter() - t0) * 1000)
        now = win32gui.GetForegroundWindow()
        rec["user_back_where_they_were"] = now == prev and (not prev_tab or selected_tab_rid(now) == prev_tab)
        break
    else:
        rec["timed_out"] = True
    rec["jumped"] = jumped
    print("\a  Done. Click back into this script window.")
    rec["user_text_in_original_field_once"] = ask(f"Did '{text.strip()}' appear exactly ONCE in the ORIGINAL field?")
    rec["user_nothing_in_other_window"] = ask("Was NOTHING extra typed into the window/tab you switched to?")
    if mode == "jump":
        rec["user_returned_to_their_window"] = ask("After the flash, were you back in the window/tab you had switched to?")
    print("  (Delete the test text from the original field; do NOT press Enter in a chat box.)")
    return rec


def run_g4() -> None:
    g4 = RESULTS["g4"]
    print("\n================ G4 part 1: clipboard privacy ================")
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Clipboard") as k:
            on = winreg.QueryValueEx(k, "EnableClipboardHistory")[0] == 1
    except OSError:
        on = False
    g4["clipboard_history_enabled"] = on
    print(f"  Clipboard history is {'ON' if on else 'OFF'} (Settings > System > Clipboard).")
    if input("  Press Enter to run the Win+V check, or s + Enter to skip: ").strip().lower() == "s":
        g4["winv_check"] = "skipped"
        save()
        return run_g4_hybrid()
    prev = clip_read_text()
    g4["user_clipboard_was_text"] = prev is not None
    tag = str(int(time.time()))[-5:]
    clip_write(f"WC-CONTROL-{tag} (normal copy: SHOULD appear in Win+V)", exclude=False)
    time.sleep(1.5)
    clip_write(f"WC-EXCLUDED-{tag} (flagged: should NOT appear in Win+V)", exclude=True)
    fm = clip_formats()
    g4["exclusion_formats_present"] = {k: (v in fm) for k, v in EXCL.items()}
    print(f"  Wrote a normal CONTROL entry and a flagged EXCLUDED entry (tag {tag}).")
    print("  Now press Win+V to open clipboard history, look, then press Esc.")
    g4["history_on_control_visible"] = ask(f"Do you see WC-CONTROL-{tag} in the Win+V list?")
    g4["excluded_visible_in_history"] = ask(f"Do you see WC-EXCLUDED-{tag} ANYWHERE in the Win+V list?")
    if prev is not None:
        clip_write(prev, exclude=False)
        g4["restore_text_ok"] = clip_read_text() == prev
    print(f"  Clipboard restored. You can delete WC-CONTROL-{tag} from Win+V afterwards.")
    save()
    run_g4_hybrid()


def run_g4_hybrid() -> None:
    g4 = RESULTS["g4"]

    print("\n================ G4 part 2: hybrid delivery ================")
    print("  Each scenario: put your cursor in the target field, switch away when told,")
    print("  then keep your hands off. The app should bring the target back, type a test")
    print("  text there once, and return you. Enter is never pressed.")
    g4["hybrid"] = []
    for n, (key, target, away, mode) in enumerate(SCENARIOS, 1):
        g4["hybrid"].append(hybrid_scenario(key, target, away, mode, n))
        save()


def main() -> int:
    import sys
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else "all"
    if os.path.exists(OUT):
        try:
            RESULTS.update(json.load(open(OUT, encoding="utf-8")))
        except Exception:
            pass
    print(__doc__.split("Saves results")[0])
    if only in ("all", "g3"):
        print("Before G3: open Notepad (empty) and VS Code (Untitled file).")
        input("Press Enter to begin G3 (HUD focus test)... ")
        run_g3()
        save()
    if only in ("all", "g4"):
        print("Before G4: open Devin desktop (chat box), Notepad (empty), VS Code (Untitled).")
        print("Optional: a Chrome/Edge window with two tabs, one containing a text box.")
        input("Press Enter to begin G4 (clipboard + hybrid delivery)... ")
        run_g4()
        save()
    print(f"\nAll done. Results saved to:\n  {OUT}\nTell Claude you're finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
