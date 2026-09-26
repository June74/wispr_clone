# WO-M3c — Run controller: cleanup and the cleanup-choice state

```text
Work-order ID: WO-M3c
Role file / requested model: RED + verify: sol-integration-test-author.md / gpt-6-sol
                             GREEN: luna-integration-programmer.md / gpt-6-luna
Pipeline branch or P0/M stage: M3c, branch integ/m3c-cleanup
Outcome and observable acceptance:
  - If cleanup is enabled, the dictionary-adjusted text goes through CleanupEngine + guard, and
    only an accepted result is inserted.
  - Cleanup failure or guard rejection → `awaiting_cleanup_choice`: zero insertion calls, the
    original is kept, and the reason is recorded.
  - Explicit recovery: `retry_cleanup` re-runs cleanup and, on success, rechecks the destination
    and inserts. `use_original` inserts the exact raw STT text.
  - Cancel during cleanup (T-RUN-004, moved from M3b) and cancel while awaiting the choice both
    end `cancelled`.
Base revision / worktree / branch: 796e159 / ~/projects/wc-m3c / integ/m3c-cleanup
Relevant sections: CODEMAP.md §4 steps 4-5 and recovery table; WO-M3a and WO-M3b (pinned API,
  all decisions); dev_pipeline.md §8 row M3c.
Exact writable paths (under backend_dev/):
  Sol:  tests/unit/pipeline/test_run_controller_cleanup*.py (new),
        tests/fakes/cleanup.py (new: FakeCleanupEngine following cleanup/base.py exactly)
  Luna: src/wispr_clone/pipeline/run_controller.py
Read-only: everything else. Allowed new import: pipeline -> cleanup (already allowed).
Check commands (from backend_dev/, UV_LINK_MODE=copy):
  uv sync --locked; uv run ruff check --no-cache .; uv run ruff format --check .;
  uv run mypy src scripts tests/_attribution tests/fakes; uv run python scripts/check_imports.py;
  uv run pytest -q -W error
Authorization: edit only writable paths; no git writes; no PRs; the coordinator commits.
Privacy: never log transcript or cleaned text. `cleanup_reason` holds only fixed codes.
```

## Pinned API additions (M3a/M3b API unchanged)

```text
@dataclass(frozen=True, slots=True)
class RunServices:
    ...all M3a fields unchanged...
    cleanup: CleanupEngine | None = None      # new LAST field, default None (M3a/M3b tests unchanged)

class RunController:
    async def recover(self, run_id: str, action: RecoveryAction, *, expected_version: int) -> None:
        # M3c supports RETRY_CLEANUP and USE_ORIGINAL. M3d adds INSERT and COPY; until then
        # they raise WisprError(VALIDATION, "run", "action").
        # Order: history.get(run_id) (RUN_EXPIRED/RUN_NOT_FOUND propagate); then
        # record.version != expected_version → WisprError(STALE_VERSION);
        # action not in allowed_recovery_actions(state) → WisprError(VALIDATION, "run", "action").
        # Then transition (RETRY_CLEANUP / USE_ORIGINAL → processing), persist, publish, and
        # start a background task for that run. It is registered in the same task table, so
        # `settled` and `cancel` work, with its own cancel flag. `recover` returns without waiting.
```

## Rules (binding)

1. **Config at run start:** `config_snapshot()` is stored on the run (M3a).
   - Keys: `cleanup_enabled` (bool; **missing means False**, so the M3a/M3b tests stay
     cleanup-off) and `cleanup_instructions` (str; missing means "").
   - The controller reads them from the run's stored `record.config`, never the live settings,
     so an edit mid-run does not affect that run.
   - If `cleanup_enabled` is true but `services.cleanup is None`, treat it as cleanup failure
     with reason `cleanup_unavailable`.
2. **Cleanup off** (T-RUN-009): unchanged from M3a. The adjusted text is inserted,
   `cleanup_status=off`, `output_selection="adjusted"`.
