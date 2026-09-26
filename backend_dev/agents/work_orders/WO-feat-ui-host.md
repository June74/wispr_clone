# WO-feat-ui-host — Native windows, HUD, bridge and event publisher (pywebview)

```text
Work-order ID: WO-feat-ui-host
Role file / requested model: RED + verify: sol / gpt-6-sol ; GREEN: luna / gpt-6-luna
Pipeline branch: wave 3, feat/ui-host (parallel with feat/web-runtime; they share the bridge
  contract in WO-feat-web-runtime, which is binding)
Outcome and observable acceptance:
  - `wispr_clone.ui` hosts the settings window (with the only JS bridge) and a non-activating
    HUD window (no bridge).
  - It validates bridge commands, forwards them to `application.api.Api` on the app worker loop,
    and publishes backend events to the pages as data only.
  - Navigation is locked to bundled files. There is no HTTP server, and debug is off in release.
Base revision / worktree / branch: 9fb8242 / ~/projects/wc-uihost / feat/ui-host
Relevant sections: CODEMAP.md §3 (ui → application only), §6 (webview security boundary,
  command/event contract), §7 G3 record (HUD focus=False evidence); WO-feat-web-runtime (bridge
  contract); WO-M4a (Api.call, Result).
Exact writable paths (under backend_dev/):
  Sol:  tests/unit/ui/** (new), tests/fakes/webview.py (new),
        tests/probes/webview/** (new: real-API shape probe, Windows only)
  Luna: src/wispr_clone/ui/__init__.py, bridge.py, events.py, windows.py, overlay.py (new)
Read-only: everything else.
Allowed imports: ui → contracts, config, util, application (check_imports). pywebview is imported
  lazily (importlib), Windows-only (already locked: pywebview 6.2.1), and never at module import.
Check commands: the usual Python set (UV_LINK_MODE=copy, ruff --no-cache).
```

## Real pywebview 6.2.1 API (verified by the coordinator from the installed package; binding)

- `webview.create_window(title, url=None, html=None, js_api=None, width, height, x, y, resizable,
  hidden, frameless, easy_drag, shadow, focus=True, minimized, on_top=False, background_color,
  transparent=False, text_select, zoomable, draggable, ...)` returns `Window`.
- `webview.start(func=None, args=None, gui=None, debug=False, http_server=False,
  private_mode=True, storage_path=None, icon=None, ...)`. It runs the GUI loop on the calling
  (main) thread.
- `webview.settings` keys include `ALLOW_DOWNLOADS`, `ALLOW_FILE_URLS`,
  `OPEN_EXTERNAL_LINKS_IN_BROWSER` and `OPEN_DEVTOOLS_IN_DEBUG`.
- Window methods: `run_js(script)` runs as-is; `evaluate_js` wraps the script in `eval`.
  Also: `get_current_url()`, `load_url(url)`, `show()`, `hide()`, `destroy()`, `move()`,
  `resize()`, and property `on_top`.
- Window events (`window.events.<name> += handler`): `loaded`, `before_load`, `closing`,
  `closed`, `shown`, `request_sent`, `response_received`, `initialized`.

## Rules (binding)

1. **Bridge (`ui/bridge.py`)** — `class Bridge`, exposed as the settings window's `js_api`.
   - Its only public method is `call(self, name, payload)`. pywebview exposes the public methods
     of the js_api object, so no other public attributes are allowed.
   - Validation happens before forwarding:
     - `name` must be a `str` and one of the `Api`'s registered commands (UNKNOWN_COMMAND
       otherwise);
     - `payload` must be a JSON-compatible dict (str keys; values: None, bool, int, float, str,
       list, dict), at most 64 KiB serialized, and nested at most 8 levels (VALIDATION
       otherwise) (T-UI-001).
   - Forward with `asyncio.run_coroutine_threadsafe(api.call(name, payload), worker_loop)` and
     wait with a 15 s timeout. A timeout gives `{"ok": false, "error": "storage_error"}`.
   - Return a plain dict `{"ok", "data", "error"}` with `error` as the code string.
   - Never log the payload.
2. **Events (`ui/events.py`)** — `class WebviewEventSink(EventSink)`.
   - `publish(event)` serializes with `json.dumps(event, ensure_ascii=True)`, then delivers
     `window.run_js("window.wisprEvent(" + json.dumps(serialized) + ")")` to each subscribed
     window. The payload arrives as one JSON string literal, never interpolated code
     (T-UI-002). **Use `run_js`, never `evaluate_js`**: the page CSP forbids eval.
   - Settings window: all event names. HUD: only `run:state` and `audio:level`.
   - `audio:level` is throttled to at most 30 per second per window (drop older).
   - Delivery errors are swallowed and counted, never raised to the publisher, and never logged
     with payload content.
   - `publish` may be called from the worker thread; pywebview marshals `run_js`.
