# WO-feat-web-runtime — Port the final UI to the backend-driven web runtime

```text
Work-order ID: WO-feat-web-runtime
Role file / requested model: RED + verify: sol / gpt-6-sol ; GREEN: luna / gpt-6-luna
Pipeline branch: wave 3, feat/web-runtime (parallel with feat/ui-host; the bridge contract below
  is shared and binding for both)
Skill routing: ui-design-finalize, INTEGRATION branch only.
  - No redesign.
  - No cleanup or deletion: `ui_development/` stays read-only as the reference.
  - The appearance reference is `ui_development/screenshots/`.
Outcome and observable acceptance:
  `backend_dev/web/` holds the final UI's presentation (HTML/CSS/JS, Geist font + OFL licence),
  driven only by backend commands and events. Every mock/simulated behavior path from CODEMAP
  §6's table is removed. The UI never claims an insertion the backend did not confirm, and
  never opens a browser microphone.
Base revision / worktree / branch: 9fb8242 / ~/projects/wc-web / feat/web-runtime
Relevant sections: CODEMAP.md §6 (integration boundary table, security boundary, command/event
  contract), §4 (run statuses, recovery actions, HUD colors); ui_development/code/README_final.md
  (design decisions: keep); WO-M4a..c (command names and payloads); contracts/events.py.
Exact writable paths:
  Sol:  backend_dev/web/tests/** (node:test, *.test.mjs),
        backend_dev/tests/unit/web/** (Python static checks)
  Luna: backend_dev/web/** except web/tests; .github/workflows/ci.yml (ONLY: add one step to the
        `static` job, after setup, running `node --test backend_dev/web/tests/`)
Read-only: everything else, including ui_development/.
Dependencies: NONE new. Tests use Node's built-in `node:test` / `node:assert` (Node ≥ 20 is
  preinstalled on GitHub runners; local Node 22). No npm packages, no package.json dependencies.
  Playwright visual comparison is deferred (a new dependency needs the user's approval).
Check commands: the usual Python set from backend_dev/ (UV_LINK_MODE=copy; ruff --no-cache),
  plus `node --test backend_dev/web/tests/` from the repo root.
Privacy: the UI never logs transcript text to the console. The history view shows text (local UI).
```

## Structure (binding)

```text
backend_dev/web/
  index.html          from index_final.html: same markup/classes. Strict CSP meta:
                      default-src 'self'; script-src 'self'; style-src 'self';
                      font-src 'self'; img-src 'self' data:; connect-src 'none'; object-src 'none';
                      base-uri 'none'; form-action 'none'. No inline <script>, no inline event handlers.
  styles.css          from styles_final.css, unchanged except asset paths
  assets/geist.ttf, assets/OFL-Geist.txt   copied byte-for-byte (licence must travel with the font)
  app.js              DOM wiring only (ES module); imports lib/*
  waveform.js         from waveform_final.js: the renderer only. Input = backend 12-band
                      `audio:level.bands` (0..1), mapped to the Frequency Lanes pillars. No
                      getUserMedia/AudioContext/synthetic phrase.
  lib/bridge.js       command client (below)
  lib/store.js        pure state: snapshot + event reducer
  lib/view.js         pure presentation rules (below)
  lib/messages.js     ErrorCode → message, a mirror of src/wispr_clone/util/error_messages.py
  README.md           runtime record: entry point, bridge contract, what was removed and why
```

## Bridge contract (binding; ui-host implements the Python side)

- **Commands:** `window.pywebview.api.call(name, payload)` returns a Promise that resolves to
  `{ok, data, error}` (a JSON object).
  - `lib/bridge.js` adds `session_token` (from the last state_get) to every command except
    `state_get`.
  - Mutating commands also get `deadline = Date.now()/1000 + 10`.
  - The mutating set is: run_*, settings_update, models_select, dict_add/update/delete/import,
    history_delete/delete_all/copy, mic_test_*.
  - `request_id` (from `crypto.randomUUID()`) is added for run_start.
- **Events:** the host calls `window.wisprEvent(jsonText)` with a JSON **string**. The UI parses
  it with `JSON.parse` and never evals it. Names: run:state, run:recovery, models:status,
  history:changed, audio:level.
- **Connection:**
  - On load, and on `window.wisprReconnect()`, the UI calls `state_get`, replaces its store
    from the snapshot, and **never replays** earlier mutations (T-WEB-006).
  - An `error` of `previous_session_token` triggers the same refresh.
- **No pywebview api:** `window.pywebview` is absent in a plain browser, and in the HUD. There,
  `bridge.available()` is false and controls show a disabled "not connected" state. There is no
  mock fallback.

## Rules (binding)

1. **Remove every CODEMAP §6 mock path:**
   - the mock `history`, `samples`, `dictionary` and `cleanupExamples` data arrays (the cleanup
     preview becomes a static illustrative example clearly labelled "Example");
   - timers that manufacture processing, success, model health, mic results or save results;
   - browser shortcuts that drive dictation (Ctrl+Shift+Space / Esc as run control). Ctrl+B and
     Ctrl+K stay: they are presentation-only;
   - undo that resurrects deletions.
   Timers remain allowed only for visual presentation: toast dismissal, tooltips, CSS-state
   delays.
2. **Lists and CRUD come from commands:** `dict_*`, `history_*`, `settings_*`, `models_*`,
   `mic_*`. The UI renders what the backend returns and refreshes on `history:changed`.
