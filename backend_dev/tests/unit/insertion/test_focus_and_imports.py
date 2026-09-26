"""T-INS focus transition, settle and lazy import contracts."""

import logging
import subprocess
import sys

from .fake_apis import FakeUiaApi, FakeWin32Api


def _target() -> object:
    from wispr_clone.insertion.destination import capture

    return capture(FakeWin32Api(), FakeUiaApi())


def test_T_INS_008_bring_forward_and_restore_original_window_tab() -> None:
    from wispr_clone.insertion.inserter import bring_forward, restore

    win, uia = FakeWin32Api(foreground=20), FakeUiaApi(focused=(20, 2))
    now = [0.0]

    def sleep(seconds: float) -> None:
        now[0] += max(seconds, 0.01)

    previous = bring_forward(_target(), win, uia, sleep=sleep, clock=lambda: now[0])
    assert previous is not None
    assert (previous.hwnd, previous.tab) == (20, (20, 1))
    assert ("set_foreground", (10,), {}) in win.calls
    assert ("select_tab", (10, (10, 1))) in uia.calls
    assert ("focus_element", ((1, 2),)) in uia.calls
    restore(previous, win, uia)
    assert win.foreground == 20
    assert ("select_tab", (20, (20, 1))) in uia.calls


def test_T_INS_011_bring_forward_times_out_and_waits_for_settle() -> None:
    from wispr_clone.insertion.inserter import bring_forward

    now = [0.0]

    def sleep(seconds: float) -> None:
        now[0] += max(seconds, 0.01)

    win, uia = FakeWin32Api(foreground=20, switch_foreground=False), FakeUiaApi()
    assert (
        bring_forward(
            _target(),
            win,
            uia,
            settle_s=0.1,
            timeout_s=0.3,
            sleep=sleep,
            clock=lambda: now[0],
        )
        is None
    )
    assert 0.3 <= now[0] <= 0.5
    now[0] = 0.0
    win.switch_foreground = True
    assert (
        bring_forward(
            _target(),
            win,
            uia,
            settle_s=0.1,
            timeout_s=0.3,
            sleep=sleep,
            clock=lambda: now[0],
        )
        is not None
    )
    assert now[0] >= 0.1


def test_T_INS_012_imports_are_lazy_and_logs_do_not_contain_text(caplog) -> None:
    from wispr_clone.insertion.inserter import dispatch

    subprocess.run(
        [
            sys.executable,
            "-c",
            "import importlib\n"
            "import sys\n"
            "for name in (\n"
            "    'wispr_clone.insertion.destination',\n"
            "    'wispr_clone.insertion.verifier',\n"
            "    'wispr_clone.insertion.inserter',\n"
            "    'wispr_clone.insertion.app_strategies',\n"
            "    'wispr_clone.insertion.win32',\n"
            "    'wispr_clone.insertion.uia',\n"
            "):\n"
            "    importlib.import_module(name)\n"
            "assert 'win32clipboard' not in sys.modules\n"
            "assert 'uiautomation' not in sys.modules\n",
        ],
        check=True,
        timeout=10,
    )
    with caplog.at_level(logging.DEBUG):
        win, uia = FakeWin32Api(), FakeUiaApi()
        dispatch("PRIVATE TRANSCRIPT sentinel 81", _target(), win, uia)
    assert "PRIVATE TRANSCRIPT sentinel 81" not in caplog.text
    for name in (
        "wispr_clone.insertion.destination",
        "wispr_clone.insertion.verifier",
        "wispr_clone.insertion.inserter",
        "wispr_clone.insertion.app_strategies",
    ):
        assert "PRIVATE TRANSCRIPT sentinel 81" not in repr(vars(sys.modules[name]))
