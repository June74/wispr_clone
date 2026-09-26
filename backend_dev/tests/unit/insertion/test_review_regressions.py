"""T-INS review regressions using only in-memory desktop boundaries."""

from dataclasses import replace

import pytest

from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.insertion.destination import DestinationSnapshot, capture
from wispr_clone.insertion.inserter import (
    PreviousFocus,
    bring_forward,
    dispatch,
    restore,
)
from wispr_clone.insertion.verifier import verify

from .fake_apis import FakeUiaApi, FakeWin32Api


def _paste_snapshot() -> DestinationSnapshot:
    return replace(capture(FakeWin32Api(), FakeUiaApi()), langid=0x0412)


class DelayedPasteWin32(FakeWin32Api):
    def __init__(self, uia: FakeUiaApi) -> None:
        super().__init__(clipboard="user's old text")
        self.uia = uia
        self.queued = False
        self.pasted: list[str | None] = []

    def send_inputs(self, inputs: object) -> int:
        self.queued = True
        return super().send_inputs(inputs)

    def apply_queued_paste(self) -> None:
        if self.queued:
            self.pasted.append(self.clipboard)
            self.uia.texts[(1, 2)] = "before " + str(self.clipboard)
            self.queued = False


def test_T_INS_013_clipboard_held_until_delayed_paste_lands() -> None:
    uia = FakeUiaApi()
    win = DelayedPasteWin32(uia)
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        assert win.clipboard == "dictation"
        if len(sleeps) == 3:
            win.apply_queued_paste()

    result = dispatch(
        "dictation", _paste_snapshot(), win, uia, paste_settle_s=0.5, sleep=sleep
    )
    assert result.strategy == "paste"
    assert len(sleeps) >= 3
    assert win.pasted == ["dictation"]
    assert uia.texts[(1, 2)] == "before dictation"
    assert win.clipboard == "user's old text"


def test_T_INS_013_restores_clipboard_by_settle_deadline_if_paste_never_lands() -> None:
    uia = FakeUiaApi()
    win = DelayedPasteWin32(uia)
    elapsed = [0.0]

    def sleep(seconds: float) -> None:
        assert win.clipboard == "dictation"
        elapsed[0] += seconds

    dispatch("dictation", _paste_snapshot(), win, uia, paste_settle_s=0.2, sleep=sleep)
    assert 0.2 <= elapsed[0] <= 0.21
    assert win.clipboard == "user's old text"
    assert win.pasted == []


@pytest.mark.parametrize("failure", ["foreground", "tab", "field", "settle"])
def test_T_INS_014_bring_forward_failure_restores_previous_focus(failure: str) -> None:
    class FailingUia(FakeUiaApi):
        def select_tab(self, hwnd: int, tab: tuple[int, ...]) -> bool:
            if failure == "tab" and hwnd == 10:
                return False
            return super().select_tab(hwnd, tab)

        def focus_element(self, rid: tuple[int, ...]) -> bool:
            if failure == "field":
                return False
            return super().focus_element(rid)

        def focused_element(self) -> tuple[int, ...] | None:
            if failure == "settle":
                return (99, 99)
            return super().focused_element()

    win = FakeWin32Api(foreground=20, switch_foreground=failure != "foreground")
    uia = FailingUia(focused=(20, 2))
    now = [0.0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    assert (
        bring_forward(
            _paste_snapshot(),
            win,
            uia,
            timeout_s=0.03,
            sleep=sleep,
            clock=lambda: now[0],
        )
        is None
    )
    assert win.foreground == 20
    assert ("select_tab", (20, (20, 1))) in uia.calls


def test_T_INS_007_rejects_desktop_foreground_before_querying_its_process() -> None:
    win, uia = FakeWin32Api(foreground=0), FakeUiaApi()
    with pytest.raises(WisprError) as error:
        capture(win, uia)
    assert error.value.error_code == ErrorCode.DESTINATION_UNVERIFIABLE
    assert error.value.where == "insertion"
    assert error.value.why == "no window"
    assert not any(name == "window_process" for name, *_ in win.calls)


def test_T_INS_007_rejects_excluded_foreground_process() -> None:
    win, uia = FakeWin32Api(), FakeUiaApi()
    with pytest.raises(WisprError) as error:
        capture(win, uia, exclude_pids=frozenset({101}))
    assert error.value.error_code == ErrorCode.DESTINATION_UNVERIFIABLE
    assert error.value.where == "insertion"
    assert error.value.why == "own window"
    assert not any(
        name in {"window_title", "keyboard_layout"} for name, *_ in win.calls
    )
    assert uia.calls == []


@pytest.mark.parametrize(
    "change",
    [
        {"extra": "unexpected"},
        {"hwnd": True},
        {"pid": 1.0},
        {"langid": "0x409"},
        {"field": [True]},
    ],
)
def test_T_INS_007_from_json_rejects_extra_keys_and_wrong_types(
    change: dict[str, object],
) -> None:
    data = capture(FakeWin32Api(), FakeUiaApi()).to_json()
    data.update(change)
    with pytest.raises(WisprError) as error:
        DestinationSnapshot.from_json(data)
    assert error.value.error_code == ErrorCode.VALIDATION


def test_T_INS_008_restore_skips_closed_previous_window() -> None:
    win, uia = FakeWin32Api(foreground=10, windows={10}), FakeUiaApi()
    restore(PreviousFocus(20, (20, 1)), win, uia)
    assert win.foreground == 10
    assert not any(name == "set_foreground" for name, *_ in win.calls)


@pytest.mark.parametrize(
    "operation", ["is_on_screen", "selected_tab", "focused_element"]
)
def test_T_INS_002_uia_failure_is_unverifiable(operation: str) -> None:
    class RaisingUia(FakeUiaApi):
        def is_on_screen(self, rid: tuple[int, ...]) -> bool:
            if operation == "is_on_screen":
                raise OSError("synthetic UIA failure")
            return super().is_on_screen(rid)

        def selected_tab(self, hwnd: int) -> tuple[int, ...] | None:
            if operation == "selected_tab":
                raise OSError("synthetic UIA failure")
            return super().selected_tab(hwnd)

        def focused_element(self) -> tuple[int, ...] | None:
            if operation == "focused_element":
                raise OSError("synthetic UIA failure")
            return super().focused_element()

    win = FakeWin32Api()
    snapshot = capture(win, FakeUiaApi())
    assert verify(snapshot, win, RaisingUia()).status == "unverifiable"