3. **Cleanup on**, after the dictionary step:
   1. Persist `original_text`, `adjusted_text` and `cleanup_status=pending` in one
      `update_run`, with `output_selection` None.
   2. `cleaned = await cleanup.clean(CleanupRequest(text=adjusted,
      glossary=tuple(e.spelling for e in entries), instructions=cleanup_instructions))`.
   3. If it raises `ThirdPartyError`/`WisprError`, then `cleanup_status=failed` and
      `cleanup_reason` = the error code value. Any other exception gives `cleanup_reason =
      "cleanup_unavailable"`.
   4. Otherwise `verdict = guard.check(adjusted, cleaned)`. If it is not accepted, then
      `cleanup_status=rejected` and `cleanup_reason = ",".join(sorted(verdict.reasons))`.
   5. On failure or rejection: in one `update_run`, set the cleanup fields and
      `status=awaiting_cleanup_choice`, through the CLEANUP_FAILED transition. Publish run:state,
      then `{"name": "run:recovery", "run_id", "version", "status": "awaiting_cleanup_choice",
      "actions": sorted(allowed_recovery_actions(state))}`. Stop: **no insertion claim or
      dispatch**. Never store `cleaned_text` for a rejected result.
   6. Accepted: persist `cleaned_text=cleaned`, `output_selection="cleaned"` and
      `cleanup_status=ok`, then insert `cleaned`, as in M3a step 4.
4. **Cancel during cleanup** (T-RUN-004): the flag is checked right after `clean()` returns or
   raises. When set, the result is discarded, no cleaned text is stored, and the run goes
   CANCEL → `cancelled` with 0 dispatch.
5. **Cancel while awaiting the choice (no live task):** `cancel(run_id)` on a run with no live
   task loads the record. If CANCEL is legal from its status, it transitions, persists and
   publishes. Otherwise it is a no-op. This extends the M3b no-op rule only for runs that have
   no task.
6. **`retry_cleanup`:** runs rule 3 again from step 2, on the stored `adjusted_text` with the
   entries and instructions read now.
   - Success leads to a **fresh destination recheck** through `insertion.attempt`, using
     `DestinationSnapshot.from_json(record.destination)`, which is None when there is no
     destination (then HOLD). A new request id is used, with kind `automatic`.
   - Failure again returns the run to `awaiting_cleanup_choice`.
7. **`use_original`:** `output_selection="original"`, then insert the exact `original_text`
   (the raw STT text, not dictionary-adjusted, no transformation), as in rule 6's insertion
   path.
8. The `events_for` mapping and decisions from WO-M3a/M3b still apply to the recovery tasks.

## Tests (Sol; IDs in function names)

Use the M3a fixtures, plus FakeCleanupEngine with a scripted result, a raise, or a block on an
event.

| ID | Assertion |
|---|---|
| T-RUN-009 | `cleanup_enabled` False → no `clean()` call; the adjusted text is inserted |
| T-RUN-009b | The config snapshot is read from the run: editing the live config after start does not change that run |
| T-RUN-010c | Cleanup accepted → the cleaned text is inserted exactly once; `cleaned_text` stored, `output_selection="cleaned"`, `cleanup_status="ok"`; the glossary equals the dictionary spellings; the instructions are passed |
| T-RUN-010 | `clean()` raises ThirdPartyError(CLEANUP_TIMEOUT) → `awaiting_cleanup_choice`; 0 `send_inputs` and 0 attempts; `original_text`/`adjusted_text` kept; `cleanup_status="failed"`, `cleanup_reason="cleanup_timeout"`; run:recovery actions == ["copy","retry_cleanup","use_original"] |
| T-RUN-011c | Guard rejects (the cleaned text drops a negation) → same as T-RUN-010 but `cleanup_status="rejected"`, `cleanup_reason="negation"`, `cleaned_text` None |
| T-RUN-011d | `cleanup_enabled` True with `services.cleanup` None → `awaiting_cleanup_choice`, reason `cleanup_unavailable` |
| T-RUN-012 | `retry_cleanup` after a failure: the second `clean()` succeeds → the destination is rechecked (verify called) → the cleaned text is inserted once → `done` |
| T-RUN-012b | `retry_cleanup` while the user has switched away → the run ends `awaiting_destination` (no dispatch) |
| T-RUN-013 | `use_original` → exactly `original_text` inserted (the dictionary alias NOT applied); `output_selection="original"` |
| T-RUN-014 | `recover` with a stale version → STALE_VERSION, no state change; action INSERT → VALIDATION; RETRY_CLEANUP on a `done` run → VALIDATION |
| T-RUN-004 | Cancel while `clean()` is pending → `cancelled`, 0 dispatch, `cleaned_text` None |
| T-RUN-015 | Cancel while `awaiting_cleanup_choice` (no task) → `cancelled`, published; a second cancel is a no-op |
| T-RUN-016 | Privacy: transcript/cleaned text never appears in caplog output or `cleanup_reason` |

## Coordinator decisions after RED review

1. In rule 6, "the entries and instructions read now" means:
   - dictionary **entries** are re-read from DictionaryRepo (for the glossary);
   - **instructions** always come from the run's stored `record.config`, never the live
     settings (rule 1).
