# WO-M2 — Insertion protocol

```text
Work-order ID: WO-M2
Role file / requested model: RED + verify: sol-integration-test-author.md / gpt-6-sol
                             GREEN: luna-integration-programmer.md / gpt-6-luna
Pipeline branch or P0/M stage: M2, branch integ/m2-insertion-protocol
Outcome and observable acceptance:
  pipeline/insertion_protocol.py is the sole owner of the sequence
  claim -> recheck -> dispatch -> outcome, and of hybrid delivery (return trigger, idle jump) for
  awaiting runs.
  - history stores the claims; insertion performs the OS calls; neither decides the sequence.
  - The protocol never updates run status. It returns a ProtocolResult, and run_controller (M3)
    maps that to state-machine events.
Base revision / worktree / branch: deb66b9 / ~/projects/wc-m2 / integ/m2-insertion-protocol
Relevant sections: CODEMAP.md §4 (normal path steps 6-7, hybrid delivery, insertion protocol and
  cancellation boundary), §5 (runs vs insertion_attempts); dev_pipeline.md §8 row M2.
Prerequisites: history (#15) and insertion-win (#21) merged.
Exact writable paths (under backend_dev/):
  Sol:  tests/unit/pipeline/test_insertion_protocol*.py (new),
        tests/integration/pipeline/** (new),
        tests/fakes/insertion.py (new: promote FakeWin32Api/FakeUiaApi from
          tests/unit/insertion/fake_apis.py; that file becomes a re-export so the insertion
          tests keep passing),
        tests/unit/insertion/fake_apis.py (re-export only)
  Luna: src/wispr_clone/pipeline/insertion_protocol.py (new)
Read-only: everything else.
Allowed imports: pipeline -> contracts, config, util, history, insertion (+ stdlib).
  Import Connection/IntegrityError only via wispr_clone.storage, never sqlite3 (none needed here).
Required tiers: S, U, I on ubuntu and windows.
Check commands (from backend_dev/, UV_LINK_MODE=copy):
  uv sync --locked; uv run ruff check .; uv run ruff format --check .;
  uv run mypy src scripts tests/_attribution tests/fakes; uv run python scripts/check_imports.py;
  uv run pytest -q -W error
Authorization: edit only writable paths; no git writes; no PRs; the coordinator commits.
Privacy: no text, titles or field contents in logs, reasons or exceptions. Reasons use the fixed
  vocabulary below.
Handoff: coordinator. Sol: RED output. Luna: GREEN outputs. Sol: verification findings.
```

## Pinned API (use these exact names)

```text
class ProtocolOutcome(StrEnum):
    INSERTED = "inserted"      # dispatched and confirmed by read-back
    UNCERTAIN = "uncertain"    # dispatched; not confirmed, or dispatch raised
    FAILED = "failed"          # nothing sent: 0 events accepted, or destination/idle changed after the claim
    CANCELLED = "cancelled"    # cancelled before dispatch; nothing sent
    AWAITING = "awaiting"      # user not in the destination; nothing claimed
    HELD = "held"              # closed / unverifiable / wait limit / claim failed (never with a claimed attempt)
    ABANDONED = "abandoned"    # run expired or gone before dispatch
    DUPLICATE = "duplicate"    # request already claimed, or an automatic attempt already exists

@dataclass(frozen=True, slots=True)
class ProtocolResult:
    outcome: ProtocolOutcome
    attempt_id: str | None     # the claimed (or existing, for DUPLICATE) attempt; None if no claim
    reason: str                # fixed vocabulary: "", "cancelled", "window changed",
                               # "window closed", "unverifiable", "wait limit", "claim failed",
                               # "expired", "input during jump", "bring forward failed",
                               # "automatic attempt exists", "duplicate request",
                               # "no events", "dispatch error", "not confirmed"

@dataclass(frozen=True, slots=True)
class WaitingRun:
    run_id: str
    text: str
    snapshot: DestinationSnapshot
    request_id: str
    awaiting_since: float          # history clock (wall) seconds

Offload = Callable[[Callable[[], T]], Awaitable[T]]   # runs OS calls on the one insertion/COM thread

class InsertionProtocol:
    def __init__(
        self,
        history: HistoryRepo,
        win32: Win32Api,
        uia: UiaApi,
        *,
        offload: Offload,                       # REQUIRED; tests pass an inline async runner
        clock: Callable[[], float],             # same wall clock as history (wait limit)
        new_id: Callable[[], str],              # attempt ids
        idle_threshold_ms: int = 1000,
        return_settle_ms: int = 300,
        wait_limit_s: float = 600.0,
        bring_forward_settle_s: float = 0.1,
        paste_settle_s: float = 0.5,
    ) -> None: ...

    async def attempt(
        self, run_id: str, text: str, snapshot: DestinationSnapshot, *,
        request_id: str, kind: Literal["automatic", "explicit"],
        is_cancelled: Callable[[], bool],
    ) -> ProtocolResult: ...
        # Immediate path (CODEMAP §4 steps 6-7, and explicit Insert/retry).

    async def deliver_next(
        self, waiting: Sequence[WaitingRun], *, is_cancelled: Callable[[str], bool],
    ) -> tuple[str, ProtocolResult] | None: ...
        # One hybrid-delivery tick. Considers ONLY the oldest run (smallest awaiting_since;
        # ties by input order). Returns None if `waiting` is empty, otherwise (run_id, result).
        # The caller removes a run from its waiting list when the result is not AWAITING.
```

