# WO-M1 — Run state machine

```text
Work-order ID: WO-M1
Role file / requested model: RED + verify: sol-integration-test-author.md / gpt-6-sol
                             GREEN: luna-integration-programmer.md / gpt-6-luna
Pipeline branch or P0/M stage: M1, branch integ/m1-state-machine
Outcome and observable acceptance:
  A pure, synchronous state machine decides every legal run-status change, the cancellation
  boundary (dispatch begun) and the status-level recovery actions. It holds no I/O, no clock,
  no adapters. run_controller (M3) and insertion_protocol (M2) will call it.
Base revision / worktree / branch: 984ab46 / ~/projects/wc-m1 / integ/m1-state-machine
Relevant sections: CODEMAP.md §4 (normal path, hybrid delivery, recovery rules, insertion
  protocol and cancellation boundary), §5 (run status vs insertion outcome); feature spec
  "Text insertion", "Meaning-preserving cleanup"; dev_pipeline.md §8 row M1.
Prerequisites: P0 merged (contracts.run RunStatus/RecoveryAction, contracts.common WisprError).
Exact writable paths (under backend_dev/):
  Sol:  tests/unit/pipeline/** (new)
  Luna: src/wispr_clone/pipeline/__init__.py (docstring only),
        src/wispr_clone/pipeline/state_machine.py
Read-only: everything else.
Allowed imports: pipeline.state_machine -> contracts only (+ stdlib dataclasses, enum, typing).
Required tiers: S, U on ubuntu and windows.
Check commands (from backend_dev/, UV_LINK_MODE=copy):
  uv sync --locked; uv run ruff check .; uv run ruff format --check .;
  uv run mypy src scripts tests/_attribution tests/fakes; uv run python scripts/check_imports.py;
  uv run pytest -q -W error
Authorization: edit only writable paths; no git writes; no PRs; the coordinator commits, pushes,
  opens the PR.
Test independence rule: Sol builds the expected table in the TEST from this work order. Tests must
  not import TRANSITIONS or any table from the implementation to compute expectations.
Handoff: coordinator. Sol: RED command/output. Luna: GREEN outputs. Sol: verification findings.
```

## Pinned API (use these exact names)

```python
class RunEvent(StrEnum):
    STOP = "stop"                          # user stopped recording
    CANCEL = "cancel"                      # cancel shortcut/command
    FAIL = "fail"                          # mic/STT failure, no speech, definite pre-dispatch failure
    CLEANUP_FAILED = "cleanup_failed"      # cleanup failed OR guard rejected (reason is data, not here)
    RETRY_CLEANUP = "retry_cleanup"        # explicit recovery
    USE_ORIGINAL = "use_original"          # explicit recovery
    RETRY_STT = "retry_stt"                # explicit recovery (controller checks a WAV is retained)
    DESTINATION_AWAY = "destination_away"  # candidate ready, user switched away
    HOLD = "hold"                          # destination closed/unverifiable, wait limit, claim failed
    DISPATCH_BEGIN_AUTO = "dispatch_begin_auto"          # automatic OS dispatch starts
    DISPATCH_BEGIN_EXPLICIT = "dispatch_begin_explicit"  # user-requested insert starts
    INSERTED = "inserted"                  # confirmed (read-back ok)
    INSERT_FAILED = "insert_failed"        # definite failure after dispatch began
    INSERT_UNCERTAIN = "insert_uncertain"  # ambiguous / unreadable / mismatch

@dataclass(frozen=True, slots=True)
class RunState:
    status: RunStatus
    version: int
    dispatching: bool = False     # True from DISPATCH_BEGIN_* until an outcome event

class TransitionRejected(Exception):
    # Raised for an event that is not legal in the current state. Attributes: state, event.
    # str() names only status, dispatching and event (no user data exists here anyway).
    state: RunState
    event: RunEvent

def initial_state() -> RunState                # RunState(RunStatus.RECORDING, version=1)
def transition(state: RunState, event: RunEvent, *, expected_version: int | None = None) -> RunState
def is_terminal(state: RunState) -> bool       # True for done and cancelled
def allowed_recovery_actions(state: RunState) -> frozenset[RecoveryAction]
```

`transition` rules:

- If `expected_version` is given and differs from `state.version`: raise
  `WisprError(ErrorCode.STALE_VERSION, where="pipeline.state_machine", why=...)` BEFORE checking
  legality (T-SM-006).
- Legal event: return a NEW `RunState` with the target status, `version = state.version + 1`
  (every legal transition, including DISPATCH_BEGIN_*, increments), and `dispatching` as in the
  table. The input state is never modified.
- Illegal event: raise `TransitionRejected`; nothing changes.

## The transition table (the whole truth; everything not listed is illegal)

Not dispatching (`dispatching=False`):

