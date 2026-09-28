"""T-APP-042: startup failures are recorded and reported without private text."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fakes.webview import Window

from wispr_clone import config
from wispr_clone.app import App, AppFactories

from ._support import Boundaries


@pytest.mark.unit
def test_T_APP_042_window_creation_failure_reports_one_safe_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from wispr_clone import __main__ as entrypoint

    boundaries = Boundaries()

    def broken_window(*args: object, **kwargs: object) -> Window:
        raise RuntimeError("private key and transcript must stay hidden")

    monkeypatch.setattr(boundaries.webview, "create_window", broken_window)
    app_instances: list[App] = []

    def make_app(
        factories: AppFactories, *, data_dir: Path, debug: bool, start_hidden: bool
    ) -> App:
        app = App(factories, data_dir=data_dir, debug=debug, start_hidden=start_hidden)
        app_instances.append(app)
        return app

    monkeypatch.setattr(entrypoint, "App", make_app)
    monkeypatch.setattr(
        entrypoint, "real_factories", lambda: boundaries.factories(gui=True)
    )
    monkeypatch.setattr(config, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        entrypoint,
        "acquire_single_instance",
        lambda: SimpleNamespace(release=lambda: None),
    )

    assert entrypoint.main([]) == 1
    assert len(app_instances) == 1
    assert app_instances[0].failure == ("windows", "RuntimeError")
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "wispr_clone: startup failed at windows (RuntimeError)\n"
