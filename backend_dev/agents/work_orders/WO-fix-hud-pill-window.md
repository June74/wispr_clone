# WO-fix-hud-pill-window — HUD bar is cut off and sits in a grey box (user-reported)

```text
Symptom: the HUD pill is cut off on the left, and a light-grey rectangle surrounds it.
Root cause (measured on the real PC with pywebview 6.2.1, WebView2, 96 dpi):
  A. CSS: `.pill.is-open { transform: translate(-50%,0) }` (2 classes) beats
     `.hud-pill { transform:none }` (1 class). The pill is shifted left by half its width.
  B. Size: resizable=False → FixedSingle border; frameless then removes the border but keeps the
     client size. The requested 240x56 became 224x17, then min_size (default 200x100) forced
     224x100. The label "Waiting for destination" makes the pill 271 px wide.
  C. Grey box: WebView2 transparency is not see-through on Windows. The transparent WebView shows
     the Form's BackColor (#F0F0F0), and a TransparencyKey color key does not apply to WebView2's
     composited content. Also, pywebview's transparent path calls form.Show()+Activate() on every
     navigation start, which is a focus-steal risk.
Verified fix (real-PC screenshot): an opaque window exactly the pill size (280x44 logical),
  resized after `shown`, plus SetWindowRgn(CreateRoundRectRgn(0,0,w+1,h+1,h,h)).
  Result: the full pill, with nothing around it.
Branch / worktree: fix/hud-pill-window / ~/projects/wc-hud
Writable: Luna: src/wispr_clone/ui/overlay.py, src/wispr_clone/ui/win_region.py (new),
                web/hud.html, web/styles.css (HUD rules only)
          Sol:  tests/unit/ui/test_overlay.py (new), tests/fakes/webview.py (mirror the real
                signature only), web/tests/hud_layout.test.mjs (new),
                tests/integration/test_real_hud_window.py (new; WISPR_REAL_GUI=1 only)
```

## Rules

1. `open_hud` creates the window with:
   - `transparent=False`, `background_color="#1b161d"` (the pill color, hsl(280 12% 10%));
   - `min_size=(1, 1)`, `width=HUD_WIDTH=280`, `height=HUD_HEIGHT=44`;
   - frameless, on_top, focus=False, shadow=False, hidden=True, js_api=None (as now);
   - x/y computed from the (0,0) screen with the new size, placed 48 px above the bottom.
2. It subscribes to `window.events.shown`. The handler never raises: it logs a code-only warning
   and continues.
   - It calls `window.resize(HUD_WIDTH, HUD_HEIGHT)`.
   - Then, on Windows only, it calls `win_region.apply_pill_region(title)`.
3. `win_region.apply_pill_region(title) -> bool`:
   - uses only ctypes and user32/gdi32;
   - finds the hwnd with FindWindowW(None, title); the HUD title is unique: "Wispr Clone HUD";
   - reads the physical size with GetWindowRect;
   - applies SetWindowRgn(hwnd, CreateRoundRectRgn(0, 0, w+1, h+1, h, h), True);
   - calls DeleteObject on the region only if SetWindowRgn fails;
   - returns False (no raise) if the window isn't found or on a non-Windows platform.
4. CSS/HTML:
   - hud.html gets `<html class="hud-root">`;
   - `.hud-root, .hud-root body` get background #1b161d;
   - `.pill.hud-pill` overrides `.pill.is-open` with:
     transform:none; margin:0; box-shadow:none; width:100vw; height:100vh;
   - `.hud-pill .pill-label` gets `min-width:0; overflow:hidden; text-overflow:ellipsis;
     white-space:nowrap`;
   - the main app's `.pill` is unchanged.
5. There are no screenshots in tests. Screen capture could record user content, which is a
   privacy risk.

## Tests (Sol)

| ID | Assertion |
|---|---|
| T-UI-008 | open_hud passes the rule-1 arguments to create_window (fake webview) and places the window at x = sx + (sw-280)//2, y = sy + sh - 44 - 48 |
| T-UI-009 | The shown handler calls resize(280, 44) and then apply_pill_region("Wispr Clone HUD") (monkeypatched). If either raises, the handler does not raise |
| T-UI-010 | apply_pill_region returns False on non-Windows, and when FindWindowW returns 0 (fake ctypes seam) |
| T-WEB-013 | styles.css has a `.pill.hud-pill` rule with transform:none, margin 0, box-shadow none, 100vw/100vh; `.hud-root` has background #1b161d; hud.html has class hud-root |
| T-UI-011 (real, WISPR_REAL_GUI=1, win32) | Start the real webview with open_hud; after shown, show the HUD. GetWindowRect size = round(280*s) x round(44*s), where s = GetDpiForWindow/96. GetWindowRgn(hwnd, CreateRectRgn(0,0,0,0)) returns COMPLEXREGION (3). Then destroy and exit within 15 s |

---

## Revision 2 (after real-PC verification). Supersedes rules 2, 3, 4 (radius) and T-UI-009..011

