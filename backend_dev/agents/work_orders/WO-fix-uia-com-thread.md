# WO-fix-uia-com-thread — Initialise UI Automation on the insertion thread (user-reported)

```text
Symptom (user's first real launch, 2026-09-27):
  "[WinError -2147221008] CoInitialize has not been called / Can not load UIAutomationCore.dll",
  repeated.
Root cause (reproduced by the coordinator on the real PC):
  - `RealUia()` imports `uiautomation` on the app worker thread.
  - All UIA calls then run on the insertion executor thread, which never initialises COM.
  - Calling from a thread that did not import and did not initialise fails. With
    `uiautomation.InitializeUIAutomationInCurrentThread()` run first on that thread, it works.
Branch / worktree: fix/uia-com-thread / ~/projects/wc-com (base: main)
Writable: Luna: src/wispr_clone/app.py
          Sol:  tests/unit/app/test_com_thread*.py,
                tests/probes/uia/test_p_uia_002_thread.py,
                tests/integration/app/test_real_headless_windows.py
```

## Rules (binding)

1. Add a LAST field `insertion_thread_init: Callable[[], None] = _noop` to `AppFactories`.
   - `real_factories()` sets it to a function that imports `uiautomation` and calls
     `InitializeUIAutomationInCurrentThread()` (Windows only).
   - The self-test and test factories keep the no-op.
2. `self.insertion_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=
   "wispr-insertion", initializer=self.factories.insertion_thread_init)`.
3. `factories.win32()` and `factories.uia()` are **constructed on the insertion executor**
   (`await loop.run_in_executor(self.insertion_executor, ...)`), never on the worker thread. The
   module import, construction and every call therefore share one COM-initialised thread.
4. A failing initializer must not crash the app. The executor's first use then raises, the
   existing tracker/timer error counting applies, and startup continues.
5. At shutdown, before `insertion_executor.shutdown`, run
   `uiautomation.UninitializeUIAutomationInCurrentThread` on that thread (real factories only,
   through an optional `insertion_thread_exit` factory field with the same pattern, default no-op).

## Tests (Sol)

| ID | Kind | Assertion |
|---|---|---|
| T-APP-040 | unit | The executor initializer runs once, on the executor thread, before any offloaded call; `factories.win32()`/`uia()` are called on that same thread (record `threading.current_thread().name`); the exit hook runs on it at shutdown |
| P-UIA-002 | probe, Windows | The real uiautomation imported on another thread: a call from a fresh executor thread **without** init raises the COM error (documents the failure), and **with** the init runs `GetFocusedControl()` without error |
| T-APP-041 | integration, Windows, `manual` (skipped in CI) | Real headless startup: `App(real_factories() with webview=None and a no-op hotkey listener)`; startup; let the destination tracker tick ≥ 4 times; `timer_errors.get("tracker", 0) == 0`; shutdown. The coordinator runs it on the real PC before the PR, to catch fake-vs-real composition gaps |

## Coordinator decision after GREEN review

6. **uiautomation writes `@AutomationLog.txt` into the working directory by default** (found
   after the user's launch; it contained only the COM error). It could log control names in
   future. `init_insertion_thread` therefore calls `uiautomation.Logger.SetLogFile('')` (the
   documented way to disable the file) before `InitializeUIAutomationInCurrentThread()`.
   - Add `@AutomationLog.txt` to the repo `.gitignore`.
   - T-APP-041 additionally asserts that no `@AutomationLog.txt` appears in the cwd after the
     headless run.
   - Writable: `.gitignore` (Luna), T-APP-041 (coordinator one-liner).
7. **Flaky test exposed by the extra thread hop:**
   `test_hotkey_and_settings_update_use_api_and_rebuild_listener` waited a fixed two
   `sleep(0)` turns for hotkey-scheduled starts. Destination capture now hops to the COM thread,
   so the second start can race the cancelled first run's lease release. That DEVICE_LEASE_CONFLICT
   is correct behaviour. Sol makes the test condition-based:
   - poll (bounded, e.g. 2 s) until `active_run_id` / the run count reach the expected values;
   - after `run_cancel`, await `app.controller.settled(first_run_id)` (catching its exception)
     before pressing the rebuilt hotkey.
   Keep its assertions. Writable for Sol: tests/unit/app/test_composition.py (this test only).
