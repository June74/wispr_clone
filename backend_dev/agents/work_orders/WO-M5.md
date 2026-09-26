# WO-M5 — App composition: `app.py`, `__main__.py`, single instance, startup/shutdown, self-test

```text
Work-order ID: WO-M5
Role file / requested model: RED + verify: sol / gpt-6-sol ; GREEN: luna / gpt-6-luna
Pipeline branch or P0/M stage: M5, branch integ/m5-app
Outcome and observable acceptance:
  `python -m wispr_clone` composes every service, wires every callback once, runs the
  application worker loop on its own thread and the pywebview GUI on the main thread, and
  shuts down cleanly. A second instance exits. `python -m wispr_clone --self-test` composes the
  whole app with in-process fakes and runs a scripted dictation end to end. It needs no GUI,
  GPU, network, mic or desktop, exits 0 on ubuntu and windows CI, and is used later by CD.
Base revision / worktree / branch: 8f1d379 / ~/projects/wc-m5 / integ/m5-app
Relevant sections: CODEMAP.md §3 (module table, upward callbacks table, one-worker rule), §4, §5
  (startup recovery), §6 (security), §7 G3; WO-M3a..f, WO-M4a..c, WO-feat-ui-host,
  WO-feat-web-runtime (all carried-forward notes, especially: M3e decision 1 on manual deletes,
  M3a decision 4 on startup recovery of recording/processing runs, and M4b rule 6 on
  cleanup_for).
Exact writable paths (under backend_dev/):
  Sol:  tests/unit/app/** (new), tests/integration/app/** (new)
  Luna: src/wispr_clone/app.py, src/wispr_clone/__main__.py, src/wispr_clone/selftest.py (new),
        src/wispr_clone/config.py (ONLY: add `stt_model_path()` and interval constants below)
Read-only: everything else.
Allowed imports: app / __main__ / selftest may import anything (check_imports: app → None).
  pywebview, pynput, sounddevice and the insertion Real* classes are imported lazily inside
  factory functions, never at module import. `--self-test` must never import them.
Check commands: the usual Python set (UV_LINK_MODE=copy, ruff --no-cache), plus the node tests.
Safety: never load, unload or reconfigure LM Studio models (shared with Cognee). The app only
  uses LmStudioCleanup's read-only health and chat on an already-loaded model. The app loads
  the in-process Voxtral STT model through `VoxtralTranscribeCpp.start()`. That is not an LM
  Studio model, and loading it is the app's normal job.
```

## Pinned API

```text
# app.py
@dataclass(frozen=True, slots=True)
class AppFactories:           # every external boundary is a factory, so self-test/unit tests inject fakes
    open_database: Callable[[Path], Database]
    stt_engine: Callable[[Settings], SttEngine]
    cleanup_for: Callable[[str], CleanupEngine | None]
    win32: Callable[[], Win32Api]
    uia: Callable[[], UiaApi]
    new_capture: Callable[[DeviceLease, int | None, LeaseOwner], CaptureLike]
    list_devices: Callable[[], tuple[InputDevice, ...]]
    hotkey_listener: Callable[[HotkeyService], ListenerLike]   # start()/stop()
    webview: Callable[[], Any] | None                          # None → headless (self-test)
    clock: Callable[[], float]
    monotonic: Callable[[], float]

def real_factories() -> AppFactories: ...
class App:
    def __init__(self, factories: AppFactories, *, data_dir: Path, debug: bool = False) -> None: ...
    def run(self) -> int: ...               # blocks; returns the exit code
    async def startup(self) -> None: ...    # on the worker loop; exposed for tests
    async def shutdown(self) -> None: ...   # on the worker loop; idempotent
    @property
    def api(self) -> Api: ...

def acquire_single_instance(name: str = "WisprClone") -> SingleInstance | None: ...  # None if another instance holds it
# __main__.py: argparse --self-test, --debug; the single instance; App(real_factories()).run()
# selftest.py: def run_self_test() -> int
```

## Rules (binding)

