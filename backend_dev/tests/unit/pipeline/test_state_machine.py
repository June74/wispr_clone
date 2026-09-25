"""WO-M1's public run-state transitions and status-level recovery contract."""

from dataclasses import FrozenInstanceError
from itertools import product

import pytest

from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.contracts.run import RecoveryAction, RunStatus

# Expected values are transcribed from WO-M1, independently of the implementation.
# Every absent (status, event) pair is illegal when dispatching is False.
EXPECTED_IDLE: dict[tuple[RunStatus, str], tuple[RunStatus, bool]] = {
    (RunStatus.RECORDING, "stop"): (RunStatus.PROCESSING, False),
    (RunStatus.RECORDING, "cancel"): (RunStatus.CANCELLED, False),
    (RunStatus.RECORDING, "fail"): (RunStatus.ERROR, False),
    (RunStatus.PROCESSING, "cancel"): (RunStatus.CANCELLED, False),
    (RunStatus.PROCESSING, "fail"): (RunStatus.ERROR, False),
    (RunStatus.PROCESSING, "cleanup_failed"): (
        RunStatus.AWAITING_CLEANUP_CHOICE,
        False,
    ),
    (RunStatus.PROCESSING, "destination_away"): (
        RunStatus.AWAITING_DESTINATION,
        False,
    ),
    (RunStatus.PROCESSING, "hold"): (RunStatus.HELD, False),
    (RunStatus.PROCESSING, "dispatch_begin_auto"): (RunStatus.PROCESSING, True),
    (RunStatus.AWAITING_CLEANUP_CHOICE, "retry_cleanup"): (
        RunStatus.PROCESSING,
        False,
    ),
    (RunStatus.AWAITING_CLEANUP_CHOICE, "use_original"): (
        RunStatus.PROCESSING,
        False,
    ),
    (RunStatus.AWAITING_CLEANUP_CHOICE, "cancel"): (RunStatus.CANCELLED, False),
    (RunStatus.AWAITING_DESTINATION, "dispatch_begin_auto"): (
        RunStatus.AWAITING_DESTINATION,
        True,
    ),
    (RunStatus.AWAITING_DESTINATION, "dispatch_begin_explicit"): (
        RunStatus.AWAITING_DESTINATION,
        True,
    ),
    (RunStatus.AWAITING_DESTINATION, "hold"): (RunStatus.HELD, False),
    (RunStatus.AWAITING_DESTINATION, "cancel"): (RunStatus.CANCELLED, False),
    (RunStatus.HELD, "dispatch_begin_explicit"): (RunStatus.HELD, True),
    (RunStatus.ERROR, "retry_stt"): (RunStatus.PROCESSING, False),
    (RunStatus.ERROR, "dispatch_begin_explicit"): (RunStatus.ERROR, True),
    (RunStatus.UNCERTAIN, "dispatch_begin_explicit"): (RunStatus.UNCERTAIN, True),
}

