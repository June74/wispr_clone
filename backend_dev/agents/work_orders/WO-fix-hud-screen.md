# WO-fix-hud-screen — HUD crash on real pywebview; silent exit (user-reported)

```text
Symptom: the app exits immediately with code 1 and no output.
Root cause (coordinator, real PC):
  - `ui/overlay.py` open_hud uses `screen.is_primary`. Real pywebview 6.2.1 `Screen` has only
    `x, y, width, height, scale, dpi, frame, physical_*` → AttributeError.
  - `App.run()` swallows the exception and returns 1 silently.
  - The fake had no `screens`, so the placement code never ran in any test; P-WEBVIEW-001 did
    not check `Screen`.
Branch / worktree: fix/hud-screen / ~/projects/wc-hud
Writable: Luna: src/wispr_clone/ui/overlay.py, src/wispr_clone/app.py
          Sol:  tests/fakes/webview.py, tests/unit/ui/**, tests/probes/webview/**,
                tests/unit/app/test_startup_errors*.py, tests/integration/app/test_real_gui_smoke_windows.py
```

## Rules

1. **Primary screen:** the first screen with `x == 0 and y == 0`, else `screens[0]`. With no
   screens, skip placement. The HUD is centred horizontally, 48 px above the bottom:
   `x = s.x + (s.width - 240)//2`, `y = s.y + s.height - 56 - 48`. Attributes are read with
   plain attribute access; no invented fields.
2. **No silent failure:**
   - When `run()` returns non-zero, `__main__` prints ONE line to stderr:
     `wispr_clone: startup failed at <step> (<ExceptionType>)`.
   - `<step>` is the last `startup_log` entry, or `windows` / `webview` for GUI failures.
   - There is no message text, key or transcript in the line.
   - `App` records `self.failure = (step, type_name)` for both paths (the worker error and the
     webview error).
3. The fake webview gets `screens = [Screen(x, y, width, height, scale=1.0)]` mirroring the real
   class (no `is_primary`). P-WEBVIEW-001 also asserts that the real `webview.screens[0]` has
   x/y/width/height and **no** `is_primary`.

## Tests (Sol)

| ID | Assertion |
|---|---|
| T-UI-007 | open_hud with the fake screens [(-1920,0,1920,1080), (0,0,3440,1440)] moves to the (0,0) screen at the formula position; no screens → no move, no error |
| T-APP-042 | A webview factory whose create_window raises → `app.failure == ("windows", "RuntimeError")` and `main()` prints exactly one stderr line matching the format, with no other text |
| T-APP-043 (Windows, manual; WISPR_REAL_GUI=1) | Real GUI smoke: `App(real_factories())` with a `webview.start(func=...)` hook that, after 2 s, records the settings and HUD windows exist, then destroys them; run() returns 0; no `@AutomationLog.txt`. The coordinator runs it on the real PC (a window flashes) |

## Coordinator decision after the real GUI smoke

4. **Real pywebview rejects window methods before the GUI loop runs**: `move()` before
   `webview.start()` raises `WebViewException('Main window failed to start')`.
   - open_hud computes the position first and passes `x=`, `y=` to `create_window` (the real
     signature has them). It never calls `move()` before start.
   - The fake mirrors the real rule: Window methods (`move, resize, show, hide, load_url, run_js,
     evaluate_js, get_current_url, destroy`) raise `WebViewException("Main window failed to
     start")` until the fake's `start()` has run. Event `+=` registration is allowed before start.
   - Sol updates the fake and T-UI-007 (the position is now in `create_window` options).
     Luna updates overlay.py. T-APP-043 must then pass on the real PC.
5. **Real pywebview event/readiness rules** (verified in webview/window.py and
   platforms/winforms.py, 6.2.1):
   - every Window method is decorated `_shown_call` or `_loaded_call`, and waits up to 20 s for
     that event, then raises `WebViewException("Main window failed to start")`;
   - `before_load` fires BEFORE `shown`;
   - hidden windows are Show()n then Hide()n at creation, so `shown` does fire and `show()` works
     later.
   Binding:
   - The navigation lock subscribes to `loaded` only (not `before_load`).
   - Its handler wraps everything in `try/except Exception` and counts blocks/failures without
     raising into pywebview's event thread.
   - The fake mirrors these rules: `start()` emits `before_load` (window methods still raise at
     that point), then marks the window shown, then emits `loaded`. Sol updates the fake and the
     T-UI-004 cases (before_load no longer triggers the lock). Luna updates windows.py
     (the shared helper).
6. **Double shutdown scheduling (found by the real GUI smoke):** the window `closed` event
   schedules shutdown, the worker finishes and closes its loop, and then `run()`'s `finally` calls
   `_schedule_shutdown()` again. That creates an `App.shutdown()` coroutine on a closed loop
   ("Event loop is closed", "coroutine never awaited").
   - Binding: `_schedule_shutdown` is idempotent (a flag). It returns without creating any
     coroutine when the loop is None, closed or not running.
   - Its done-callback stops the loop only if it is not closed, and never raises.
   - Sol: T-APP-044 (unit): calling `_schedule_shutdown()` twice, and after the loop closed, gives
     one shutdown, no RuntimeWarning "never awaited", and no exception (`-W error`).
