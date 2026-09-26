# WO-M4b — Application layer: model service and model commands

```text
Work-order ID: WO-M4b
Role file / requested model: RED + verify: sol-integration-test-author.md / gpt-6-sol
                             GREEN: luna-integration-programmer.md / gpt-6-luna
Pipeline branch or P0/M stage: M4 part b, branch integ/m4b-model-service
Outcome and observable acceptance:
  `application.model_service.ModelService` aggregates readiness for the selected STT and cleanup
  models, tests a model, and selects a model through validated settings (local-only enforced).
  It publishes `models:status` only when readiness changes. A health poll never touches run
  state. `models_status` / `models_test` / `models_select` are exposed as commands.
  **It never loads, unloads or reconfigures any model** (LM Studio is shared with Cognee; the
  in-process STT model is loaded only by the app at startup, M5).
Base revision / worktree / branch: bb2ff4e / ~/projects/wc-m4b / integ/m4b-model-service
Relevant sections: CODEMAP.md §3 (model_service row, health does not overwrite run HUD), §6;
  WO-M4a (Api, CommandSpec, Result); WO-feat-cleanup (/api/v0/models "loaded" check; never
  trigger JIT loading); dev_pipeline.md §8 row M4 (T-APP-005, T-APP-006).
Exact writable paths (under backend_dev/):
  Sol:  tests/unit/application/test_model_service*.py (new)
  Luna: src/wispr_clone/application/model_service.py (new),
        src/wispr_clone/application/commands/model_commands.py (new)
Read-only: everything else.
Check commands (from backend_dev/, UV_LINK_MODE=copy):
  uv sync --locked; uv run ruff check --no-cache .; uv run ruff format --check .;
  uv run mypy src scripts tests/_attribution tests/fakes; uv run python scripts/check_imports.py;
  uv run pytest -q -W error
Authorization: edit only writable paths; no git writes; no PRs; the coordinator commits.
```

## Pinned API

```text
# application/model_service.py
class ModelService:
    def __init__(self, registry: ModelRegistry, store: SettingsStore, *,
                 stt_for: Callable[[str], SttEngine | None],        # engine for a model id (None = unavailable)
                 cleanup_for: Callable[[str], CleanupEngine | None],
                 events: EventSink,
                 health_timeout_s: float = 3.0) -> None: ...
    async def status(self) -> list[dict[str, object]]: ...
        # Selected models only, in role order [stt, cleanup]:
        # {"model_id", "role", "ready": bool, "error_code": str | None}
    async def test(self, model_id: str) -> dict[str, object]: ...   # one status item for that model
    async def select(self, model_id: str) -> dict[str, object]: ... # returns {"settings": <json>, "models": status()}
    async def poll(self) -> None: ...   # computes status; publishes models:status only if it changed

# application/commands/model_commands.py
class ModelCommands:
    def __init__(self, service: ModelService) -> None: ...
    def specs(self) -> dict[str, CommandSpec]: ...
        # models_status (mutating=False), models_test (mutating=False), models_select (mutating=True)
```

## Rules (binding)

1. **Readiness per role:**
   - **stt:** `engine = stt_for(model_id)`. `ready = engine is not None and engine.ready`.
     Otherwise `error_code = "stt_unavailable"`. Never call `engine.start()` or any load.
   - **cleanup:** `engine = cleanup_for(model_id)`. `ready = await asyncio.wait_for(
     engine.health(), health_timeout_s)`. A None engine, a timeout, or any exception gives
     `ready=False, error_code="cleanup_unavailable"` (or `cleanup_timeout` for the timeout).
     `health()` is the adapter's read-only loaded check; never send a chat request from here.
   - A healthy but not-ready result gives `ready=False, error_code="model_load_failed"` for stt
     when `engine.ready` is False; for cleanup when `health()` returns False, use
     `cleanup_unavailable`.
2. **`test(model_id)`:** an unknown id → WisprError(VALIDATION, "models", "model_id"). Any
   registered model can be tested, not only the selected one. The same readiness rule applies.
   A cloud model under `local_only` → CLOUD_MODEL_FORBIDDEN, with no engine contact.
3. **`select(model_id)`:**
   - An unknown id → VALIDATION.
   - The role comes from the registry. Call `store.update({f"{role}_model_id": model_id})`,
     where the store's validation enforces local-only → CLOUD_MODEL_FORBIDDEN.
   - Then publish `models:status` with the new status, and return
     `{"settings": settings_to_data(...), "models": [...]}`.
   - Selection never loads the model.
4. **`poll()`:** compute `status()`. If it differs from the last published list, publish
   `{"name": "models:status", "models": [...]}`. It never publishes run:state or run:recovery,
   and never reads or changes runs (T-APP-005). Errors inside poll are caught; poll never raises.
5. Privacy: no model output or text is involved. Log codes only.
6. Note for M5 (no code here): the app supplies `stt_for` and `cleanup_for`. `cleanup_for`
   builds an `LmStudioCleanup` for that model id against the configured loopback endpoint.

## Tests (Sol; IDs in function names)

Use a real SettingsStore on temporary SQLite, the default registry (plus a test registry with a
non-local model), fake engines, and a FakeEventSink.

| ID | Assertion |
|---|---|
| T-APP-005 | During an active run (a run:state recording was published), `poll()` publishes only models:status and only on change; the run's record and version are unchanged; no run:state/run:recovery published by poll |
| T-APP-006 | `select` of a non-local cleanup model with local_only=True → CLOUD_MODEL_FORBIDDEN; settings unchanged; `test` of it → CLOUD_MODEL_FORBIDDEN with no engine contact |
| T-APP-013 | `status()` gives the selected stt and cleanup, in role order; an stt engine with ready False → model_load_failed; a None engine → stt_unavailable; cleanup health True → ready; health raises → cleanup_unavailable; health hangs → cleanup_timeout (fake clock or short timeout) |
| T-APP-014 | `select` of a valid local model persists it, publishes models:status, and returns settings + models; an unknown id → validation |
| T-APP-015 | No engine `start`/load method is ever called by status/test/select/poll (the fake engines record calls) |
| T-APP-016 | Commands via Api: models_status and models_test need a session but no deadline; models_select needs a deadline; errors map to codes |

## Coordinator decisions after RED review

1. STT readiness codes (resolves the rule 1 wording conflict):
   - `stt_for(model_id)` returns None → `stt_unavailable`;
   - an engine exists but `engine.ready` is False → `model_load_failed`;
   - `engine.ready` is True → ready.
2. **After Sol's verification (T-APP-017):**
   - Sol read the real adapters: `LmStudioCleanup.health` only does `GET /api/v0/models`, and
     `VoxtralTranscribeCpp.ready` reads a flag. Both are read-only.
   - Binding fixes:
     - a. `ready` is True only when `health()` returns exactly `True`; anything else →
       `cleanup_unavailable`.
     - b. `select` and `poll` are serialized by one `asyncio.Lock`, and a generation counter
       bumped by `select`. A poll whose computation overlapped a select discards its result.
     - c. The event payload and the return value are independent deep copies.
