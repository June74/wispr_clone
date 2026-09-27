# WO-native-pill-hud: a native-drawn full-pill HUD on Windows

```text
User decision (2026-09-27): build the full pill. The user's HUD settings v2:
  window 272x44, padding 16/6, gap 12, label 12 px weight 500, dot 8, wave 88x28, radius 22.
Why native: DWM caps the corner radius at about 8 px, and WebView2's composition layer ignores
  window regions (measured). A per-pixel-alpha layered window drawn with GDI+ gives smooth pill
  ends and a real soft shadow.
Validated on the real PC (native_pill_prototype.py.txt in this folder):
  - UpdateLayeredWindow succeeds, at about 5 ms per frame;
  - the pill's corners show the backdrop through them;
  - showing it leaves the foreground window unchanged.
Findings from the prototype:
  - PrivateFontCollection.AddFontFile FAILS on \\wsl.localhost UNC paths, and works from a local
    path. geist.ttf is a variable font whose named instances appear as families; use "Geist Medium".
  - Use private ctypes.WinDLL instances, never ctypes.windll (shared argtypes break pywebview).
Branch / worktree: feat/native-pill-hud / ~/projects/wc-pill
Writable: Luna: src/wispr_clone/ui/hud_model.py (new), src/wispr_clone/ui/waveform_model.py (new),
                src/wispr_clone/ui/native_hud.py (new), src/wispr_clone/ui/events.py,
                src/wispr_clone/app.py (HUD creation only), tests/_attribution/impact/pywebview.toml
                (modules list only)
          Sol:  tests/unit/ui/test_hud_model.py, tests/unit/ui/test_waveform_model.py,
                tests/unit/ui/test_native_hud.py, tests/integration/test_real_native_hud.py,
                tests/fixtures/waveform_golden.json plus its generator
                web/tests/waveform_golden.test.mjs, tests/unit/ui/test_events*.py where affected
```

## Rules

1. **`hud_model.py`** (pure and cross-platform):
   - `HUD_SPEC` holds the user's v2 values plus radius 22 and shadow margin 14.
   - `STATUS_LABELS` mirrors web/hud.js exactly. `status_color(status)` mirrors web/lib/view.js
     hudState, using these dark-theme colours: green #6fb58b, yellow #d4a954, red #e0848b, and
     #8a8191 for idle/blue.
   - `layout(scale) -> dataclass` gives in physical px: the window size (pill plus 2 × margin), the
     pill rect, the dot centre and radius, label x, and the wave rect (right edge = pill right -
     padding right).
   - `hud_visible(status)` mirrors the app's show/hide set. The label is always one of the fixed
     status strings; never a transcript.
2. **`waveform_model.py`**: a faithful PORT of web/waveform.js, not a rewrite. It covers N, W, H,
   REST, CENTER, OPACITY, X(), targets, resampleBands, levelFromBands, smoothLevel, smoothBands,
   the per-frame height update, and idle/active modes. `update(bands12, running)` and
   `tick(dt) -> heights`. Same constants, same maths.
3. **`native_hud.py`** (Windows only; lazy pythonnet imports):
   - `NativeHud` has `show()`, `hide()`, `publish_event(event: dict)` (run:state, audio:level),
     and `destroy()`.
   - It owns a daemon thread with a Win32 window: class "WisprCloneNativeHud", title
     "Wispr Clone HUD"; ex-style LAYERED|TOOLWINDOW|TRANSPARENT|NOACTIVATE|TOPMOST; style WS_POPUP.
   - It runs a message loop and draws with GDI+ into a Format32bppPArgb bitmap, pushed with
     UpdateLayeredWindow(ULW_ALPHA), as in the prototype. It draws:
     - the shadow;
     - a pill fill of ARGB(242, 27, 22, 29);
     - a 1 px white 8.6% border;
     - the dot (a pulsing ring while recording is optional);
     - the label in Geist Medium, 12 px × scale, AntiAliasGridFit;
     - waveform bars with the waveform_model heights and opacity, using lineWidth 3 of 340
       scaled to the 88 px wave width, like the canvas.
   - The font file is copied once to `%LOCALAPPDATA%\WisprClone\cache\fonts\geist.ttf`, then
     loaded. Fall back to "Segoe UI" on failure.
   - Position: bottom-centre of the primary monitor's work area (MonitorFromPoint(0,0) +
     GetMonitorInfo). The pill's bottom edge sits 48 px × scale above the work-area bottom.
     Scale comes from GetDpiForMonitor or GetDpiForWindow.
   - Animation: redraw about every 33 ms while visible and the waveform is active or settling;
     otherwise only on state changes. Honour SPI_GETCLIENTAREAANIMATION = off with 250 ms frames.
   - `show()`: SetWindowPos(HWND_TOPMOST, NOMOVE|NOSIZE|NOACTIVATE|SHOWWINDOW). `hide()`:
     ShowWindow(SW_HIDE). Neither ever activates. Every call is thread-safe: marshal onto the HUD
     thread with PostMessage or a queue.
   - `destroy()` ends the thread within 2 s. No method raises; failures log code-only warnings.
