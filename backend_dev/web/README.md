# Web runtime

`index.html` is the settings window entry point. It loads only local `styles.css`, `app.js`, and
bundled assets. `hud.html` is the web floating indicator; it has no command bridge. On Windows the
host draws the indicator natively (`src/wispr_clone/ui/native_hud.py`) and loads `hud.html` only if
the native HUD is unavailable. Both pages use the same strict CSP. Geist and its OFL are bundled in `assets/`.

`app.js` calls the finite `window.pywebview.api.call(name, payload)` interface through
`lib/bridge.js`. The bridge adds the current session token to commands, a ten-second deadline to
mutations, and a request ID to `run_start`. Reconnect and a stale-session rejection fetch a fresh
`state_get`; they never replay commands. The host delivers JSON strings to `window.wisprEvent`.
The settings page consumes run, recovery, model, history, and audio events. `hud.html` consumes only
run and audio events and cannot issue commands; the native HUD's cancel button asks the host to
call `run_cancel`.

`lib/store.js` reduces snapshots and versioned events (a `run:recovery` may share its `run:state`
version). `lib/view.js` maps run status to HUD colors, recovery actions, insertion confirmation, and
whether Discard is offered. `lib/forms.js` holds the settings-form rules: Save-term and
cleanup-instruction enablement, and the saved microphone selection. `lib/models.js` builds the Models page pickers and
badges, `lib/shortcuts.js` turns a key press into a shortcut binding, and `lib/secrets.js` trims a
pasted API key. `lib/messages.js` mirrors the backend's stable error messages. The waveform renderer accepts the backend's twelve audio bands;
it does not open a browser microphone.

The prototype's mock history, dictionary and cleanup-example rotation, simulated completion,
model health and microphone levels, browser microphone and generated waveform, keyboard-driven
browser dictation, local copy/retry/delete mutations, undo, and speculative insertion toast were
removed. History, dictionary CRUD/import/export, microphone device/test, model status/tests,
settings, runs and recovery now use backend commands/events. The cleanup comparison remains one
static illustrative example, labelled “Example.” The bundled presentation keeps the reference
markup and classes; inline styles were moved into equivalent CSS classes for the CSP.

Launch at login uses `autostart_get`/`autostart_set`; the Windows Run key is its only record, and
a source checkout reports it as unavailable (see `src/wispr_clone/ui/autostart.py`). The page draws the window's title bar: `bridge.window()`
sends `window_drag`, `window_minimize`, `window_toggle_maximize` and `window_close` without a session
token, and the host removes the native caption. Some reference preferences have no backend
command/schema field and are disabled: floating-indicator preference, history enablement, and retention selection. The Models
page fills each picker from `models_catalog` (OpenRouter speech models, LM Studio downloads) when the
page opens and switches models with `models_select`. The Recording page switches `recording_mode`
and records a new `dictation_shortcut` from a key press, saving both with `settings_update`; the
desktop hotkey service applies them, and browser keys never start dictation. There is no statistics
command, so the General page's usage cards show only “—”.

The backend supplies twelve frequency bands but no waveform texture samples. The renderer
therefore uses a zero-filled waveform buffer, so the reference's texture term contributes zero;
pillar heights come from the resampled bands and overall level alone. The renderer draws the
General page's dictation card and the `hud.html` fallback; the native HUD has no waveform.
