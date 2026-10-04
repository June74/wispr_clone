"""Delayed delivery retains its original target when activation is unavailable."""

from dataclasses import replace
from pathlib import Path

import pytest
from unit.pipeline.test_insertion_protocol import _confirm, scenario

from wispr_clone.pipeline.insertion_protocol import ProtocolOutcome

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


async def test_delayed_cleanup_survives_denied_focus_and_pastes_once_on_return(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as s:
        # A hosted cleanup can finish after the user has moved to another app.
        s.clock.advance(25)
        s.win.foreground = 20
        s.win.switch_foreground = False
        s.uia.focused = (20, 2)
        waiting = s.waiting()
        initial = await s.attempt()
        assert initial.outcome == ProtocolOutcome.AWAITING
        denied = await s.protocol.deliver_next([waiting], is_cancelled=lambda _: False)
        assert denied is not None
        assert (denied[1].outcome, denied[1].reason, denied[1].attempt_id) == (
            ProtocolOutcome.AWAITING,
            "foreground unavailable",
            None,
        )
        assert not any(
            name in {"select_tab", "focus_element"} for name, *_ in s.uia.calls
        )
        assert not any(
            name in {"send_inputs", "set_clipboard"} for name, *_ in s.win.calls
        )
        assert await s.history.attempts(s.run_id) == ()
        for _ in range(3):
            s.clock.advance(1)
            pending = await s.protocol.deliver_next(
                [waiting], is_cancelled=lambda _: False
            )
            assert pending is not None
            assert pending[1].outcome == ProtocolOutcome.AWAITING
        assert s.jump_calls() == 1

        # The same app with a different field is not permission to paste there.
        s.win.foreground = 10
        s.uia.focused = (99, 99)
        wrong_field = await s.protocol.deliver_next(
            [waiting], is_cancelled=lambda _: False
        )
        assert wrong_field is not None
        assert wrong_field[1].outcome == ProtocolOutcome.AWAITING
        assert s.sends() == 0
        assert s.jump_calls() == 1

        s.uia.focused = s.snapshot.field
        s.win.idle_values = [100]
        settling = await s.protocol.deliver_next(
            [waiting], is_cancelled=lambda _: False
        )
        assert settling is not None
        assert settling[1].outcome == ProtocolOutcome.AWAITING
        assert s.sends() == 0
        _confirm(s)
        s.win.idle_values = [300]
        delivered = await s.protocol.deliver_next(
            [waiting], is_cancelled=lambda _: False
        )
        assert delivered is not None
        assert delivered[1].outcome == ProtocolOutcome.INSERTED
        repeated = await s.protocol.deliver_next(
            [waiting], is_cancelled=lambda _: False
        )
        assert repeated is not None
        assert repeated[1].outcome == ProtocolOutcome.DUPLICATE
        assert s.sends() == 1
        assert s.jump_calls() == 1
        assert len(await s.history.attempts(s.run_id)) == 1


@pytest.mark.parametrize("stop", ["cancel", "deadline", "closed", "unverifiable"])
async def test_denied_focus_still_honors_terminal_conditions(
    tmp_path: Path, stop: str
) -> None:
    async with scenario(tmp_path) as s:
        s.win.foreground = 20
        s.win.switch_foreground = False
        s.uia.focused = (20, 2)
        waiting = s.waiting()
        denied = await s.protocol.deliver_next([waiting], is_cancelled=lambda _: False)
        assert denied is not None
        assert denied[1].outcome == ProtocolOutcome.AWAITING
        if stop == "deadline":
            s.clock.advance(601)
        elif stop == "closed":
            s.win.windows.remove(10)
        elif stop == "unverifiable":
            s.win.foreground = 10
            s.uia.visible[s.snapshot.field] = False
        result = await s.protocol.deliver_next(
            [waiting], is_cancelled=lambda _: stop == "cancel"
        )
        assert result is not None
        assert result[1].outcome == (
            ProtocolOutcome.CANCELLED if stop == "cancel" else ProtocolOutcome.HELD
        )
        assert s.jump_calls() == 1
        assert s.sends() == 0
        assert await s.history.attempts(s.run_id) == ()


async def test_activation_suppression_is_scoped_to_waiting_operation(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as s:
        s.win.foreground = 20
        s.win.switch_foreground = False
        waiting = s.waiting()
        await s.protocol.deliver_next([waiting], is_cancelled=lambda _: False)
        renewed = replace(waiting, request_id="new-request")
        result = await s.protocol.deliver_next([renewed], is_cancelled=lambda _: False)
        assert result is not None
        assert result[1].outcome == ProtocolOutcome.AWAITING
        assert s.jump_calls() == 2
        assert s.sends() == 0
        assert await s.history.attempts(s.run_id) == ()