1. **Threads:**
   - One application worker thread runs one asyncio loop. All services, Api handlers and timers
     live on it (CODEMAP §3 "only the worker mutates authoritative state").
   - The GUI (`webview.start`) owns the main thread.
   - Insertion OS calls run on one dedicated single-thread executor, the insertion/COM thread;
     it is `InsertionProtocol`'s `offload`. uiautomation must not share pywebview's COM thread
     (DEPENDENCIES.md).
   - The Bridge dispatches to the worker loop (ui-host).
2. **Startup order (T-APP-010):**
   1. acquire the single instance, else exit 3;
   2. `data_dir` and the history audio dir exist;
   3. open the Database and run all migrations (m001..m004);
   4. `history.recover_on_startup()`, which reconciles in_flight→uncertain and pending
      cleanup→choice, expires, retries deletions, and removes orphan WAVs;
   5. **runs left in `recording` or `processing`** by a crash → `error` with
      `error_code=storage_error` (M3a decision 4 note). Their WAV is kept, so `retry_stt` stays
      available;
   6. load settings;
   7. build the services (the M3 RunController, the M4 commands, ModelService, `Api` with a
      fresh random `session_token` via `secrets.token_urlsafe(24)`);
   8. start the STT engine (`await stt.start()`). A failure does not abort the app: readiness
      reports it and run_start then fails with its code;
   9. start timers and the hotkey listener;
   10. only then create the windows (history is exposed to the UI).
   Record each step to an injectable `startup_log` list for tests. Codes only, no text.
3. **Callback wiring (exactly once):**
   - `HistoryRepo(on_run_evicted=…)` → `controller.abort(run_id)` + `run_commands.invalidate(run_id)`.
   - `HotkeyService(on_start/on_stop/on_cancel, post=loop.call_soon_threadsafe)`. Each callback
     schedules an internal `api.call("run_start"|"run_stop"|"run_cancel", payload)` with the
     current `session_token`, `deadline = clock()+10`, and a fresh request_id for start.
     on_stop and on_cancel target `controller.active_run_id` / `cancel_current`.
   - `EventSink`: headless → an in-memory sink; GUI → `WebviewEventSink(settings, hud)`. The HUD
     is shown on run:state recording/processing/awaiting and hidden 1.5 s after a terminal or
     idle state.
   - `copy_to_clipboard(text)` → the insertion executor running
     `win32.set_clipboard(text, exclusion_formats=True)`.
   - `last_external_destination()` → the most recent snapshot from a **destination tracker**.
     The tracker is a 250 ms timer on the worker that offloads
     `capture(win32, uia, exclude_pids={own pid})` only when the foreground hwnd changes to a
     non-own window.
   - `cleanup_for(model_id)` → `LmStudioCleanup(model_id=model_id)` against
     `config.LM_STUDIO_ENDPOINT`'s loopback base, cached per model id.
4. **Timers** (constants added to `config.py`):
   - `DELIVERY_TICK_S = 0.1` → `controller.delivery_tick()`;
   - `MODEL_POLL_S = 5.0` → `model_service.poll()`;
   - a retention timer at `history.next_expiry_at()` → `enforce_retention()`, then re-arm;
   - `TRACKER_S = 0.25`.
   Timer callbacks never raise: exceptions are caught and counted by code.
5. **Settings changes:** wrap the `settings_update` CommandSpec so that, after success, the
   hotkey service is rebuilt with the new bindings and mode (stop the old listener, start the
   new one). Nothing else is reloaded mid-run (M3e snapshot rules).
6. **Shutdown (T-APP-012; also triggered by the settings window `closed` event):** in this
   order:
   1. stop the hotkey listener;
   2. stop timers;
   3. cancel the current run (`cancel_current`) and stop any mic test;
   4. await the controller's live tasks (bounded, 5 s);
   5. `cleanup` adapters `aclose()`, then `await stt.close()`;
   6. shut down the insertion executor;
   7. close the Database;
   8. stop the worker loop;
   9. release the single instance.
   It is idempotent. Record the steps to `shutdown_log`.
7. **Single instance (T-APP-011):**
   - Windows: a named mutex `Local\WisprClone` via `ctypes` (`CreateMutexW`;
     `ERROR_ALREADY_EXISTS` = 183 → another instance is running).
   - Elsewhere, and in tests: an exclusive lock file in `data_dir` (`fcntl.flock`, or `msvcrt`
     on Windows).
   - A second instance returns exit code 3 without touching the DB or opening windows.
