# WO-hud-inner-pill: the outside HUD shows exactly the in-app pill; remove the in-app pill

```text
User decision (2026-09-27):
  - "No pill should be visible inside the app."
  - "The outside one should show exactly what the original inner HUD showed."
In-app pill (web/index.html #pill): a status dot (green pulsing while recording, yellow while
  working); the label "Listening" / "Working"; a timer; and a ghost icon button ✕
  (aria "Cancel dictation") that triggers #dictate-cancel. It opens for recording, processing and
  awaiting_destination. Its .meter is empty (never visible) and its timer was stuck at 0:00, a bug.
Branch / worktree: feat/hud-inner-pill / ~/projects/wc-hud2
Writable: Luna: src/wispr_clone/ui/native_hud.py, src/wispr_clone/ui/hud_model.py,
                src/wispr_clone/app.py (the cancel callback wiring only), web/index.html (remove
                #pill), web/app.js (remove the pill code), web/styles.css (unused .pill rules may
                stay; the HUD page still uses them)
          Sol:  tests/unit/ui/test_hud_model.py, tests/unit/ui/test_native_hud.py,
                tests/integration/test_real_native_hud.py, tests/unit/app/*, web/tests/*
```

## Rules

1. **Remove the in-app pill.** Delete the #pill markup and every app.js reference to it (#pill,
   #pill-label, #pill-dot, #pill-meter, #pill-timer, #pill-cancel). The dictate card, with its own
   cancel and recovery buttons, stays.
2. **Native HUD content**, 272x44, radius 22, as before. Left to right:
   - padding 16;
   - the dot (8 px; pulsing ring while recording, like `.status-dot.live::after`: expanding, fading,
     1.4 s);
   - gap 12;
   - the label (Geist Medium 12 px, white; takes the remaining space; ellipsis if needed);
   - the timer: m:ss in a monospace face (Cascadia Mono, falling back to Consolas), 12 px, white
     70%, min width 38;
   - gap 12;
   - the ✕ button, a 28 px circle with a 16 px ✕ glyph drawn as two 1.5 px round-cap lines in white
     70%; on hover the circle fills white 10% and the glyph turns white;
   - right padding 6.
   The waveform is REMOVED.
3. **Labels.** "Listening" (recording) and "Working" (processing, awaiting_destination), like the
   in-app pill. For the other visible states keep STATUS_LABELS ("Needs attention", "Could not
   confirm").
4. **Timer.** It counts from the moment status becomes recording, updates every second while
   recording, and freezes during Working. It resets on the next recording.
5. **Clickable ✕, without ever activating.**
   - Drop WS_EX_TRANSPARENT; keep NOACTIVATE.
   - WM_MOUSEACTIVATE returns MA_NOACTIVATE (3).
   - WM_NCHITTEST returns HTCLIENT inside the pill shape and HTTRANSPARENT (-1) outside it. The
     layered alpha=0 margin is already click-through.
   - WM_MOUSEMOVE with TrackMouseEvent(TME_LEAVE) drives the hover state; WM_MOUSELEAVE clears it.
   - WM_LBUTTONUP inside the ✕ circle calls `on_cancel()`: a constructor argument to NativeHud,
     invoked off the HUD thread, never raising.
   - Clicks elsewhere on the pill do nothing.
6. **App wiring.** NativeHud(on_cancel=...) schedules the same cancel the Esc hotkey uses (run_cancel
   with the active run id), through loop.call_soon_threadsafe.
7. Focus must never change on show, hide, hover or click (T-UI-015 extended).

## Tests (Sol)

| ID | Assertion |
|---|---|
| T-UI-012 (update) | hud_model layout: dot, label, timer and ✕ rects for scale 1 and 1.5 (✕ circle right edge = pill right - 6; timer right = ✕ left - 12); labels per rule 3; no wave rect |
| T-UI-016 | Timer formatting and behaviour with a fake clock: 0:00 → 0:07 → 1:05; freezes during processing; resets on a new recording |
| T-UI-017 | Hit testing: point in ✕ → cancel; point on the pill elsewhere → no cancel; outside the pill → HTTRANSPARENT (pure helper) |
| T-UI-015 (real, extend) | The ex-style lacks TRANSPARENT and still has NOACTIVATE. PostMessage WM_LBUTTONDOWN/UP at the ✕ centre calls on_cancel once. Foreground unchanged throughout. frames_drawn increases while recording (for the timer and pulse) |
| T-WEB-017 | index.html has no #pill; app.js has no '#pill' selectors |
| T-APP-045 | App wiring: a NativeHud on_cancel callback schedules run_cancel for the active run (fake factories) |
