# WO-M3d — Run controller: awaiting destination, held, and Insert/Copy recovery

```text
Work-order ID: WO-M3d
Role file / requested model: RED + verify: sol-integration-test-author.md / gpt-6-sol
                             GREEN: luna-integration-programmer.md / gpt-6-luna
Pipeline branch or P0/M stage: M3d, branch integ/m3d-awaiting
Outcome and observable acceptance:
  - A run whose user switched away enters `awaiting_destination`, and is later delivered to its
    ORIGINAL destination through the M2 hybrid delivery (return trigger or idle jump). Delivery
    is oldest first, one at a time.
  - The idle threshold and wait limit are snapshotted per run at start.
  - A destination that is closed or unverifiable, or a wait past the limit → `held`.
  - Explicit Insert recovery (with a double-paste guard) and Copy (never pastes) work.
  - Stale versions and expired runs are rejected.
Base revision / worktree / branch: c46decc / ~/projects/wc-m3d / integ/m3d-awaiting
Relevant sections: CODEMAP.md §4 (steps 6-7, hybrid delivery, recovery table), WO-M2
  (deliver_next), WO-M3a..c (all decisions; M3a decision 4 note on insertion_outcome);
  dev_pipeline.md §8 row M3d.
Exact writable paths (under backend_dev/):
  Sol:  tests/unit/pipeline/test_run_controller_awaiting*.py (new),
        tests/unit/pipeline/test_insertion_protocol.py (T-PRO-027 only)
  Luna: src/wispr_clone/pipeline/run_controller.py,
        src/wispr_clone/pipeline/insertion_protocol.py (rule 2 only)
Read-only: everything else.
Check commands (from backend_dev/, UV_LINK_MODE=copy):
  uv sync --locked; uv run ruff check --no-cache .; uv run ruff format --check .;
  uv run mypy src scripts tests/_attribution tests/fakes; uv run python scripts/check_imports.py;
  uv run pytest -q -W error
Authorization: edit only writable paths; no git writes; no PRs; the coordinator commits.
Privacy: never log transcript text.
```

## Pinned API additions (earlier API unchanged)

```text
@dataclass(frozen=True, slots=True)
class RunServices:
    ...unchanged...
    cleanup: CleanupEngine | None = None
    clock: Callable[[], float] = time.time      # new LAST field; the same wall clock as history

class RunController:
    async def delivery_tick(self) -> None: ...
        # One hybrid-delivery step. The app (M5) calls it periodically.
    @property
    def waiting_run_ids(self) -> tuple[str, ...]: ...   # oldest first
    async def recover(self, run_id: str, action: RecoveryAction, *, expected_version: int,
                      acknowledge_uncertain: bool = False) -> None: ...
        # adds INSERT; COPY still raises VALIDATION ("use copy_text")
    async def copy_text(self, run_id: str) -> str: ...
        # The selected output text, with expiry enforced through history.get. No state change,
        # no insertion call, no clipboard access (the M4 command owns the clipboard).

# insertion_protocol.py
@dataclass(frozen=True, slots=True)
class WaitingRun:
    ...M2 fields unchanged...
    idle_threshold_ms: int | None = None     # per-run override (rule 2)
    wait_limit_s: float | None = None
```

## Rules (binding)

1. **Entering awaiting:**
   - When `events_for(result)` yields DESTINATION_AWAY, persist `status=awaiting_destination`
     and `awaiting_since=clock()` in ONE `update_run`, publish run:state, then run:recovery
     (rule 6).
   - Append a `WaitingRun(run_id, text, snapshot, request_id=new_id(), awaiting_since,
     idle_threshold_ms, wait_limit_s)` to the controller's waiting list:
     - `text` is the selected output text;
     - `request_id` is generated once and kept for that waiting run;
     - `idle_threshold_ms = int(config["idle_jump_seconds"] * 1000)` and
       `wait_limit_s = config["destination_wait_limit_seconds"]`, from the run's stored config.
       A missing key means None, so the protocol defaults apply.
