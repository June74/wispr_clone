"""RealUia regressions exercised with in-memory controls, without COM."""

from types import SimpleNamespace
from typing import Any

from wispr_clone.insertion import uia as uia_module


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
