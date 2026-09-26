"""WO-M3a protocol outcomes mapped to lifecycle events."""

import pytest
from wispr_clone.pipeline.run_controller import events_for

from wispr_clone.pipeline.insertion_protocol import ProtocolOutcome, ProtocolResult
from wispr_clone.pipeline.state_machine import RunEvent


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (ProtocolOutcome.INSERTED, (RunEvent.DISPATCH_BEGIN_AUTO, RunEvent.INSERTED)),
        (
            ProtocolOutcome.UNCERTAIN,
            (RunEvent.DISPATCH_BEGIN_AUTO, RunEvent.INSERT_UNCERTAIN),
        ),
        (
            ProtocolOutcome.FAILED,
            (RunEvent.DISPATCH_BEGIN_AUTO, RunEvent.INSERT_FAILED),
        ),
        (ProtocolOutcome.AWAITING, (RunEvent.DESTINATION_AWAY,)),
        (ProtocolOutcome.HELD, (RunEvent.HOLD,)),
        (ProtocolOutcome.CANCELLED, (RunEvent.CANCEL,)),
        (ProtocolOutcome.ABANDONED, ()),
        (ProtocolOutcome.DUPLICATE, ()),
    ],
)
def test_T_RUN_001c_events_for_exact_mapping(
    outcome: ProtocolOutcome, expected: tuple[RunEvent, ...]
) -> None:
    assert events_for(ProtocolResult(outcome, None, "")) == expected
