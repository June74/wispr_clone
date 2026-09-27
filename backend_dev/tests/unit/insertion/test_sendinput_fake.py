"""T-INS-SI-003: insertion's fake preserves its accepted-count behavior."""

from fakes.insertion import FakeWin32Api

from wispr_clone.insertion.win32 import KeyEvent


def test_T_INS_SI_003_fake_send_inputs_records_and_returns_count() -> None:
    events = (KeyEvent(vk=0xFF, flags=0x0002), KeyEvent(vk=0xFF, flags=0x0002))
    win32 = FakeWin32Api()

    assert win32.send_inputs(events) == 2
    assert win32.calls == [("send_inputs", (events,), {})]

    win32.accepted = 0
    assert win32.send_inputs(events) == 0
    assert win32.calls[-1] == ("send_inputs", (events,), {})