2. **Protocol (the only change):** `deliver_next` uses `w.idle_threshold_ms` and
   `w.wait_limit_s` when they are not None, and the constructor values otherwise. Sol adds
   T-PRO-027.
3. **`delivery_tick`:**
   - If the list is empty, return.
   - Call `insertion.deliver_next(waiting, is_cancelled=lambda rid: cancel_flag(rid))`.
   - On AWAITING, change nothing.
   - On any other outcome, remove that run from the list and apply `events_for(result)` from
     `awaiting_destination`, persisting ONE final status (M3a decision 1).
   - INSERTED/UNCERTAIN/FAILED go through DISPATCH_BEGIN_AUTO; HELD → `held` (+ run:recovery);
     CANCELLED → `cancelled`; ABANDONED → drop the entry and publish nothing; DUPLICATE → drop
     the entry, with no status change.
   - Exceptions inside a tick are caught. The entry stays, the loop never dies, and the next
     tick retries. Nothing is logged except fixed codes.
4. **Held on first attempt:** a HELD from the immediate `attempt` (M3a) now also publishes
   run:recovery.
5. **Cancel while awaiting:** `cancel(run_id)` on a waiting run (no live task) removes it from the
   waiting list, then transitions CANCEL, as in M3c rule 5.
6. **run:recovery** is published after run:state whenever a run ENTERS `awaiting_destination`,
   `held`, `error` or `uncertain` (as well as `awaiting_cleanup_choice` from M3c). `actions` is
   `sorted(allowed_recovery_actions(state))`. Nothing is published for done or cancelled.
7. **`recover(INSERT)`:**
   1. `history.get` (RUN_EXPIRED/RUN_NOT_FOUND propagate) → version check (STALE_VERSION) →
      allowed-action check (VALIDATION).
   2. **Double-paste guard:** `outcome = history.insertion_outcome(run_id)`.
      - `inserted` → WisprError(VALIDATION, "run", "already inserted").
      - `uncertain` and not `acknowledge_uncertain` → WisprError(VALIDATION, "run",
        "acknowledge").
      - `in_flight` → WisprError(DUPLICATE_REQUEST, "run", "in flight").
   3. If the run is on the waiting list, remove it before the attempt.
   4. `result = await insertion.attempt(run_id, text, snapshot, request_id=new_id(),
      kind="explicit", is_cancelled=flag)`. `text` is the selected output (`cleaned` / `adjusted`
      / `original` per `output_selection`). `snapshot` is `DestinationSnapshot.from_json(
      record.destination)`; if there is none, raise DESTINATION_UNVERIFIABLE with no attempt.
   5. Map the explicit result:
      - INSERTED → DISPATCH_BEGIN_EXPLICIT, INSERTED;
      - UNCERTAIN → DISPATCH_BEGIN_EXPLICIT, INSERT_UNCERTAIN;
      - FAILED → DISPATCH_BEGIN_EXPLICIT, INSERT_FAILED;
      - persist ONE final status and publish it.
   6. Any other outcome makes NO status change. If the run was awaiting, it is re-added to the
      waiting list with its original `awaiting_since`. Then `recover` raises:
      - AWAITING → DESTINATION_UNVERIFIABLE "not in destination";
      - HELD → DESTINATION_CLOSED or DESTINATION_UNVERIFIABLE, per the reason;
      - DUPLICATE → DUPLICATE_REQUEST;
      - ABANDONED → RUN_EXPIRED;
      - CANCELLED → no raise.
   7. `recover(INSERT)` runs inline: it awaits the attempt and returns after the status is
      persisted. It still sets and uses a cancel flag for the run.
8. **`copy_text`:** `history.get` (expiry enforced), then the selected text. If there is no
   selected output but `original_text` exists, return `original_text`. Otherwise
   WisprError(VALIDATION, "run", "no text").

## Tests (Sol; IDs in function names)