| From status | Event | To status | dispatching after |
|---|---|---|---|
| recording | STOP | processing | False |
| recording | CANCEL | cancelled | False |
| recording | FAIL | error | False |
| processing | CANCEL | cancelled | False |
| processing | FAIL | error | False |
| processing | CLEANUP_FAILED | awaiting_cleanup_choice | False |
| processing | DESTINATION_AWAY | awaiting_destination | False |
| processing | HOLD | held | False |
| processing | DISPATCH_BEGIN_AUTO | processing | True |
| awaiting_cleanup_choice | RETRY_CLEANUP | processing | False |
| awaiting_cleanup_choice | USE_ORIGINAL | processing | False |
| awaiting_cleanup_choice | CANCEL | cancelled | False |
| awaiting_destination | DISPATCH_BEGIN_AUTO | awaiting_destination | True |
| awaiting_destination | DISPATCH_BEGIN_EXPLICIT | awaiting_destination | True |
| awaiting_destination | HOLD | held | False |
| awaiting_destination | CANCEL | cancelled | False |
| held | DISPATCH_BEGIN_EXPLICIT | held | True |
| error | RETRY_STT | processing | False |
| error | DISPATCH_BEGIN_EXPLICIT | error | True |
| uncertain | DISPATCH_BEGIN_EXPLICIT | uncertain | True |
| done | (nothing) | | |
| cancelled | (nothing) | | |

Dispatching (`dispatching=True`; only reachable in processing, awaiting_destination, held, error,
uncertain), for every such status:

| Event | To status | dispatching after |
|---|---|---|
| INSERTED | done | False |
| INSERT_FAILED | error | False |
| INSERT_UNCERTAIN | uncertain | False |
| anything else, including CANCEL | rejected (`TransitionRejected`) | unchanged |

Why these rows (for Sol's test docstrings): the idle jump that is aborted because input arrived
never begins dispatch, so it needs no event; a claim that fails before dispatch is HOLD (from
awaiting_destination) or FAIL (from processing); "insert elsewhere" while waiting is
DISPATCH_BEGIN_EXPLICIT; eviction deletes the run rather than transitioning it (M3e).

`allowed_recovery_actions` (status level; the run controller later removes actions whose data is
missing, e.g. retry_stt without a WAV). While `dispatching` is True: empty set.

| Status | Actions |
|---|---|
| recording, processing | none |
| awaiting_cleanup_choice | retry_cleanup, use_original, copy |
| awaiting_destination | insert, copy |
| held | insert, copy |
| error | retry_stt, insert, copy |
| uncertain | insert, copy |
| done | copy |
| cancelled | copy |

## Tests (Sol, tests/unit/pipeline/test_state_machine.py; `@pytest.mark.unit`)

| ID | Must assert |
|---|---|
| **T-SM-001** (invariant) | exhaustive, parametrized over every (status × dispatching × event) combination, with the expected result written out in the test from the tables above: legal → exact target status, dispatching flag and version+1; illegal → `TransitionRejected` and the state unchanged. Unreachable dispatching states (recording, awaiting_cleanup_choice, done, cancelled with dispatching=True) are still checked: every event is rejected there |
| **T-SM-002** (invariant) | from awaiting_cleanup_choice no DISPATCH_BEGIN_* is legal; the only paths to dispatch pass through RETRY_CLEANUP or USE_ORIGINAL (a reachability search over the test's own table from awaiting_cleanup_choice that forbids those two events never reaches dispatching=True) |
| **T-SM-003** (invariant) | held rejects DISPATCH_BEGIN_AUTO (no automatic attempt); only DISPATCH_BEGIN_EXPLICIT leaves held |
| **T-SM-004** (invariant) | for every dispatching state, CANCEL raises `TransitionRejected` and no sequence of events after DISPATCH_BEGIN_* reaches cancelled |
| T-SM-005 | a realistic path (recording → processing → awaiting_destination → dispatching → done) increments version by exactly 1 per step starting from `initial_state().version == 1`; inputs are not mutated (frozen dataclass) |
| **T-SM-006** (invariant) | `expected_version` mismatch → `WisprError` with `STALE_VERSION`, even for an otherwise illegal event; matching version → normal result |
| **T-SM-007** (invariant) | awaiting_destination (not dispatching) accepts exactly {DISPATCH_BEGIN_AUTO, DISPATCH_BEGIN_EXPLICIT, HOLD, CANCEL} |
| T-SM-008 | `allowed_recovery_actions` equals the table for every status, is empty while dispatching; `is_terminal` is True exactly for done and cancelled |
</content>

## Coordinator decisions after RED review

1. T-SM-004 wording corrected. The invariant is the cancellation boundary of ONE dispatch: while
   `dispatching` is True, CANCEL is rejected, and the only exits are the three outcome events
   (INSERTED, INSERT_FAILED, INSERT_UNCERTAIN), so an in-flight dispatch can never end as
   cancelled. After an outcome is recorded, a later explicit recovery (e.g. error → RETRY_STT →
   processing → CANCEL) is a new operation and may be cancelled; that is not a contradiction.
   Sol's RED assertion (in-flight CANCEL rejected; exits only via outcomes) is accepted as is.
