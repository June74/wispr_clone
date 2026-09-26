# WO-M3b — Run controller: cancellation

```text
Work-order ID: WO-M3b
Role file / requested model: RED + verify: sol-integration-test-author.md / gpt-6-sol
                             GREEN: luna-integration-programmer.md / gpt-6-luna
Pipeline branch or P0/M stage: M3b, branch integ/m3b-cancellation
Outcome and observable acceptance:
  - Cancel during recording or STT processing ends the run `cancelled`. It makes zero dispatch
    calls, releases the mic lease, and ignores late callbacks and results.
  - Cancel during insertion follows the M2 boundary: before dispatch it suppresses the insert;
    after dispatch it cannot retract it.
  - Overlapping start is rejected, and long silence never stops capture.
  - An empty transcript fails with NO_SPEECH_DETECTED.
  - The M3a carry-forward notes about CancelledError and unretrieved task exceptions are
    resolved.
  - Cancel during cleanup (T-RUN-004) moves to M3c, because cleanup does not exist yet.
Base revision / worktree / branch: fe33470 / ~/projects/wc-m3b / integ/m3b-cancellation
Relevant sections: CODEMAP.md §4 (cancellation boundary, step 2-3), §3 (no re-entrant callbacks);
  WO-M3a (pinned skeleton, decisions 1-5, notes in decision 4); dev_pipeline.md §8 row M3b.
Exact writable paths (under backend_dev/):
  Sol:  tests/unit/pipeline/test_run_controller_cancel*.py (new),
        tests/integration/pipeline/test_run_cancel*.py (new),
        tests/fakes/audio.py, tests/fakes/stt.py (extend only; keep existing behavior)
  Luna: src/wispr_clone/pipeline/run_controller.py,
        src/wispr_clone/pipeline/insertion_protocol.py (decision 1 only)
  Sol also: tests/unit/pipeline/test_insertion_protocol.py (T-PRO-026 only)
Read-only: everything else.
Check commands (from backend_dev/, UV_LINK_MODE=copy):
  uv sync --locked; uv run ruff check --no-cache .; uv run ruff format --check .;
  uv run mypy src scripts tests/_attribution tests/fakes; uv run python scripts/check_imports.py;
  uv run pytest -q -W error
Authorization: edit only writable paths; no git writes; no PRs; the coordinator commits.
Privacy: never log transcript text.
```

## Pinned API additions (the M3a API is unchanged)

```text
class RunController:
    async def cancel(self, run_id: str) -> None: ...
        # No-op (no error) for an unknown, settled or terminal run.
    async def cancel_current(self) -> str | None: ...
        # For the cancel shortcut. Cancels the recording run if there is one, else the most
        # recently started run whose task has not finished. Returns the run_id cancelled, or None.
```

## Rules (binding)

1. **Never `task.cancel()` a run task** to implement user cancel. Use a per-run cancel flag plus
   the resource cancels below, so no `CancelledError` lands in the middle of a DB write.
2. **Cancel while recording:**
   - set the flag; `capture.cancel()` (the queue is discarded, the iterator ends, the lease is
     released); `session.cancel()`; `wav.close()`;
   - free the recording slot immediately, inside `cancel` before it returns;
   - the task then transitions CANCEL → `cancelled`, persists it and publishes it. No
     STOP/processing event is ever published for that run.
3. **Cancel while processing (STT finishing):**
   - set the flag and call `session.cancel()`. `finish()` then raises STT_STREAM_CLOSED, or
     returns late;
   - either way, when the flag is set the task discards any text: `original_text` and
     `adjusted_text` stay None, nothing is inserted, and the run goes CANCEL → `cancelled`,
     never `error`;
   - the flag is checked after every await in `_process`: after `finish`, after
     `dictionary.entries`, after `update_run`, and before `insertion.attempt`.
