"""T-UI-020/021/022: tray icon, launch-at-login registry value, hide-on-close."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fakes.webview import FakeWebview

from wispr_clone.ui import autostart, tray
from wispr_clone.ui.windows import WindowControls, open_settings


class FakeIcon:
    def __init__(self, name: str, image: object, title: str, menu: Any) -> None:
        self.name, self.image, self.title, self.menu = name, image, title, menu
        self.ran = self.stopped = False

    def run(self) -> None:
        self.ran = True

    def stop(self) -> None:
        self.stopped = True


def _fake_pystray() -> Any:
    def menu_item(text: str, action: Any, default: bool = False) -> Any:
        return SimpleNamespace(text=text, action=action, default=default)

    return SimpleNamespace(
        Menu=lambda *items: list(items), MenuItem=menu_item, Icon=FakeIcon
    )


@pytest.mark.unit
def test_T_UI_020_tray_menu_opens_and_quits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tray, "icon_image", lambda: "image")
    calls: list[str] = []
    icon_tray = tray.Tray(
        on_open=lambda: calls.append("open"),
        on_quit=lambda: calls.append("quit"),
        pystray=_fake_pystray(),
    )

    assert icon_tray.start() is True
    assert icon_tray.running
    icon = icon_tray._icon
    assert icon.title == "Wispr Clone"
    assert [(item.text, item.default) for item in icon.menu] == [
        ("Open Wispr Clone", True),
        ("Quit", False),
    ]
    for item in icon.menu:
        item.action()
    assert calls == ["open", "quit"]
    icon_tray._thread.join(timeout=2)
    assert icon.ran

    icon_tray.stop()
    icon_tray.stop()
    assert icon.stopped
    assert not icon_tray.running


@pytest.mark.unit
def test_T_UI_020_tray_start_failure_is_reported_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken() -> object:
        raise OSError("no image library")

    monkeypatch.setattr(tray, "icon_image", broken)
    icon_tray = tray.Tray(
        on_open=lambda: None, on_quit=lambda: None, pystray=_fake_pystray()
    )
    assert icon_tray.start() is False
    assert not icon_tray.running


@pytest.mark.unit
def test_T_UI_020_icon_image_is_square_rgba() -> None:
    pytest.importorskip("PIL")
    image = tray.icon_image(32)
    assert image.size == (32, 32)
    assert image.mode == "RGBA"
    assert image.getpixel((0, 0))[3] == 0  # rounded corner stays transparent
    assert image.getpixel((16, 16)) == (255, 255, 255, 255)  # middle bar


class FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    class _Key:
        def __enter__(self) -> None:
            return None

        def __exit__(self, *_: object) -> None:
            return None

    def OpenKey(self, root: str, path: str) -> Any:  # noqa: N802
        assert (root, path) == ("HKCU", autostart.RUN_KEY)
        return self._Key()

    def CreateKeyEx(self, root: str, path: str, reserved: int, access: int) -> Any:  # noqa: N802
        assert (root, path, access) == ("HKCU", autostart.RUN_KEY, 2)
        return self._Key()

    def QueryValueEx(self, _key: None, name: str) -> tuple[str, int]:  # noqa: N802
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], 1

    def SetValueEx(self, _key: None, name: str, _r: int, kind: int, value: str) -> None:  # noqa: N802
        assert kind == 1
        self.values[name] = value

    def DeleteValue(self, _key: None, name: str) -> None:  # noqa: N802
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


@pytest.mark.unit
def test_T_UI_021_autostart_is_unavailable_from_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")  # a checkout, even on Windows
    monkeypatch.setattr(autostart, "_winreg", lambda: pytest.fail("no registry"))
    assert autostart.command_line() is None
    assert autostart.status() == {"available": False, "enabled": False}
    assert autostart.set_enabled(True) == {"available": False, "enabled": False}


@pytest.mark.unit
def test_T_UI_021_autostart_writes_and_removes_the_run_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = FakeWinreg()
    command = r'"C:\Apps\app\Scripts\pythonw.exe" -m wispr_clone --background'
    monkeypatch.setattr(autostart, "command_line", lambda: command)
    monkeypatch.setattr(autostart, "_winreg", lambda: registry)

    assert autostart.status() == {"available": True, "enabled": False}
    assert autostart.set_enabled(True) == {"available": True, "enabled": True}
    assert registry.values == {"WisprClone": command}

    # A value from a moved install does not start this executable.
    registry.values["WisprClone"] = r'"D:\old\WisprClone.exe" --background'
    assert autostart.status()["enabled"] is False

    assert autostart.set_enabled(False) == {"available": True, "enabled": False}
    assert registry.values == {}
    assert autostart.set_enabled(False)["enabled"] is False


@pytest.mark.unit
def test_T_UI_022_close_hides_while_tray_runs_and_quit_really_closes() -> None:
    webview = FakeWebview()
    controls = WindowControls()
    window = open_settings(webview, object(), debug=False, controls=controls)
    webview.start()
    assert controls.window is window

    # No tray: closing proceeds, exactly as before.
    assert controls.on_closing() is True
    assert controls("window_close") is True
    assert ("destroy", ()) in window.calls

    window.calls.clear()
    controls.hide_on_close = True
    assert controls.on_closing() is False
    assert controls("window_close") is True
    assert window.calls == [("hide", ()), ("hide", ())]
    assert window.events.closing.handlers == [controls.on_closing]

    controls.show()
    assert ("show", ()) in window.calls

    controls.end_session()
    assert controls.on_closing() is True

    controls.quitting = False
    controls.quit()
    assert controls.quitting
    assert window.calls[-1] == ("destroy", ())


@pytest.mark.unit
def test_T_UI_022_start_hidden_never_shows_the_window() -> None:
    webview = FakeWebview()
    window = open_settings(webview, object(), debug=False, start_hidden=True)
    webview.start()
    assert ("show", ()) not in window.calls


@pytest.mark.unit
def test_T_UI_021_installed_wheel_starts_through_signed_pythonw(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from wispr_clone import config

    package = tmp_path / "app" / "Lib" / "site-packages" / "wispr_clone"
    (package / "web").mkdir(parents=True)
    (package / "web" / "index.html").write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(config, "__file__", str(package / "config.py"))
    monkeypatch.setattr(
        sys, "executable", str(tmp_path / "app" / "Scripts" / "python.exe")
    )

    pythonw = tmp_path / "app" / "Scripts" / "pythonw.exe"
    assert autostart.command_line() == f'"{pythonw}" -m wispr_clone --background'
