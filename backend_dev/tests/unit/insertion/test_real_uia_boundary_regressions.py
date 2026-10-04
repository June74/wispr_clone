"""RealUia regressions exercised with in-memory controls, without COM."""

from types import SimpleNamespace
from typing import Any

import pytest

from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.insertion import uia as uia_module
from wispr_clone.insertion.destination import capture
from wispr_clone.insertion.verifier import verify

from .fake_apis import FakeWin32Api


def _real_uia(monkeypatch: Any, automation: Any) -> uia_module.RealUia:
    monkeypatch.setattr(uia_module.sys, "platform", "win32")
    monkeypatch.setattr(uia_module.importlib, "import_module", lambda _: automation)
    return uia_module.RealUia()


def test_T_INS_015_focused_control_is_read_directly_from_cache(
    monkeypatch: Any,
) -> None:
    class FocusedControl:
        ControlTypeName = "DocumentControl"
        IsOffscreen = False

        def GetRuntimeId(self) -> list[int]:
            return [4, 5, 6]

        def GetValuePattern(self) -> Any:
            return SimpleNamespace(Value="synthetic value")

    def no_desktop_walk() -> None:
        raise AssertionError("focused control must be read from the cache")

    automation = SimpleNamespace(
        GetFocusedControl=FocusedControl,
        GetRootControl=no_desktop_walk,
    )
    uia = _real_uia(monkeypatch, automation)
    rid = uia.focused_element()
    assert rid == (4, 5, 6)
    assert uia.element_control_type(rid) == "DocumentControl"
    assert uia.is_on_screen(rid) is True
    assert uia.element_text(rid) == "synthetic value"


def test_T_INS_016_selected_tab_uses_pattern_and_skips_property_errors(
    monkeypatch: Any,
) -> None:
    class BrokenControl:
        @property
        def ControlTypeName(self) -> str:
            raise RuntimeError("synthetic COM property error")

        def GetChildren(self) -> list[Any]:
            return []

    class TabControl:
        ControlTypeName = "TabItemControl"

        def GetSelectionItemPattern(self) -> Any:
            return SimpleNamespace(IsSelected=True)

        def GetRuntimeId(self) -> list[int]:
            return [8, 9]

        def GetChildren(self) -> list[Any]:
            return []

    class RootControl:
        ControlTypeName = "WindowControl"

        def GetChildren(self) -> list[Any]:
            return [TabControl(), BrokenControl()]

    automation = SimpleNamespace(ControlFromHandle=lambda _: RootControl())
    uia = _real_uia(monkeypatch, automation)
    assert uia.selected_tab(10) == (8, 9)


def _materializing_capture_boundary(
    monkeypatch: Any, *, switch_foreground: bool = False
) -> tuple[FakeWin32Api, uia_module.RealUia, uia_module.RuntimeId]:
    win = FakeWin32Api()

    class Field:
        ControlTypeName = "EditControl"

        def __init__(self, rid: uia_module.RuntimeId) -> None:
            self.rid = rid
            self.IsOffscreen = False

        def GetRuntimeId(self) -> list[int]:
            return list(self.rid)

        def GetChildren(self) -> list[Any]:
            return []

    old, current = Field((1, 2)), Field((1, 3))
    state = SimpleNamespace(focused=old, materialized=False)

    class Root:
        ControlTypeName = "WindowControl"

        def GetChildren(self) -> list[Any]:
            # A lazy native provider can replace controls during its first walk.
            if not state.materialized:
                state.materialized = True
                old.IsOffscreen = True
                state.focused = current
                if switch_foreground:
                    win.foreground = 20
            return [current]

    automation = SimpleNamespace(
        ControlFromHandle=lambda _: Root(),
        GetFocusedControl=lambda: state.focused,
    )
    return win, _real_uia(monkeypatch, automation), current.rid


def test_capture_refreshes_field_after_provider_materialization(
    monkeypatch: Any,
) -> None:
    win, uia, current = _materializing_capture_boundary(monkeypatch)
    snapshot = capture(win, uia)
    assert snapshot.field == current
    assert snapshot.field_type == "EditControl"
    assert snapshot.tab is None
    assert verify(snapshot, win, uia).status == "same"


def test_capture_rejects_foreground_change_during_tree_walk(monkeypatch: Any) -> None:
    win, uia, _ = _materializing_capture_boundary(monkeypatch, switch_foreground=True)
    with pytest.raises(WisprError) as caught:
        capture(win, uia)
    assert caught.value.error_code == ErrorCode.DESTINATION_UNVERIFIABLE
    assert caught.value.why == "foreground changed"