| ID | Assertion |
|---|---|
| T-RUN-020 | User switched away at the insertion step → `awaiting_destination` with `awaiting_since` set; run:recovery actions == ["copy","insert"]; `delivery_tick` while still away and not idle → nothing; the user returns (foreground back, idle ≥ settle) → `delivery_tick` inserts exactly once into the ORIGINAL destination → `done`; a further tick does nothing |
| T-RUN-020b | Idle-jump delivery: away + idle ≥ the run's threshold → jump, insert once, the user's window restored → `done` |
| T-RUN-020c | Two waiting runs → the oldest is delivered first, one per tick |
| T-RUN-021 | `recover(INSERT)` on a `held` run with the user in the destination → one explicit attempt → `done` |
| T-RUN-021b | `recover(INSERT)` after a confirmed insert (run shown `error` but its attempt `inserted`; build the state via history) → VALIDATION "already inserted", 0 dispatch |
| T-RUN-021c | `recover(INSERT)` on `uncertain` without acknowledge → VALIDATION; with acknowledge → one new explicit attempt |
| T-RUN-021d | `recover(INSERT)` on an awaiting run while the user is elsewhere → raises, the status stays `awaiting_destination`, the run is still on the waiting list, 0 dispatch |
| T-RUN-022 | `copy_text` returns the selected text; 0 `send_inputs`; no status change |
| T-RUN-023 | `use_original` still inserts the exact original (regression of M3c through the new mapping) |
| T-RUN-024 | `recover` with a stale version → STALE_VERSION, no change |
| T-RUN-025 | `recover` / `copy_text` on an expired run (clock past 24 h) → RUN_EXPIRED |
| T-RUN-026 | The run's config has `idle_jump_seconds=3`, `destination_wait_limit_seconds=60`: idle 2.5 s → no jump; wait 61 s → `held` "wait limit"; changing the live config after start has no effect |
| T-RUN-027 | Cancel while awaiting → removed from the waiting list, `cancelled`, 0 dispatch on later ticks |
| T-RUN-028 | Destination window closed while awaiting → tick → `held`, run:recovery ["copy","insert"] |
| T-RUN-029 | An exception inside `deliver_next` (the fake raises once) → the tick does not raise; the entry is kept; the next tick delivers |
| T-PRO-027 | `WaitingRun` per-run `idle_threshold_ms` / `wait_limit_s` override the constructor values |

## Coordinator decisions after RED review

1. **Double-paste guard uses ALL attempts** (amends rule 7.2).
   `insertion_outcome` is the latest attempt only, so an older confirmed insert followed by a
   later failed attempt would slip through. Use `history.attempts(run_id)`:
   - any `inserted` → VALIDATION "already inserted";
   - any `in_flight` → DUPLICATE_REQUEST;
   - any `uncertain` without `acknowledge_uncertain` → VALIDATION "acknowledge".
2. **Insert elsewhere** (CODEMAP recovery table: "Held result → insert: user selects an external
   destination; verify it immediately before dispatch"; the awaiting row says insert elsewhere
   follows the held-result rule and ends the wait).
   - `recover(..., destination: DestinationSnapshot | None = None)`.
   - When a destination is given, it is the user-selected target: the M4 command captures it
     before the app's window takes focus. The explicit attempt uses it, and the run's stored
     destination is not changed.
   - When it is None, the stored destination is used (rule 7.4).
   - An awaiting run inserted elsewhere leaves the waiting list; if the attempt does not dispatch,
     it is re-added (rule 7.6).
3. Expired runs: history deletes on the first expired access (RUN_EXPIRED), and later access gives
   RUN_NOT_FOUND. Both are "unavailable", and tests use separate runs. No code change.
4. Sol adds:
   - T-RUN-021e: an older `inserted` attempt, then a later `failed` explicit attempt → INSERT is
     rejected "already inserted";
   - T-RUN-021f: a held run with a closed stored window, and INSERT with a new `destination`
     (the fake foreground on it) → one explicit dispatch to the new target → `done`.