3. **Run display:** from run:state and run:recovery only.
   - HUD and card colors: recording → green animating; processing → yellow stationary;
     awaiting_destination → yellow stationary; awaiting_cleanup_choice / error / uncertain → red
     stationary; held / idle → blue stationary (CODEMAP §4). **Only green animates** (T-WEB-007).
   - **The "inserted" toast appears only on run:state `done`** (T-WEB-004).
   - A failed or rejected cleanup (`awaiting_cleanup_choice`) shows the actions from the
     run:recovery `actions` list (retry cleanup / use original / copy) plus cancel, and no
     insertion toast (T-WEB-005). Each button sends `run_recover` with the run's current
     version.
4. **Waveform:** it animates only while the displayed run is `recording` and `audio:level`
   events arrive (bands → pillars). Otherwise it shows the still Quiet Pillars. The mic test on
   the Recording page uses `mic_test_start/stop` levels (run_id null).
5. **Errors:** show `messages.js[error]`. Never display raw exception text.
6. **Theme:** synced with settings (`theme`) through settings_update. The sidebar
   open/collapsed state may stay in localStorage (presentation-local).
7. **Pure modules** (`lib/store.js`, `lib/view.js`, `lib/bridge.js`) have no DOM access, so
   node:test can import them directly. `view.js` exports at least
   `hudState(status) -> {color, animate}`, `shouldToastInserted(event)`,
   `recoveryButtons(recoveryEvent)`, `waveformActive(runStatus, lastLevelAt, now)`.

## Tests (Sol)

| ID | Kind | Assertion |
|---|---|---|
| T-WEB-001 | Python static | web/*.js contain no mock data arrays (the names above), no "simulated", and no setTimeout/setInterval tied to completion (allowed only in whitelisted presentation helpers, checked by comment tag `// presentation-timer`) |
| T-WEB-002 | Python static | no `getUserMedia`, `AudioContext`, `mediaDevices` anywhere under web/ |
| T-WEB-002b | Python static | index.html has the exact CSP; no remote URLs (http:, https:, //) in html/css/js; no inline scripts or on* handlers; the font and OFL licence are present and byte-identical to ui_development |
| T-WEB-003 | node | store built from a state_get snapshot exposes settings, models and runs; applying run:state events updates only that run's status/version; older versions are ignored |
| T-WEB-004 | node | shouldToastInserted is true only for run:state `done`; false for uncertain/error/awaiting/processing |
| T-WEB-005 | node | recoveryButtons for awaiting_cleanup_choice gives retry_cleanup/use_original/copy (+cancel); never an insertion toast |
| T-WEB-006 | node | the bridge adds session_token, deadline and request_id correctly; a reconnect or previous_session_token issues exactly one state_get and replays nothing; state_get has no token |
| T-WEB-007 | node | hudState: only `recording` animates, and the colors match rule 3 |
| T-WEB-008 | Python static | messages.js keys and texts equal util/error_messages.py |

## Coordinator decisions after RED review

1. **CSP vs. reference markup:** the reference `index_final.html` has an inline `<script>` and
   inline `style="..."` attributes, which the strict CSP (`script-src 'self'; style-src 'self'`)
   blocks.
   - Move the inline script into `app.js`.
   - Convert every markup `style` attribute into an equivalent CSS class in `styles.css`, so the
     rendering is identical. This is a like-for-like conversion, not a redesign.
   - JS may still set `element.style.<prop>` (CSSOM), which CSP allows. JS must not use
     `setAttribute('style', ...)` or inline handlers.
2. **Cancel** on the cleanup-choice card (and anywhere else) sends `run_cancel` with `run_id`,
   not `run_recover`. `RecoveryAction` has no cancel.
3. **Export names:** `lib/store.js` exports `createStore(snapshot)` and
   `applyEvent(state, event)`; `lib/bridge.js` exports `createBridge(windowLike)`. These are the
   names Sol's tests use; accepted.
4. **HUD page (from WO-feat-ui-host rule 5):** add `web/hud.html` + `web/hud.js`, the floating
   listening pill from the reference (waveform + status color).
   - No commands and no bridge use: it only defines `window.wisprEvent` for run:state and
     audio:level.
   - The same CSP, and it reuses `styles.css`, `waveform.js` and `lib/view.js`.
   - T-WEB-002b's static checks cover it too.
5. **Coordinator review of GREEN: the waveform was rewritten, not ported (binding fix).** The
   approved "Frequency Lanes on Quiet Pillars" renderer (ui_development/code/waveform_final.js,
   spec in git history) must be preserved exactly:
   - geometry: N=29, W=340, H=72, SCALE=2, CENTER=36, REST=2, `X(i)=44+9i`,
     `OPACITY = 0.30 + 0.55·sin(πi/28)`;
   - `interpolate` / `smoothSample`;
   - `targets(level, bands, wave) = REST + 57·clamp(level)·(0.025 + 0.84·band + 0.135·waveform)`,
     with the same sampling (`u*31` radius 1, `u*127` radius 2);
   - the easing/draw loop that stops when still and settles to the exact resting pixels;
   - `prefers-reduced-motion` handling;
   - color from the theme.
   ONLY the input changes:
   - `bands32 = resample(backend 12 bands → 32)` by linear interpolation;
   - `level = clamp(max(bands12))`;
   - `wave = zeros(128)` (the backend sends no waveform, so the 0.135 texture term is 0;
     documented in web/README.md);
   - remove the mic analysis and the synthetic `sampleFrame`.
   Export the pure helpers `targets`, `resampleBands`, `levelFromBands` (ES module) for tests.
   Sol adds T-WEB-009 (node): targets() equals the reference formula for sampled inputs,
   resampleBands() endpoints/midpoints are correct, silence gives exactly REST for all 29
   pillars, and the geometry constants match.