All `attempt`/`deliver_next` calls are serialized by one `asyncio.Lock` (the single insertion
slot). Every Win32/UIA/insertion call (`verify`, `bring_forward`, `restore`, `dispatch`, `confirm`,
`win32.*`) runs inside `offload`, never directly on the event loop.

## Sequence (binding)

### `attempt` (immediate)
1. `is_cancelled()` → CANCELLED "cancelled" (no claim).
2. `verify(snapshot)`: `changed` → AWAITING "window changed". `closed` → HELD "window closed".
   `unverifiable` → HELD "unverifiable". None of these claim anything.
3. Claim via `history.claim_attempt(run_id, attempt_id=new_id(), request_id, kind,
   target=snapshot.to_json())`:
   - `ClaimResult.deduplicated` → DUPLICATE "duplicate request", with the existing attempt_id.
     No dispatch.
   - `WisprError(DUPLICATE_REQUEST)` → DUPLICATE "automatic attempt exists", attempt_id None.
   - `WisprError(RUN_EXPIRED | RUN_NOT_FOUND)` → ABANDONED "expired".
   - Any other exception → HELD "claim failed". No dispatch (T-PRO-001).
4. **Final recheck, immediately before dispatch.** Order: cancelled → resolve the attempt
   `cancelled`, return CANCELLED. Then run eligibility via `history.get(run_id)`: RUN_EXPIRED or
   NOT_FOUND → ABANDONED "expired" (the attempt row goes with the run; do not resolve it). Then
   `verify` must be `same`; otherwise resolve the attempt `failed` and return FAILED with that
   reason. That is a definite pre-dispatch failure (CODEMAP §4 step 7 → run `error`), and nothing
   was sent.
   - Why not AWAITING: the unique index allows one automatic attempt per run whatever its
     outcome, so the claim cannot be re-claimed automatically. Recovery is the explicit Insert.
   - Why not HELD: a held run has no insertion attempt (CODEMAP §4 step 6).
5. `dispatch(text, snapshot, ..., paste_settle_s)`. **Dispatch is the cancellation boundary.**
   From here on, cancellation is ignored.
   - dispatch raised → resolve `uncertain`, UNCERTAIN "dispatch error";
   - `events_accepted == 0` → resolve `failed`, FAILED "no events";
   - else `confirm` → `inserted`: resolve `inserted`, INSERTED ""; `uncertain`: resolve
     `uncertain`, UNCERTAIN "not confirmed".
   - Never retry, and never fall back to another strategy.
6. If `resolve_attempt` itself raises after dispatch, the result is still the observed outcome.
   The row stays `in_flight` and becomes `uncertain` at the next startup. Never re-dispatch.

### `deliver_next` (hybrid delivery, oldest only)
For the oldest waiting run `w`:
1. `is_cancelled(w.run_id)` → CANCELLED "cancelled" (T-PRO-015).
2. `clock() - w.awaiting_since > wait_limit_s` → HELD "wait limit".
3. `verify(w.snapshot)`: `closed` → HELD "window closed"; `unverifiable` → HELD "unverifiable".
4. **Return trigger:** `verify` is `same` (the user brought the window and tab back themselves).
   - `win32.idle_ms() < return_settle_ms` → AWAITING "window changed" (check again next tick).
   - Otherwise run `attempt` steps 3-5 with kind `automatic`. No focus change and no restore.
