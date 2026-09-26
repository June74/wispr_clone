# WO-M3e — Run controller: eviction/expiry mid-run and the settings/dictionary snapshot

```text
Work-order ID: WO-M3e
Role file / requested model: RED + verify: sol-integration-test-author.md / gpt-6-sol
                             GREEN: luna-integration-programmer.md / gpt-6-luna
Pipeline branch or P0/M stage: M3e, branch integ/m3e-eviction
Outcome and observable acceptance:
  - When history evicts or expires a run that is still active (recording, processing,
    cleanup, awaiting), `on_run_evicted(run_id)` → `RunController.abort(run_id)` stops its
    work. Late model results are rejected, the run is never re-created, and nothing is
    inserted.
  - Settings and dictionary edits made mid-run apply to the next run only.
Base revision / worktree / branch: f6d6b71 / ~/projects/wc-m3e / integ/m3e-eviction
Relevant sections: CODEMAP.md §3 (on_run_evicted delivered deferred, never re-entrant), §5
  retention bullets; WO-M3a..d (all decisions); dev_pipeline.md §8 row M3e.
Exact writable paths (under backend_dev/):
  Sol:  tests/unit/pipeline/test_run_controller_eviction*.py (new)
  Luna: src/wispr_clone/pipeline/run_controller.py
Read-only: everything else.
Check commands (from backend_dev/, UV_LINK_MODE=copy):
  uv sync --locked; uv run ruff check --no-cache .; uv run ruff format --check .;
  uv run mypy src scripts tests/_attribution tests/fakes; uv run python scripts/check_imports.py;
  uv run pytest -q -W error
Authorization: edit only writable paths; no git writes; no PRs; the coordinator commits.
```

## Pinned API addition

```text
class RunController:
    def abort(self, run_id: str) -> None: ...
        # SYNC (it is the on_run_evicted callback, which history already defers with
        # call_soon). Unknown or finished run → no-op.
```

## Rules (binding)

1. **`abort(run_id)`** is synchronous and never awaits. It:
   - marks the run aborted, a flag separate from cancel;
   - removes the run from the waiting list;
   - calls `capture.cancel()`, `session.cancel()` and `wav.close()` when they exist;
   - frees the recording slot if the run holds it.
   The run's record is already gone or going, so the controller writes NO status for it and
   publishes NO run:state or run:recovery event afterwards.
2. **Aborted run task:** after every await, an aborted flag ends the task quietly (no writes).
   - Any RUN_NOT_FOUND or RUN_EXPIRED from history for that run also ends the task quietly,
     even if `abort` was not yet delivered (deferred callback ordering).
   - It never calls `create_run` or any write that could re-create the run; `update_run` never
     upserts.
   - A late STT `finish` or cleanup result is discarded.
   - The `is_cancelled` given to the protocol also returns True when the run is aborted, so no
     dispatch happens after an abort. After dispatch has begun, the M2 boundary applies, and
     history keeps a run with an in-flight attempt, so it is not evicted.
   - `settled(run_id)` for an aborted run raises WisprError(RUN_NOT_FOUND) (or RUN_EXPIRED),
     from `history.get`. The task itself raises nothing, so there is no unretrieved exception.
3. **Dictionary snapshot:** the dictionary entries are read ONCE at `start` (after
   `create_run`) and kept in memory for that run. The dictionary step and the cleanup glossary
   of the normal path use that snapshot, so edits after start affect only the next run.
   - Explicit `retry_cleanup` still re-reads the entries (M3c decision 1), because it is a new
     explicit action.
   - Config is already a snapshot (M3c rule 1); T-RUN-031 re-checks it end to end.
4. `abort` of a run that is not active (terminal, or unknown) is a no-op.

## Tests (Sol; IDs in function names)

Wire the HistoryRepo with `on_run_evicted=lambda rid: controller.abort(rid)`: build the
controller first, or use a holder. Use the real deferred delivery.

| ID | Assertion |
|---|---|
| T-RUN-030 | Eviction while processing (STT `finish` blocked; ten newer runs are created so retention evicts it, or `delete_run` is used): after the deferred callback, `finish` returns text → discarded; 0 dispatch; no run:state for that run after the eviction; `history.get` → RUN_NOT_FOUND (never re-created); `settled` raises RUN_NOT_FOUND; no unretrieved-exception log |
| T-RUN-030g | Expiry while recording (the clock moves past 24 h and `enforce_retention` runs): capture cancelled, lease released, slot free; a new start succeeds |
| T-RUN-030h | Eviction while awaiting destination: removed from the waiting list; later ticks do nothing; 0 dispatch |
| T-RUN-030i | Eviction while `clean()` is pending: the cleanup result is discarded, nothing is written, 0 dispatch |
| T-RUN-030j | RUN_NOT_FOUND surfaces before the callback is delivered (the run is deleted directly, and the callback is suppressed): the task still ends quietly with no re-creation |
| T-RUN-031 | A dictionary entry added after start is NOT applied to that run's adjusted text, but IS applied to the next run; a config change after start does not affect the run (cleanup_enabled toggled) |
| T-RUN-031b | `abort` of an unknown or finished run → no-op, no event |

## Coordinator decisions after RED review

1. `HistoryRepo.delete_run`/`delete_all` (manual delete) do NOT fire `on_run_evicted`; only the
   count eviction and expiry do.
   - Controller side: rule 2 (RUN_NOT_FOUND ends the task quietly) covers a manual delete.
   - **Carried to M4 (binding):** the `history_delete` / `history_delete_all` commands must call
     `RunController.abort(run_id)` for each deleted run, so an in-progress recording stops and
     its mic lease is released.
2. **After Sol's verification (T-RUN-032, 032a, 032b, 032e), binding:**
   - a. `start` generates `run_id` and registers it as starting BEFORE awaiting `create_run`.
     After every await in `start`, an aborted run makes `start` release everything it acquired
     and raise WisprError(RUN_NOT_FOUND, "run", "aborted"). It never returns a deleted run.
   - b. `abort` of a starting run frees the recording-slot reservation immediately, so a new
     `start` can proceed at once.
   - c. Every run:state / run:recovery publish goes through one helper that drops the event
     when the run is aborted. This covers writes that return after the abort.
   - d. The id leaves `_aborted` when the run's task (or start) finishes, or immediately for a
     run with no task (for example a waiting run). The set therefore holds only in-progress
     aborts.