Measured on the real PC (pixel samples over a red, on-top backdrop; no user content captured):
- **SetWindowRgn doesn't work.** It clips the page, but WebView2's own backing layer still paints
  rgb(32,32,32) in the cut-away corners.
- **DWM rounding works.** DwmSetWindowAttribute(hwnd, 33 = DWMWA_WINDOW_CORNER_PREFERENCE,
  2 = DWMWCP_ROUND) clips cleanly, with anti-aliased corners of about 8 px.
- **Focus steal (new, critical).** pywebview `window.show()` calls `Form.Activate()`, and WinForms
  `Visible=True` uses SW_SHOW. In both cases the HUD became the foreground window, so dictated text
  would paste into the HUD.
- **Native show without activation breaks rendering.** SetWindowPos(SWP_SHOWWINDOW|NOACTIVATE) on a
  WinForms-hidden form leaves WebView2 blank.
- **WinForms `Opacity` resets styles.** Changing it rewrites the extended style and drops NOACTIVATE.
- **Verified recipe.** A native layered alpha on a WinForms-visible form renders correctly, keeps
  the foreground unchanged on show, and keeps its styles.

R2-1. `open_hud` returns a `HudHandle`.
- It wraps the pywebview window. `__getattr__` delegates everything else to that window (run_js,
  destroy, events, …).
- create_window keeps the rule-1 arguments.

R2-2. The `shown` handler never raises; on failure it logs a code-only warning. It runs these steps
on every platform, then the Windows-only steps (win32):
1. `window.resize(HUD_WIDTH, HUD_HEIGHT)`.
2. `win_hud.prepare(title, make_visible)`, where `make_visible` sets `window.native.Visible = True`
   on the GUI thread via `window.native.Invoke(System.Action(...))`. The System import is lazy,
   inside the function.
3. On success, set `handle.native_ready = True`.

R2-3. `ui/win_hud.py` replaces `win_region.py` (delete that file). It uses its own ctypes.WinDLL
instances; never the shared ctypes.windll, because shared argtypes break pywebview. HWND values use
c_void_p/HANDLE.
- `prepare(title, make_visible) -> hwnd | None`:
  1. FindWindowW. Set the extended style: `(ex | LAYERED 0x80000 | TOOLWINDOW 0x80 | TRANSPARENT 0x20
     | NOACTIVATE 0x08000000) & ~APPWINDOW 0x40000`.
  2. SetLayeredWindowAttributes(alpha 0, LWA_ALPHA 2).
  3. prev = GetForegroundWindow(); call make_visible(); if the HUD is now foreground and prev is
     set, call SetForegroundWindow(prev).
  4. Re-apply the style and alpha 0.
  5. SetWindowPos(HWND_TOPMOST, NOMOVE|NOSIZE|NOACTIVATE|FRAMECHANGED).
  6. DwmSetWindowAttribute(33, 2). A failure here is ignored, since Windows 10 has no rounding.
  7. Return the hwnd.
- `show(hwnd)`: alpha 255, then SetWindowPos(HWND_TOPMOST, NOMOVE|NOSIZE|NOACTIVATE|ASYNCWINDOWPOS).
- `hide(hwnd)`: alpha 0. Neither function raises; both return bool.

R2-4. `HudHandle.show()/hide()`:
- If native_ready, they use win_hud.show/hide(hwnd).
- Otherwise they fall back to window.show()/hide(). This covers non-Windows, and the time before
  prepare finishes.

R2-5. CSS: the `.pill.hud-pill` border-radius is 8px, to match the DWM corners. Everything else
stays as in rule 4.

## Tests, revision 2 (Sol) — replace T-UI-009/010/011 accordingly

| ID | Assertion |
|---|---|
| T-UI-009 | The shown handler calls resize(280,44), then (win32 monkeypatched) win_hud.prepare("Wispr Clone HUD", <callable>). native_ready follows prepare's result. Exceptions are swallowed |
| T-UI-010 | HudHandle.show/hide call win_hud.show/hide(hwnd) when native_ready. Otherwise they call window.show/hide. run_js/destroy/events delegate to the window. win_hud.prepare returns None on non-Windows, or when FindWindowW finds nothing (fake seam) |
| T-UI-011 (real) | Real webview plus open_hud, with a helper window that is ours and in the foreground. After prepare, the HUD is visible and the extended style has LAYERED, TOOLWINDOW, TRANSPARENT and NOACTIVATE, without APPWINDOW. handle.show() leaves GetForegroundWindow unchanged. The size is 280x44*scale. DwmGetWindowAttribute(33) = 2 where supported. Exit within 20 s. No screen capture |
| T-WEB-013 | Add: `.pill.hud-pill` border-radius 8px |

## Revision 3: readiness signal

The real run showed that the `shown` handler runs asynchronously, so `native_ready` is read too
early.
- `HudHandle.prepared` is a `threading.Event`. The `shown` handler sets it in `finally`, whether
  the setup succeeded or failed.
- T-UI-009 asserts that prepared is set after the handler runs, including when the setup raises.
- T-UI-011 waits `handle.prepared.wait(5)` before it checks native_ready.