8. **`--self-test` (T-APP-013):**
   - Build `App` with in-process fakes defined in `selftest.py`: a fake STT that returns fixed
     text, fake capture chunks, fake win32/uia where the destination verifies and read-back
     confirms, and no webview. It uses a temporary `data_dir`.
   - Run startup, then `api.call` `run_start` → `run_stop`, and wait until the run is `done`
     (bounded 10 s). Check exactly one insertion attempt `inserted`, then shutdown.
   - Print one line `self-test ok` and return 0; on any failure print
     `self-test failed: <code>` and return 1.
   - It never imports pywebview, pynput, sounddevice, uiautomation or pywin32.
9. `config.stt_model_path()` returns `Path(os.environ["WISPR_STT_MODEL"])` if set, else the
   default GGUF path used by `scripts/check_local_models.py`. It performs no I/O at import.
10. Privacy: no text in any log. Logs are codes and step names only.

## Tests (Sol)

- `tests/unit/app` uses fake factories and a temp dir. `tests/integration/app` runs the
  subprocess self-test.
- The test fakes may reuse `tests/fakes/*`; `selftest.py` must have its own minimal fakes in
  `src`.

| ID | Assertion |
|---|---|
| T-APP-010 | `startup_log` order is exactly rule 2 (steps 2-10); history is exposed only after recovery; a run left `recording` in the DB before startup becomes `error`/storage_error with its WAV kept |
| T-APP-011 | With the lock held (a second `acquire_single_instance` in-process or a subprocess), `main()` returns 3 without opening the DB (the DB file is not created) |
| T-APP-012 | shutdown during an active recording: capture cancelled, lease free, STT closed, cleanup aclosed, DB closed, the insertion executor shut down; `shutdown_log` order per rule 6; a second shutdown is a no-op |
| T-APP-013 | `python -m wispr_clone --self-test` (subprocess, sys.executable) exits 0 and prints `self-test ok`; `sys.modules` in that process (checked by a hidden env flag that prints them) never includes webview/pynput/sounddevice/uiautomation/win32gui |
| T-APP-014 | Callback wiring: an eviction calls abort + invalidate; a hotkey on_start → one run started through Api (with a valid token/deadline); settings_update of the shortcut rebuilds the listener; timer exceptions are counted, not raised |
| T-APP-015 | The destination tracker ignores own-pid windows and captures only on a foreground change; `last_external_destination()` returns the latest external snapshot |

## Coordinator decisions after RED review

1. API gaps (from Sol), resolved:
   - a. Interrupted `recording` / `processing` runs → `error` is done by the app (rule 2 step 5)
     after `recover_on_startup`: one `update_run` per run with the FAIL transition and
     `error_code=storage_error`. History is unchanged.
   - b. `CleanupEngine` has no `aclose`. At shutdown, call `aclose()` only if the concrete adapter
     has it (`getattr(engine, "aclose", None)`), for every cached `cleanup_for` adapter and the
     run controller's engine.
   - c. There is no public drain on RunController. The app wraps the `run_start` and
     `run_recover` CommandSpecs to record the run_ids they return. At shutdown it awaits
     `controller.settled(run_id)` for each recorded id still non-terminal, bounded to 5 s in
     total, with exceptions swallowed.
   - d. Test seams are agreed as named by Sol's tests: `app.startup_log`, `app.shutdown_log`
     (lists of step names), `app.last_external_destination()`, plus `app.timer_errors`
     (dict name → count) and `app.insertion_executor`.
     `acquire_single_instance(name="WisprClone", *, lock_dir: Path | None = None)`: the lock file
     lives in `lock_dir` (tests use tmp); the Windows mutex is used when `sys.platform == "win32"`
     and `lock_dir` is None.
   - e. Hotkey callbacks take no arguments.
     - on_start → `api.call("run_start", {...token, deadline, request_id})`;
     - on_stop → if `controller.active_run_id` → `api.call("run_stop", {run_id: that})`, else no-op;
     - on_cancel → `api.call("run_cancel", {})`, which uses cancel_current.
     Each is scheduled as a task on the worker loop, with its result/exception retrieved.