4. **`events.py`**: if a window has `publish_event`, call it with the event dict (for the HUD:
   run:state and audio:level only, with the same 30 Hz throttle) instead of `run_js`.
5. **`app.py`**:
   - On win32, create `NativeHud()` instead of `open_hud(...)`.
   - If NativeHud fails to start, fall back to open_hud and log a code-only warning.
   - The non-Windows path is unchanged. `_windows`/shutdown destroy the NativeHud.
6. Privacy: never draw, log or store transcript text or window titles in the HUD.

## Tests (Sol)

| ID | Assertion |
|---|---|
| T-UI-012 | hud_model: spec values; STATUS_LABELS equal hud.js's mapping (parse web/hud.js text); status_color matches view.js for every status; layout(1) and layout(1.5) geometry (window = (272+28)x(44+28) × scale; wave right edge = pill right - 6 × scale) |
| T-UI-013 | waveform_model equals waveform.js on golden fixtures (targets, resampleBands, levelFromBands, and a 60-frame height sequence for a fixed input). The generator is a node script run by web/tests/waveform_golden.test.mjs, which also fails if the committed fixture drifts from waveform.js |
| T-UI-014 | NativeHud on non-Windows: construction raises or returns unavailable cleanly. With fake seams: publish_event and show/hide are marshalled and never raise. events.py prefers publish_event and throttles audio to 30 Hz |
| T-UI-015 (real, WISPR_REAL_GUI=1, win32) | Real NativeHud: after show, visible; ex-style has LAYERED, TOOLWINDOW, TRANSPARENT, NOACTIVATE and TOPMOST; window size = layout(scale); GetForegroundWindow is unchanged by show, hide and show; publish_event(recording and audio levels) doesn't raise; destroy ends the thread within 2 s. No screen capture |
| T-APP-041/043 | Still pass. On Windows, app startup uses NativeHud (assert through a factory seam) |

## Revision 2 (real-PC findings)

- Every frame failed with `ModuleNotFoundError: No module named 'System.Drawing'`. In the
  prototype, pywebview had already referenced the assembly.
  - Fix: before the first draw, `_draw` does `import clr; clr.AddReference("System.Drawing")`
    once (lazily, on the HUD thread).
  - Add `NativeHud.frames_drawn: int`, counting successful UpdateLayeredWindow pushes.
- T-UI-015 missed this because it checks no pixels. It must also assert:
  - `frames_drawn >= 1` after show;
  - that frames keep increasing while recording with audio levels;
  - that no NATIVE_HUD_*_FAILED warning is logged in the child process.
- T-APP-043 expected a pywebview "Wispr Clone HUD" window. On Windows the HUD is native now, so
  expect only the settings pywebview window, plus a live native HUD (a FindWindowW class
  "WisprCloneNativeHud" check).
- T-UI-015 timing: destroy took 2.016 s once in the real suite. Keep the 2 s bound and investigate
  if it recurs.

## Revision 3: window class shared across instances (real bug)

Repro on the real PC: in one process, a second `NativeHud` draws 0 frames and times out on
destroy (2.00 s).
- Cause: RegisterClassW("WisprCloneNativeHud") binds the FIRST instance's wndproc. The later
  RegisterClassW fails with 1410, which is ignored, so every later window routes messages into a
  dead instance.
- This affects the app too, because `_create_windows` can run again.
- Fix: register the class once per process, with ONE module-level WNDPROC kept alive for the
  process lifetime. It dispatches by hwnd through a lock-protected registry
  `{hwnd: NativeHud}`.
- Map the hwnd at CreateWindowExW; set a pending instance before the call so that
  WM_NCCREATE/WM_CREATE resolve. Unmap on WM_DESTROY.
- Keep the class name "WisprCloneNativeHud".
- T-UI-015b (real): two sequential NativeHud instances in one process each draw >= 1 frame and
  destroy in < 2 s. Also two concurrent instances each draw, and both destroy.

## Revision 4: factory seam (CI Windows failure)

`unit (windows-latest)` failed T-APP-016 with `assert len(webview.windows) == 2` → 1. On win32 the
app constructs a REAL NativeHud even when the factories are fakes.
- Add `native_hud: Callable[[], Any] | None = None` to the app factories. `real_factories()` sets
  it to NativeHud on win32, and None elsewhere.
- `_create_windows` uses `factories.native_hud` when it is set and the result is `.available`.
  Otherwise it uses open_hud, which is the path unit tests and fakes take.
- Remove the direct `sys.platform == "win32"` construction.
- Tests: T-APP-016/composition tests stay as they are, passing on the fake path. Add T-APP-044: a
  fake native_hud factory is used when provided and available, and open_hud is used when it's
  unavailable. T-APP-043 (real) still sees the native HUD through real_factories.
