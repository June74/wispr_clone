"""Pure, synchronous run-state transitions and recovery decisions."""

from dataclasses import dataclass
from enum import StrEnum

from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.contracts.run import RecoveryAction, RunStatus


class RunEvent(StrEnum):
    """Events accepted by the run lifecycle state machine."""

    STOP = "stop"
    CANCEL = "cancel"
    FAIL = "fail"
    CLEANUP_FAILED = "cleanup_failed"
    RETRY_CLEANUP = "retry_cleanup"
    USE_ORIGINAL = "use_original"
    RETRY_STT = "retry_stt"
    DESTINATION_AWAY = "destination_away"
    HOLD = "hold"
    DISPATCH_BEGIN_AUTO = "dispatch_begin_auto"
    DISPATCH_BEGIN_EXPLICIT = "dispatch_begin_explicit"
    INSERTED = "inserted"
    INSERT_FAILED = "insert_failed"
    INSERT_UNCERTAIN = "insert_uncertain"


@dataclass(frozen=True, slots=True)
class RunState:
    """Immutable status snapshot, versioned for stale-command rejection."""

    status: RunStatus
    version: int
    dispatching: bool = False


class TransitionRejected(Exception):
    """Raised when an event is absent from the transition table."""

    def __init__(self, state: RunState, event: RunEvent) -> None:
        self.state = state
        self.event = event
        super().__init__(
            f"transition rejected: status={state.status.value}, "
            f"dispatching={state.dispatching}, event={event.value}"
        )


# Each entry gives (status, dispatching, event) -> (next status, next dispatching).
# Missing entries are illegal. Dispatch outcomes are shared by every reachable
# in-flight status; unreachable in-flight combinations intentionally have no rows.
TRANSITIONS: dict[tuple[RunStatus, bool, RunEvent], tuple[RunStatus, bool]] = {
    (RunStatus.RECORDING, False, RunEvent.STOP): (RunStatus.PROCESSING, False),
    (RunStatus.RECORDING, False, RunEvent.CANCEL): (RunStatus.CANCELLED, False),
    (RunStatus.RECORDING, False, RunEvent.FAIL): (RunStatus.ERROR, False),
    (RunStatus.PROCESSING, False, RunEvent.CANCEL): (RunStatus.CANCELLED, False),
    (RunStatus.PROCESSING, False, RunEvent.FAIL): (RunStatus.ERROR, False),
    (RunStatus.PROCESSING, False, RunEvent.CLEANUP_FAILED): (
        RunStatus.AWAITING_CLEANUP_CHOICE,
        False,
    ),
    (RunStatus.PROCESSING, False, RunEvent.DESTINATION_AWAY): (
        RunStatus.AWAITING_DESTINATION,
        False,
    ),
    (RunStatus.PROCESSING, False, RunEvent.HOLD): (RunStatus.HELD, False),
    (RunStatus.PROCESSING, False, RunEvent.DISPATCH_BEGIN_AUTO): (
        RunStatus.PROCESSING,
        True,
    ),
    (RunStatus.AWAITING_CLEANUP_CHOICE, False, RunEvent.RETRY_CLEANUP): (
        RunStatus.PROCESSING,
        False,
    ),
    (RunStatus.AWAITING_CLEANUP_CHOICE, False, RunEvent.USE_ORIGINAL): (
        RunStatus.PROCESSING,
        False,
    ),
    (RunStatus.AWAITING_CLEANUP_CHOICE, False, RunEvent.CANCEL): (
        RunStatus.CANCELLED,
        False,
    ),
    (RunStatus.AWAITING_DESTINATION, False, RunEvent.DISPATCH_BEGIN_AUTO): (
        RunStatus.AWAITING_DESTINATION,
        True,
    ),
    (RunStatus.AWAITING_DESTINATION, False, RunEvent.DISPATCH_BEGIN_EXPLICIT): (
        RunStatus.AWAITING_DESTINATION,
        True,
    ),
    (RunStatus.AWAITING_DESTINATION, False, RunEvent.HOLD): (RunStatus.HELD, False),
    (RunStatus.AWAITING_DESTINATION, False, RunEvent.CANCEL): (
        RunStatus.CANCELLED,
        False,
    ),
    (RunStatus.HELD, False, RunEvent.DISPATCH_BEGIN_EXPLICIT): (RunStatus.HELD, True),
    (RunStatus.ERROR, False, RunEvent.RETRY_STT): (RunStatus.PROCESSING, False),
    (RunStatus.ERROR, False, RunEvent.DISPATCH_BEGIN_EXPLICIT): (RunStatus.ERROR, True),
    (RunStatus.UNCERTAIN, False, RunEvent.DISPATCH_BEGIN_EXPLICIT): (
        RunStatus.UNCERTAIN,
        True,
    ),
    **{
        (status, True, event): (target, False)
        for status in (
            RunStatus.PROCESSING,
            RunStatus.AWAITING_DESTINATION,
            RunStatus.HELD,
            RunStatus.ERROR,
            RunStatus.UNCERTAIN,
        )
        for event, target in (
            (RunEvent.INSERTED, RunStatus.DONE),
            (RunEvent.INSERT_FAILED, RunStatus.ERROR),
            (RunEvent.INSERT_UNCERTAIN, RunStatus.UNCERTAIN),
        )
    },
}

_RECOVERY_ACTIONS: dict[RunStatus, frozenset[RecoveryAction]] = {
    RunStatus.RECORDING: frozenset(),
    RunStatus.PROCESSING: frozenset(),
    RunStatus.AWAITING_CLEANUP_CHOICE: frozenset(
        {
            RecoveryAction.RETRY_CLEANUP,
            RecoveryAction.USE_ORIGINAL,
            RecoveryAction.COPY,
        }
    ),
    RunStatus.AWAITING_DESTINATION: frozenset(
        {RecoveryAction.INSERT, RecoveryAction.COPY}
    ),
    RunStatus.HELD: frozenset({RecoveryAction.INSERT, RecoveryAction.COPY}),
    RunStatus.ERROR: frozenset(
        {RecoveryAction.RETRY_STT, RecoveryAction.INSERT, RecoveryAction.COPY}
    ),
    RunStatus.UNCERTAIN: frozenset({RecoveryAction.INSERT, RecoveryAction.COPY}),
    RunStatus.DONE: frozenset({RecoveryAction.COPY}),
    RunStatus.CANCELLED: frozenset({RecoveryAction.COPY}),
}


def initial_state() -> RunState:
    """Return the first state of a newly recording run."""
    return RunState(RunStatus.RECORDING, version=1)


def transition(
    state: RunState,
    event: RunEvent,
    *,
    expected_version: int | None = None,
) -> RunState:
    """Apply one listed transition, or raise for stale or illegal input."""
    if expected_version is not None and expected_version != state.version:
        raise WisprError(
            ErrorCode.STALE_VERSION,
            where="pipeline.state_machine",
            why="run state version does not match",
        )

    target = TRANSITIONS.get((state.status, state.dispatching, event))
    if target is None:
        raise TransitionRejected(state, event)
    return RunState(target[0], version=state.version + 1, dispatching=target[1])


def is_terminal(state: RunState) -> bool:
    """Return whether the run has reached a terminal status."""
    return state.status in {RunStatus.DONE, RunStatus.CANCELLED}


def allowed_recovery_actions(state: RunState) -> frozenset[RecoveryAction]:
    """Return status-level recovery actions, suppressing them during dispatch."""
    if state.dispatching:
        return frozenset()
    return _RECOVERY_ACTIONS[state.status]
