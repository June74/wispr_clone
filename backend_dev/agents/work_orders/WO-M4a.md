# WO-M4a — Application layer: router, session/deadline validation, run and settings commands

```text
Work-order ID: WO-M4a
Role file / requested model: RED + verify: sol-integration-test-author.md / gpt-6-sol
                             GREEN: luna-integration-programmer.md / gpt-6-luna
Pipeline branch or P0/M stage: M4 (part a of a/b/c; the coordinator split M4 by size),
  branch integ/m4a-application
Outcome and observable acceptance:
  - `application.api.Api` routes validated commands to handlers and returns `Result`.
  - Stale-session and expired commands are rejected.
  - `run_start` is deduplicated by `start_request_id`, and a start request becomes invalid once
    its run is deleted or evicted.
  - The run commands (start/stop/cancel/recover, including copy through a privacy clipboard) and
    the settings commands (settings_get/update, state_get) work.
  - M4b adds model_service and the models_* commands. M4c adds dict_*, history_* and mic_*.
Base revision / worktree / branch: ba6eee9 / ~/projects/wc-m4a / integ/m4a-application
Relevant sections: CODEMAP.md §3 (module rules), §6 (command table, stale-command rules),
  WO-M3a..f (the controller API), WO-M3e decision 1 (abort on manual delete; M4c),
  dev_pipeline.md §8 row M4.
Exact writable paths (under backend_dev/):
  Sol:  tests/unit/application/** (new)
  Luna: src/wispr_clone/application/__init__.py, api.py, commands/__init__.py,
        commands/run_commands.py, commands/settings_commands.py (all new);
        src/wispr_clone/pipeline/run_controller.py (ONLY the public `run_snapshot` in rule 7)
Read-only: everything else.
Allowed imports: application → contracts, config, util, pipeline, audio, settings,
  dictionary, history, models, stt, cleanup (scripts/check_imports.py). NOT insertion: a
  destination snapshot is passed through as an opaque value from an injected callable.
Check commands (from backend_dev/, UV_LINK_MODE=copy):
  uv sync --locked; uv run ruff check --no-cache .; uv run ruff format --check .;
  uv run mypy src scripts tests/_attribution tests/fakes; uv run python scripts/check_imports.py;
  uv run pytest -q -W error
Authorization: edit only writable paths; no git writes; no PRs; the coordinator commits.
Privacy: results and logs never contain transcript text, except `run_recover` copy, which puts
  the text on the clipboard and never returns it.
```

## Pinned API

```text
# application/api.py
Handler = Callable[[Mapping[str, object]], Awaitable[Mapping[str, object]]]

@dataclass(frozen=True, slots=True)
class CommandSpec:
    handler: Handler
    mutating: bool          # needs a deadline
    needs_session: bool = True

class Api:
    def __init__(self, commands: Mapping[str, CommandSpec], *, session_token: str,
                 clock: Callable[[], float], max_validity_s: float = 30.0) -> None: ...
    @property
    def session_token(self) -> str: ...
    async def call(self, name: str, payload: Mapping[str, object]) -> Result[dict[str, object]]: ...

# application/commands/run_commands.py
class RunCommands:
    def __init__(self, controller: RunController, *, clock: Callable[[], float],
                 copy_to_clipboard: Callable[[str], Awaitable[None]],
                 last_external_destination: Callable[[], object | None],
                 dedupe_window_s: float = 30.0) -> None: ...
    def specs(self) -> dict[str, CommandSpec]: ...      # run_start/run_stop/run_cancel/run_recover
    def invalidate(self, run_id: str) -> None: ...      # called on manual delete (M4c) and eviction (M5 wiring)

# application/commands/settings_commands.py
class SettingsCommands:
    def __init__(self, store: SettingsStore, history: HistoryRepo, controller: RunController, *,
                 session_token: Callable[[], str],
                 readiness: Callable[[], Awaitable[list[dict[str, object]]]]) -> None: ...
                 # M4b supplies model_service.status; tests inject a fake
    def specs(self) -> dict[str, CommandSpec]: ...      # settings_get/settings_update/state_get
```

## Rules (binding)

1. **`Api.call`:**
   1. An unknown name → `Result(False, None, UNKNOWN_COMMAND)`.
   2. If `needs_session`: `payload["session_token"]` must equal the current token, else
      PREVIOUS_SESSION_TOKEN.
   3. If `mutating`: `payload["deadline"]` must be a number with
      `clock() <= deadline <= clock() + max_validity_s`. Otherwise EXPIRED_COMMAND if it is in the
      past, or VALIDATION if it is missing, not a number, or too far in the future.
   4. The handler gets the payload without `session_token` and `deadline`.
   5. The handler's return is wrapped in `Result(True, dict(...), None)`.
   6. A handler `WisprError` or `ThirdPartyError` → `Result(False, None, error.error_code)`. Any
      other exception → STORAGE_ERROR.
   7. Nothing from the exception is logged except its code. Payload values are never logged.
   - A malformed payload field (wrong type or missing) → VALIDATION, which handlers raise.
2. **`state_get`** has `needs_session=False` and `mutating=False`, so a reconnecting UI can learn
   the token. It returns:
   - `session_token`, and `settings` (`store.load()` as a JSON-safe dict);
   - `models` (`await readiness()`);
   - `runs`: `[controller.run_snapshot(r) for r in history.list_runs()]`, newest first;
   - `active_run_id`.
   All other commands have `needs_session=True`.