3. **Windows (`ui/windows.py`)** — `open_settings(webview, api_bridge, *, debug: bool)` and
   `start(webview, *, debug: bool)`.
   - Settings: `create_window("Wispr Clone", url=<file URL of backend_dev/web/index.html>,
     js_api=bridge, width=1180, height=760, min_size=(1100, 700))`.
   - Before `start`, set `webview.settings`: `ALLOW_DOWNLOADS=False`,
     `OPEN_EXTERNAL_LINKS_IN_BROWSER=False`, `OPEN_DEVTOOLS_IN_DEBUG=False`, and
     `ALLOW_FILE_URLS=True` (only for the bundled local file).
   - Call `webview.start(debug=debug, http_server=False, private_mode=True)`. In release,
     `debug=False` (T-UI-005).
4. **Navigation lock (T-UI-004):** on `before_load` and `loaded`, compare `get_current_url()`
   with the allowed bundled file URL(s): the settings page for the settings window, the HUD page
   for the HUD. The comparison normalizes the path case on Windows and ignores the query/fragment.
   On a mismatch, `load_url(allowed)` and count the block. Never follow external URLs. The CSP
   itself lives in the page (web-runtime).
5. **HUD (`ui/overlay.py`)** — `open_hud(webview, *, hud_url)`:
   - `create_window("Wispr Clone HUD", url=hud_url, js_api=None, frameless=True, on_top=True,
     focus=False, resizable=False, shadow=False, transparent=True, width=240, height=56,
     hidden=True)`. **No js_api** (T-UI-003). `focus=False` is the G3-evidenced
     non-activating mode.
   - `show_hud()` / `hide_hud()` use `show()`/`hide()` and never activate or focus.
   - Placement: bottom center of the primary screen, 48 px above the bottom, via `move()`.
   - The HUD page is `web/hud.html`. web-runtime adds it (decision recorded there); until then
     the URL is a parameter.
6. **Worker/GUI threads:**
   - `webview.start` owns the main thread. The app's asyncio worker loop runs on its own thread
     (M5 wiring).
   - The Bridge never blocks the GUI thread longer than its timeout.
   - Nothing in `ui` touches storage, insertion or models.

## Tests (Sol)

Use `tests/fakes/webview.py`, a fake module mirroring exactly the real API listed above: the
signatures, the settings keys, and the Window methods and events with `+=` handlers. It records
calls.

| ID | Assertion |
|---|---|
| T-UI-001 | The bridge rejects an unknown or non-string name → unknown_command; non-dict payloads, non-JSON values (bytes, float nan/inf, objects), payloads > 64 KiB, and nesting > 8 → validation; valid calls reach Api.call on the worker loop; the Bridge has exactly one public method |
| T-UI-002 | publish run:state containing a transcript-like string with quotes, `</script>`, backslashes, and U+2028 → the run_js argument is exactly `window.wisprEvent(<one JSON string literal>)`; parsing that literal gives back the event; evaluate_js is never called |
| T-UI-003 | The HUD window is created with js_api None, focus False, on_top True, and frameless True; the HUD receives only run:state/audio:level |
| T-UI-004 | Navigation to an external URL, or to another local file, triggers load_url(allowed); the allowed URL with a query or fragment is not blocked |
| T-UI-005 | Release start: debug False, http_server False, settings ALLOW_DOWNLOADS False, OPEN_EXTERNAL_LINKS_IN_BROWSER False, OPEN_DEVTOOLS_IN_DEBUG False |
| T-UI-006 | audio:level is throttled to ≤ 30/s per window with a fake clock; delivery errors never raise out of publish |
| P-WEBVIEW-001 (probe, Windows) | The real `webview.create_window`/`start` signatures, `settings` keys and Window methods/events include every name the fake mirrors (fake-drift guard; no window is created) |

## Coordinator decisions after RED review

1. The web-runtime work order lives on another branch, so its bridge contract is copied here
   verbatim (binding for both branches):

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


2. The event-sink clock injection is named `clock` (a callable returning seconds), as Sol's tests use.
3. CODEMAP §7 wording ("all gates unverified" while the G3 row records a passed focus test)
   is a documentation inconsistency. Out of scope here; it is fixed in M5 docs.