5. **Idle jump:** `verify` is `changed`.
   - `win32.idle_ms() < idle_threshold_ms` → AWAITING "window changed". Never jump while input
     is arriving.
   - Otherwise record `idle_start = win32.idle_ms()`, then
     `previous = bring_forward(w.snapshot, ..., settle_s=bring_forward_settle_s)`.
     If that is None → HELD "bring forward failed" (`bring_forward` has already restored).
   - `verify` must now be `same`, else `restore(previous)` and HELD with that reason
     ("window changed" counts as "unverifiable" here).
   - **Recheck idle:** `win32.idle_ms() < idle_start` means input arrived → `restore(previous)`,
     AWAITING "input during jump", **nothing claimed** (T-PRO-010).
   - Claim (step 3 above).
   - Final recheck: step 4 above, plus the idle recheck again. Idle reset after the claim →
     resolve `failed`, FAILED "input during jump".
   - Dispatch and confirm (step 5).
   - **`restore(previous)` on every path after a successful `bring_forward`, including dispatch
     errors** (use `finally`; T-PRO-011).

## Tests (Sol; IDs in function names)
- Use a real `HistoryRepo` on a temporary SQLite file via `wispr_clone.storage`, with a fake
  clock and a fake events sink.
- Use the promoted `tests/fakes/insertion.py` Win32/UIA fakes: controllable foreground, idle_ms
  sequence, is_window, `send_inputs` return, element text before/after.
- Use an inline `offload`. No real desktop.
- The idle clock is the fake's `idle_ms`.

The rows marked (int) are integration tests in `tests/integration/pipeline/`; the rest are unit
tests in `tests/unit/pipeline/`.

| ID | Assertion |
|---|---|
| T-PRO-001 | claim raises (e.g. history write fails) → HELD "claim failed", 0 `send_inputs` |
| T-PRO-002 | cancelled at the final recheck → no input, attempt resolved `cancelled`, CANCELLED |
| T-PRO-003 | user not in destination at step 2 → AWAITING, no attempt row, no input into the current window |
| T-PRO-004 | same request_id twice → exactly one dispatch; second returns DUPLICATE with the same attempt_id |
| T-PRO-005 (int) | subprocess: real SQLite file; `offload` calls `os._exit(1)` during the final recheck (after the claim). Parent reopens, `recover_on_startup` → attempt `uncertain`; the same request again → DUPLICATE, 0 dispatches |
| T-PRO-006 | dispatch raises → UNCERTAIN, attempt `uncertain`, no second dispatch or strategy |
| T-PRO-006b | read-back mismatch → UNCERTAIN "not confirmed"; accepted 0 → FAILED |
| T-PRO-007 | explicit retry with a new request_id after an automatic `uncertain` → new attempt, 1 new dispatch |
| T-PRO-008 | run expired (clock past 24 h) before the final recheck → ABANDONED, 0 dispatch |
| T-PRO-009 | idle jump only when `idle_ms >= idle_threshold_ms`; below it → AWAITING, no `set_foreground` |
| T-PRO-010 | `idle_ms` drops after `bring_forward` (input) → previous window restored, AWAITING "input during jump", no attempt row |
| T-PRO-011 | after an idle-jump dispatch (success AND dispatch error) → the user's previous window and tab are restored |
| T-PRO-012 | return trigger: foreground back on the destination and idle ≥ settle → exactly one dispatch; a second tick with the same WaitingRun → DUPLICATE, 0 dispatch |
| T-PRO-013 | closed window / unverifiable field / wait limit exceeded → HELD with the matching reason, no claim |
| T-PRO-014 | three waiting runs out of order → `deliver_next` touches only the oldest; after its removal the next oldest; never two dispatches in one tick |
| T-PRO-015 | cancelled while awaiting → CANCELLED, no claim, no dispatch |
| T-PRO-016 | concurrent `attempt` calls are serialized (the second starts its verify only after the first returns) |
| T-PRO-017 | privacy: text and titles never appear in caplog output or ProtocolResult.reason |

## Coordinator decisions after RED review

1. Return trigger: verify first, then the settle check. The order has no observable effect,
   because both must pass before any claim.
2. A destination change or idle reset detected after the claim → attempt `failed`, result FAILED
   (not HELD). HELD never carries a claimed attempt, matching CODEMAP §4 step 6. User cancel at
   the final recheck stays attempt `cancelled`, result CANCELLED.
3. Added tests: T-PRO-018 (destination changes between the claim and dispatch: the fake flips
   the foreground inside the final recheck → FAILED "window changed", attempt `failed`, 0 sends)
   and T-PRO-019 (idle jump, idle resets after the claim → FAILED "input during jump", attempt
   `failed`, previous window restored, 0 sends).