3. **`run_start`** (mutating) takes payload `request_id: str`.
   - If `request_id` is in the invalidated set → RUN_DELETED.
   - If it is in the dedupe map (request_id → (run_id, time), kept for `dedupe_window_s`), return
     `{"run_id": run_id, "deduplicated": True}` with no second start.
   - Otherwise `run_id = await controller.start(start_request_id=request_id)`, record it, and
     return `{"run_id": run_id, "deduplicated": False}`.
   - Concurrent identical `request_id`s: the second waits for the first and gets its run_id,
     using a per-request `asyncio.Future`.
   - `invalidate(run_id)` moves every request_id that maps to that run into the invalidated set,
     kept for `dedupe_window_s`.
4. **`run_stop`** / **`run_cancel`** (mutating):
   - `run_stop` requires `run_id` and calls `controller.stop`.
   - `run_cancel` takes an optional `run_id`: if present, `controller.cancel(run_id)`; else
     `controller.cancel_current()`.
   - Repeated calls have no extra side effects.
   - They return `{"run_id": ...}` (None allowed for cancel_current when nothing was running,
     encoded as `{"run_id": None}`).
5. **`run_recover`** (mutating) takes payload `run_id`, `expected_version: int`, `action` (a
   RecoveryAction value), `acknowledge_uncertain: bool` (optional, default False), and
   `use_selected_destination: bool` (optional, INSERT only).
   - **copy:** `text = await controller.copy_text(run_id)`, then
     `await copy_to_clipboard(text)`, then return `{"run_id": run_id}`. The text is never returned,
     and there is no state change.
   - **insert** with `use_selected_destination`: `dest = last_external_destination()`. If it is
     None → DESTINATION_UNVERIFIABLE. Otherwise pass `destination=dest` to `controller.recover`.
   - **Others:** `controller.recover(run_id, RecoveryAction(action),
     expected_version=..., acknowledge_uncertain=...)`.
   - It returns `{"run_id": run_id}`. The acknowledgment never means the text was inserted.
6. **`settings_update`** (mutating) takes payload `patch: dict` and returns the new settings.
   `settings_get` (not mutating) returns the current settings.
   - Settings are serialized with the pydantic model's JSON-safe dump.
7. **`RunController.run_snapshot(record) -> dict`** is the only controller change, a public
   method with no behavior change. It returns `{"run_id", "version", "status", "created_at",
   "actions": sorted(effective recovery actions)}`, where the actions reuse the existing private
   effective-action logic. It contains no text fields.

## Tests (Sol; IDs in function names)

- Use a real Database, SettingsStore, HistoryRepo and RunController (with the M3 fakes), a fake
  readiness, and a fake clipboard.
- T-APP-004's full delete wiring lands in M4c; here, test `invalidate` directly.

| ID | Assertion |
|---|---|
| T-APP-001 | Unknown command → `ok=False, error=unknown_command`; handler exceptions map to codes; no payload value appears in caplog |
| T-APP-002 | `run_start` twice with the same request_id → one `controller.start`, the same run_id, the second `deduplicated=True`; concurrent duplicates also start once |
| T-APP-003 | Wrong session_token → previous_session_token; deadline in the past → expired_command; deadline beyond max validity or missing → validation; `state_get` works without a token |
| T-APP-004 | After `invalidate(run_id)`, replaying its request_id → run_deleted, and no new run is created |
| T-APP-007 | `state_get` returns token, settings, models (from the fake readiness), runs (newest first, snapshots with actions, NO text fields) and active_run_id |
| T-APP-008 | `run_recover` copy → the clipboard fake receives the selected text; the result has no text; no status change; 0 send_inputs |
| T-APP-009 | `run_recover` insert with `use_selected_destination` and no destination → destination_unverifiable; with one → `controller.recover` receives it |
| T-APP-010 | `run_cancel` without run_id cancels the current run; repeated stop/cancel → no error, no extra events |
| T-APP-011 | `settings_update` with an invalid patch → validation; a valid patch persists and is returned |

## Coordinator decisions after RED review

1. API details (from Sol):
   - `SettingsStore.load()`/`update()` are async and return a pydantic model. Serialize with
     `model_dump(mode="json")`.
   - `HistoryRepo.list_runs()` is async and already returns newest first.
   - `Result` requires non-None data on success; every handler returns a dict (never None).
2. **After Sol's verification (T-APP-012), binding:**
   - a. The session token must be a `str` and equal to the current token
     (`hmac.compare_digest`). Anything else → PREVIOUS_SESSION_TOKEN.
   - b. The deadline must be a finite int/float (`math.isfinite`, no bool). NaN/inf → VALIDATION.
   - c. `invalidate(run_id)` also records the run_id in an invalidated-runs set. When a pending
     `run_start` resolves to an invalidated run_id, map its request_id to invalidated and raise
     RUN_DELETED. Later replays then get RUN_DELETED too.
   - d. **No time-based dedupe window** (the `dedupe_window_s` parameter is removed from the
     pinned API). Dedupe and invalidation entries are kept until `invalidate` or until a cap of
     1000 entries each (oldest dropped). A replay therefore can never reach `controller.start`
     twice, whatever the command deadline. History also dedupes `start_request_id`
     persistently.
     - Sol updates the tests that construct `RunCommands(dedupe_window_s=...)`.