4. **Cancel during `insertion.attempt`:** pass `is_cancelled=lambda: flag` to the protocol,
   which decides by the dispatch boundary. The controller applies `events_for(result)` exactly
   as returned: CANCELLED → `cancelled`; INSERTED/UNCERTAIN after dispatch → `done`/`uncertain`,
   never `cancelled`.
5. **Late callbacks:** anything that arrives for a cancelled run after `cancel` returns causes
   no state change and no event. That covers STT `on_text` callbacks, remaining chunks, and
   `finish` results.
6. **`asyncio.CancelledError`** (app shutdown or loop teardown, not user cancel): clean up the
   resources (session, capture, WAV), write **no** status, and re-raise.
   - Startup recovery for runs left in recording/processing is M5's scope; add a note, no code.
7. **Unretrieved task exceptions:** add a done-callback on each run task that retrieves the
   exception (`task.exception()` when not cancelled), so asyncio never logs "Task exception was
   never retrieved". `settled` keeps its M3a behavior: the first caller re-raises the stored
   exception.
8. **No speech:** if `text.strip() == ""` after `finish`, transition FAIL with
   `error_code=no_speech_detected`, persist `original_text=""`, and make no insertion.
9. **Long silence:** the controller has no silence timeout. Capture only ends through stop,
   cancel or a capture error.

## Tests (Sol; IDs in function names)

Use a real HistoryRepo, DictionaryRepo and InsertionProtocol (with the fakes), as in M3a.

| ID | Assertion |
|---|---|
| T-RUN-002 | Cancel during recording → `cancelled`; 0 `send_inputs`; `capture.cancel` called and the lease released; `active_run_id` None right after `cancel` returns; `session.cancel` called; run:state goes exactly recording, cancelled; no audio:level after the cancel; a new start succeeds |
| T-RUN-003 | Cancel while `finish` is pending (the fake blocks `finish` on an event) → `cancelled`; 0 dispatch; `original_text` None; also the variant where `finish` returns text after the cancel → the text is discarded, 0 dispatch |
| T-RUN-003b | Cancel during `insertion.attempt`, before dispatch (flag set when the fake verify is called the 2nd time) → CANCELLED, run `cancelled`, attempt `cancelled`; and the variant where the flag is set during dispatch → the run is `done`, not `cancelled` |
| T-RUN-005 | Overlapping start while recording → DEVICE_LEASE_CONFLICT; the first run is unaffected and completes `done` |
| T-RUN-006 | 10 minutes of silent chunks (FakeClock advanced; bands at zero) → still recording and never auto-stopped; a stop then completes normally |
| T-RUN-007 | Empty/whitespace transcript → `error` with `error_code == "no_speech_detected"`, 0 dispatch |
| T-RUN-008 | `cancel` / `cancel_current` on an unknown or finished run → no error and no event; `cancel_current` picks the recording run first, else the newest unfinished run |
| T-RUN-009a | Late STT `on_text` callback after cancel → no event and no state change |
| T-RUN-009b | The run task hits `asyncio.CancelledError` (the test cancels the task directly, simulating shutdown) → resources cleaned up, status NOT written (still `recording` in history), and the error is re-raised |
| T-RUN-009c | A failing run that nobody calls `settled` on produces no "Task exception was never retrieved" log (gc.collect + caplog) |

## Coordinator decisions after RED review

1. **M2 gap (found by Sol):** `InsertionProtocol` checks `is_cancelled()` only at the start of
   the final recheck, not after the awaited final verify and idle recheck. CODEMAP §4 step 2
   requires the cancel recheck *immediately* before OS dispatch.
   - Add one more `is_cancelled()` check as the last step before `dispatch`, after the final
     verify and idle recheck. If it is set: resolve the attempt `cancelled` and return CANCELLED
     "cancelled". A raising callback counts as cancelled, as in M2 decision 6.
   - Nothing else in the protocol changes.
   - Sol adds T-PRO-026 in `test_insertion_protocol.py`: the cancel flag flips during the final
     verify → no dispatch, attempt `cancelled`.
