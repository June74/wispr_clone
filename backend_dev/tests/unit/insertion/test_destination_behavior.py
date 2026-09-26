"""T-INS destination identity and privacy contracts."""

from dataclasses import replace
from hashlib import sha256

import pytest

from .fake_apis import FakeUiaApi, FakeWin32Api


def test_T_INS_001_capture_hashes_title_without_leaking_it() -> None:
    from wispr_clone.insertion.destination import capture

    win, uia = FakeWin32Api(), FakeUiaApi()
    title = "PRIVATE TITLE: sentinel 98"
    win.titles[10] = title
    snapshot = capture(win, uia)
    assert snapshot.title_hash == sha256(title.encode()).hexdigest()
    assert title not in repr(snapshot)
    assert title not in str(snapshot.to_json())
    assert "title" not in snapshot.to_json() or snapshot.to_json()["title"] != title


def test_T_INS_002_verify_detects_process_focus_and_closed_window() -> None:
    from wispr_clone.insertion.destination import capture
    from wispr_clone.insertion.verifier import verify

    win, uia = FakeWin32Api(), FakeUiaApi()
    snapshot = capture(win, uia)
    assert verify(snapshot, win, uia).status == "same"
    win.processes[10] = (999, "target.exe")
    assert verify(snapshot, win, uia).status == "changed"
    win.processes[10] = (101, "other.exe")
    assert verify(snapshot, win, uia).status == "changed"
    win.processes[10] = (101, "target.exe")
    win.foreground = 20
    assert verify(snapshot, win, uia).status == "changed"
    win.windows.remove(10)
    assert verify(snapshot, win, uia).status == "closed"


def test_T_INS_003_matching_title_never_overrides_window_identity() -> None:
    from wispr_clone.insertion.destination import capture
    from wispr_clone.insertion.verifier import verify

    win, uia = FakeWin32Api(), FakeUiaApi()
    snapshot = capture(win, uia)
    win.titles[20] = win.titles[10]
    win.foreground = 20
    assert verify(replace(snapshot, hwnd=10), win, uia).status == "changed"
    win.foreground = 10
    win.processes[10] = (999, "target.exe")
    assert verify(snapshot, win, uia).status == "changed"


def test_T_INS_002_verify_detects_tab_field_and_visibility() -> None:
    from wispr_clone.insertion.destination import capture
    from wispr_clone.insertion.verifier import verify

    win, uia = FakeWin32Api(), FakeUiaApi()
    snapshot = capture(win, uia)
    uia.tabs[10] = (10, 2)
    assert verify(snapshot, win, uia).status == "changed"
    uia.tabs[10] = (10, 1)
    uia.focused = (1, 3)
    assert verify(snapshot, win, uia).status == "changed"
    uia.focused = (1, 2)
    uia.visible[(1, 2)] = False
    assert verify(snapshot, win, uia).status == "unverifiable"
    assert verify(replace(snapshot, field=None), win, uia).status == "unverifiable"


def test_T_INS_007_capture_roundtrip_and_rejects_malformed_snapshot() -> None:
    from wispr_clone.insertion.destination import DestinationSnapshot, capture

    from wispr_clone.contracts.common import ErrorCode, WisprError

    win, uia = FakeWin32Api(), FakeUiaApi()
    snapshot = capture(win, uia)
    assert (snapshot.hwnd, snapshot.pid, snapshot.exe) == (10, 101, "target.exe")
    assert snapshot.tab == (10, 1)
    assert snapshot.field == (1, 2)
    assert snapshot.field_type == "Edit"
    assert snapshot.langid == 0x0409
    assert DestinationSnapshot.from_json(snapshot.to_json()) == snapshot
    for bad in (
        {},
        {**snapshot.to_json(), "hwnd": "10"},
        {**snapshot.to_json(), "field": ["x"]},
    ):
        with pytest.raises(WisprError) as error:
            DestinationSnapshot.from_json(bad)
        assert error.value.error_code == ErrorCode.VALIDATION
