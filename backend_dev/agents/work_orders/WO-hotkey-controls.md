# WO-hotkey-controls: wire the recording-mode and shortcut controls; HUD geometry v2

```text
User report: "the text doesn't land in Notepad". Settings are toggle + ctrl+shift+space; the user
  held and released, so the recording never stopped (the only run: cancelled, no audio).
Cause: in web/app.js the #mode-seg and #shortcut-select controls are static mock-ups; the
  settings window cannot change recording_mode or dictation_shortcut. The backend already accepts
  both through settings_update, and app.py rebuilds the hotkey after every settings_update.
User asks: set the dictation shortcut to Logitech G3, which the keyboard sends as F3.
User's HUD settings v2: window 272x44, padding 16/6, gap 12, label 12/500, dot 8, wave 88x28.
  They also asked for radius 22, which is out of scope here: it needs the native-drawn HUD, see
  WO-hud-compact-tune.
Branch / worktree: feat/hotkey-controls / ~/projects/wc-keys
Writable: Luna: web/app.js, web/index.html (the mode and shortcut rows only), web/lib/shortcuts.js
                (new), web/styles.css (a capture-state style and the .pill.hud-pill padding),
                src/wispr_clone/ui/overlay.py (HUD_WIDTH)
          Sol:  web/tests/shortcuts.test.mjs (new), web/tests/*.test.mjs where affected,
                tests/unit/ui/*, tests/integration/test_real_hud_window.py (HUD width)
```

## Rules

1. **Recording mode.**
   - #mode-seg reflects `state.settings.recording_mode` (exactly one aria-checked="true").
   - Clicking a button sends `settings_update {patch: {recording_mode}}`, then re-renders from
     result.data.
   - Change the description to "Toggle: press once to start, again to stop. Hold: talk while
     held."
2. **Shortcut row.** Replace the static `<select>` with:
   - a `<kbd id="shortcut-current">` showing the formatted binding;
   - a "Change" button, `#shortcut-change`.
3. **Capture.** Clicking Change enters capture mode:
   - the button reads "Press keys… (Esc to cancel)";
   - `aria-live` announces the change.
   - A keydown listener on window uses capture, and `preventDefault()`s during capture.
   - Modifier-only keydowns update a live preview but don't finish.
   - The first non-modifier key finishes capture:
     - it builds a canonical binding with `toBinding(event)`;
     - it sends `settings_update {patch: {dictation_shortcut}}`;
     - on failure it shows messageFor(error) and keeps the old binding.
   - Escape with no modifiers cancels. Blur also cancels.
   - The listener is removed when capture ends.
   - Never log keys.
4. **`web/lib/shortcuts.js`** (pure) exports:
   - `toBinding(event) -> string|null`, returning canonical text as the Python parse_binding
     accepts it:
     - modifiers are output in the order ctrl, alt, shift, win (metaKey → win);
     - F1–F24 come from event.key → "f3";
     - letters come from event.code KeyA–KeyZ → "a"; digits from Digit0–9 → "0";
     - named keys map as: " "/Space → "space", Escape → "escape", Tab, Enter, Backspace, Delete,
       Insert, Home, End, PageUp → "page_up", PageDown → "page_down", Arrow* → up/down/left/right,
       Pause, ScrollLock → "scroll_lock";
     - anything else → null.
   - `formatBinding(text) -> string` for display: "ctrl+shift+space" → "Ctrl + Shift + Space",
     "f3" → "F3", "win+d" → "Win + D".
5. **HUD geometry v2.** HUD_WIDTH changes to 272; `.pill.hud-pill` padding becomes
   `0 6px 0 16px`.

## Tests (Sol)

| ID | Assertion |
|---|---|
| T-WEB-014 | toBinding covers: F3 → "f3"; ctrl+shift+Space → "ctrl+shift+space"; meta+KeyD → "win+d"; alt+Digit5 → "alt+5"; PageUp → "page_up"; modifier-only → null; an unknown key (e.g. "Unidentified", "F25") → null |
| T-WEB-015 | formatBinding for the examples in rule 4 |
| T-WEB-016 | app.js (static source checks, matching the existing web-test style): #mode-seg click → settings_update recording_mode; the capture flow calls toBinding and sends dictation_shortcut; the static select is gone from index.html |
| T-UI-003/007/008/011, T-WEB-013 | Expected HUD width becomes 272; padding `0 6px 0 16px` |
