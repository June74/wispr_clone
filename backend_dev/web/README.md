# Web runtime

`index.html` is the settings window entry point. It loads only local `styles.css`, `app.js`, and
bundled assets. `hud.html` is the floating indicator entry point; it has no command bridge.
Both pages use the same strict CSP. Geist and its OFL are bundled in `assets/`.

`app.js` calls the finite `window.pywebview.api.call(name, payload)` interface through
`lib/bridge.js`. The bridge adds the current session token to commands, a ten-second deadline to
mutations, and a request ID to `run_start`. Reconnect and a stale-session rejection fetch a fresh
`state_get`; they never replay commands. The host delivers JSON strings to `window.wisprEvent`.
The settings page consumes run, recovery, model, history, and audio events. The HUD consumes only
run and audio events and cannot issue commands.

`lib/store.js` reduces snapshots and versioned events. `lib/view.js` maps run status to HUD colors,
recovery actions, insertion confirmation, and waveform eligibility. `lib/messages.js` mirrors the
backend's stable error messages. The waveform renderer accepts the backend's twelve audio bands;
it does not open a browser microphone.

The prototype's mock history, dictionary and cleanup-example rotation, simulated completion,
model health and microphone levels, browser microphone and generated waveform, keyboard-driven
browser dictation, local copy/retry/delete mutations, undo, and speculative insertion toast were
removed. History, dictionary CRUD/import/export, microphone device/test, model status/tests,
settings, runs and recovery now use backend commands/events. The cleanup comparison remains one
static illustrative example, labelled “Example.” The bundled presentation keeps the reference
markup and classes; inline styles were moved into equivalent CSS classes for the CSP.

Some reference preferences have no backend command/schema field and are disabled: launch at login,
sound cues, floating-indicator preference, history enablement, and retention selection. The backend
reports only currently selected models, not a model catalog, so the reference's alternate-model
picker is disabled and displays the selected model. Recording-mode and shortcut values exist in
settings, but the desktop hotkey service owns those interactions; the web runtime does not capture
or rebind browser keys. The web runtime does not show reference-only aggregate usage statistics
because there is no statistics command.

The backend supplies twelve frequency bands but no waveform texture samples. The renderer
therefore uses a zero-filled waveform buffer, so the reference's texture term contributes zero;
pillar heights come from the resampled bands and overall level alone.