DISPATCHABLE = frozenset(
    {
        RunStatus.PROCESSING,
        RunStatus.AWAITING_DESTINATION,
        RunStatus.HELD,
        RunStatus.ERROR,
        RunStatus.UNCERTAIN,
    }
)
EXPECTED_OUTCOMES = {
    "inserted": (RunStatus.DONE, False),
    "insert_failed": (RunStatus.ERROR, False),
    "insert_uncertain": (RunStatus.UNCERTAIN, False),
}
EXPECTED_RECOVERY = {
    RunStatus.RECORDING: frozenset(),
    RunStatus.PROCESSING: frozenset(),
    RunStatus.AWAITING_CLEANUP_CHOICE: frozenset(
        {RecoveryAction.RETRY_CLEANUP, RecoveryAction.USE_ORIGINAL, RecoveryAction.COPY}
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
EVENT_NAMES = (
    "stop",
    "cancel",
    "fail",
    "cleanup_failed",
    "retry_cleanup",
    "use_original",
    "retry_stt",
    "destination_away",
    "hold",
    "dispatch_begin_auto",
    "dispatch_begin_explicit",
    "inserted",
    "insert_failed",
    "insert_uncertain",
)


@pytest.fixture
def sm():  # type: ignore[no-untyped-def]
    # Import at execution time so pytest still collects every RED case before M1 exists.
    from wispr_clone.pipeline import state_machine

    return state_machine


@pytest.mark.unit
@pytest.mark.invariant("The WO-M1 table is exhaustive, including unreachable states")
@pytest.mark.parametrize(
    ("status", "dispatching", "event_name"),
    [
        pytest.param(
            status, dispatching, event, id=f"{status.value}-{dispatching}-{event}"
        )
        for status, dispatching, event in product(RunStatus, (False, True), EVENT_NAMES)
    ],
)
def test_T_SM_001_exhaustive_transitions(sm, status, dispatching, event_name) -> None:
    assert {event.value for event in sm.RunEvent} == set(EVENT_NAMES)
    state = sm.RunState(status, version=41, dispatching=dispatching)
    event = sm.RunEvent(event_name)
    expected = (
        EXPECTED_OUTCOMES.get(event_name)
        if dispatching and status in DISPATCHABLE
        else EXPECTED_IDLE.get((status, event_name))
        if not dispatching
        else None
    )

    if expected is None:
        with pytest.raises(sm.TransitionRejected) as rejected:
            sm.transition(state, event)
        assert rejected.value.state is state
        assert rejected.value.event is event
        diagnostic = str(rejected.value).lower()
        assert status.value in diagnostic
        assert str(dispatching).lower() in diagnostic
        assert event.value in diagnostic
        assert state == sm.RunState(status, version=41, dispatching=dispatching)
    else:
        result = sm.transition(state, event)
        assert result == sm.RunState(expected[0], version=42, dispatching=expected[1])
        assert result is not state
        assert state == sm.RunState(status, version=41, dispatching=dispatching)


@pytest.mark.unit
@pytest.mark.invariant("Cleanup choice requires an explicit decision before dispatch")
def test_T_SM_002_cleanup_choice_blocks_dispatch_until_recovery(sm) -> None:
    start = sm.RunState(RunStatus.AWAITING_CLEANUP_CHOICE, version=1)
    for name in ("dispatch_begin_auto", "dispatch_begin_explicit"):
        with pytest.raises(sm.TransitionRejected):
            sm.transition(start, sm.RunEvent(name))

    # Reachability is calculated solely from the expected WO-M1 table.
    seen = {(RunStatus.AWAITING_CLEANUP_CHOICE, False)}
    pending = list(seen)
    while pending:
        status, dispatching = pending.pop()
        assert not dispatching
        for (source, name), target in EXPECTED_IDLE.items():
            if source == status and name not in {"retry_cleanup", "use_original"}:
                if target not in seen:
                    seen.add(target)
                    pending.append(target)

    for name in ("retry_cleanup", "use_original"):
        processing = sm.transition(start, sm.RunEvent(name))
        assert processing.status is RunStatus.PROCESSING
        assert sm.transition(processing, sm.RunEvent.DISPATCH_BEGIN_AUTO).dispatching


@pytest.mark.unit
@pytest.mark.invariant("Held results need a user-requested insertion")
def test_T_SM_003_held_rejects_automatic_dispatch(sm) -> None:
    held = sm.RunState(RunStatus.HELD, version=3)
    with pytest.raises(sm.TransitionRejected):
        sm.transition(held, sm.RunEvent.DISPATCH_BEGIN_AUTO)
    assert sm.transition(held, sm.RunEvent.DISPATCH_BEGIN_EXPLICIT) == sm.RunState(
        RunStatus.HELD, version=4, dispatching=True
    )


@pytest.mark.unit
@pytest.mark.invariant("Cancel cannot retract a dispatch already in flight")
@pytest.mark.parametrize(
    "status", sorted(DISPATCHABLE, key=lambda item: item.value), ids=str
)
def test_T_SM_004_dispatching_rejects_cancel(sm, status) -> None:
    state = sm.RunState(status, version=8, dispatching=True)
    with pytest.raises(sm.TransitionRejected):
        sm.transition(state, sm.RunEvent.CANCEL)
    assert state == sm.RunState(status, version=8, dispatching=True)
    for name in EVENT_NAMES:
        if name not in EXPECTED_OUTCOMES:
            with pytest.raises(sm.TransitionRejected):
                sm.transition(state, sm.RunEvent(name))


@pytest.mark.unit
def test_T_SM_005_path_increments_version_and_preserves_inputs(sm) -> None:
    state = sm.initial_state()
    assert state == sm.RunState(RunStatus.RECORDING, version=1, dispatching=False)
    with pytest.raises(FrozenInstanceError):
        state.version = 99
    steps = (
        (sm.RunEvent.STOP, RunStatus.PROCESSING, False),
        (sm.RunEvent.DESTINATION_AWAY, RunStatus.AWAITING_DESTINATION, False),
        (sm.RunEvent.DISPATCH_BEGIN_AUTO, RunStatus.AWAITING_DESTINATION, True),
        (sm.RunEvent.INSERTED, RunStatus.DONE, False),
    )
    for event, status, dispatching in steps:
        previous = state
        state = sm.transition(state, event, expected_version=previous.version)
        assert state == sm.RunState(status, previous.version + 1, dispatching)
        assert previous.version == state.version - 1


@pytest.mark.unit
@pytest.mark.invariant("Staleness takes precedence over event legality")
@pytest.mark.parametrize("event_name", ["stop", "inserted"], ids=["legal", "illegal"])
def test_T_SM_006_stale_version_precedes_legality(sm, event_name) -> None:
    state = sm.RunState(RunStatus.RECORDING, version=7)
    event = sm.RunEvent(event_name)
    with pytest.raises(WisprError) as stale:
        sm.transition(state, event, expected_version=6)
    assert stale.value.error_code is ErrorCode.STALE_VERSION
    assert stale.value.where == "pipeline.state_machine"
    assert state == sm.RunState(RunStatus.RECORDING, version=7)
    if event_name == "stop":
        assert sm.transition(state, event, expected_version=7) == sm.RunState(
            RunStatus.PROCESSING, version=8
        )
    else:
        with pytest.raises(sm.TransitionRejected):
            sm.transition(state, event, expected_version=7)


@pytest.mark.unit
@pytest.mark.invariant("Waiting has exactly four legal events")
def test_T_SM_007_awaiting_destination_event_set(sm) -> None:
    state = sm.RunState(RunStatus.AWAITING_DESTINATION, version=5)
    legal = {"dispatch_begin_auto", "dispatch_begin_explicit", "hold", "cancel"}
    accepted = set()
    for name in EVENT_NAMES:
        event = sm.RunEvent(name)
        try:
            sm.transition(state, event)
        except sm.TransitionRejected:
            continue
        accepted.add(name)
    assert accepted == legal


@pytest.mark.unit
@pytest.mark.parametrize(
    ("status", "dispatching"),
    [
        pytest.param(status, dispatching, id=f"{status.value}-{dispatching}")
        for status, dispatching in product(RunStatus, (False, True))
    ],
)
def test_T_SM_008_recovery_and_terminal_status(sm, status, dispatching) -> None:
    state = sm.RunState(status, version=1, dispatching=dispatching)
    expected = frozenset() if dispatching else EXPECTED_RECOVERY[status]
    assert sm.allowed_recovery_actions(state) == expected
    assert sm.is_terminal(state) is (status in {RunStatus.DONE, RunStatus.CANCELLED})


@pytest.mark.unit
@pytest.mark.invariant("Callers cannot change the legal transition table")
def test_T_SM_001_public_transitions_cannot_authorize_cancel_during_dispatch(
    sm,
) -> None:
    state = sm.RunState(RunStatus.HELD, version=3, dispatching=True)
    key = (RunStatus.HELD, True, sm.RunEvent.CANCEL)
    assert key not in sm.TRANSITIONS
    try:
        with pytest.raises(TypeError):
            sm.TRANSITIONS[key] = (RunStatus.CANCELLED, False)
    finally:
        # Keep the exhaustive matrix independent if a mutable implementation fails.
        if key in sm.TRANSITIONS:
            del sm.TRANSITIONS[key]
    with pytest.raises(sm.TransitionRejected):
        sm.transition(state, sm.RunEvent.CANCEL)


@pytest.mark.unit
@pytest.mark.invariant("Only RunEvent members can authorize state changes")
def test_T_SM_001_plain_string_cannot_begin_automatic_dispatch(sm) -> None:
    state = sm.RunState(RunStatus.PROCESSING, version=3)
    with pytest.raises((TypeError, ValueError, sm.TransitionRejected)):
        sm.transition(state, "dispatch_begin_auto")
    assert state == sm.RunState(RunStatus.PROCESSING, version=3)


@pytest.mark.unit
@pytest.mark.invariant("Boolean command versions cannot bypass stale-version rejection")
def test_T_SM_006_boolean_expected_version_is_not_current_version(sm) -> None:
    state = sm.initial_state()
    with pytest.raises(WisprError) as stale:
        sm.transition(state, sm.RunEvent.STOP, expected_version=True)
    assert stale.value.error_code is ErrorCode.STALE_VERSION
    assert state == sm.RunState(RunStatus.RECORDING, version=1)


@pytest.mark.unit
@pytest.mark.invariant("Run versions start at one and remain positive")
def test_T_SM_005_negative_state_version_cannot_transition_to_zero(sm) -> None:
    state = sm.RunState(RunStatus.RECORDING, version=-1)
    with pytest.raises((TypeError, ValueError, WisprError)):
        sm.transition(state, sm.RunEvent.STOP)
    assert state.version == -1
