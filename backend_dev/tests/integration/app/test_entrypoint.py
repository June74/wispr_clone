"""WO-M5 process boundaries: lock and self-test."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_self_test_runs_without_desktop_dependencies(tmp_path: Path) -> None:
    env = {**os.environ, "WISPR_SELF_TEST_PRINT_MODULES": "1"}
    result = subprocess.run(
        [sys.executable, "-m", "wispr_clone", "--self-test"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "self-test ok" in result.stdout.splitlines()
    assert any(
        line.startswith("self-test modules:") for line in result.stdout.splitlines()
    )
    for forbidden in ("webview", "pynput", "sounddevice", "uiautomation", "win32gui"):
        assert forbidden not in result.stdout


def test_second_instance_exits_before_database_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from wispr_clone.app import acquire_single_instance

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    lock = acquire_single_instance("WisprCloneM5Test")
    assert lock is not None
    try:
        second = acquire_single_instance("WisprCloneM5Test")
        assert second is None
        assert not list(tmp_path.rglob("*.db"))
    finally:
        lock.release()


def test_entrypoint_returns_three_while_lock_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from wispr_clone.app import acquire_single_instance

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    lock = acquire_single_instance()
    assert lock is not None
    try:
        result = subprocess.run(
            [sys.executable, "-m", "wispr_clone"],
            env=os.environ.copy(),
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        assert result.returncode == 3, result.stderr
        assert not list(tmp_path.rglob("*.db"))
    finally:
        lock.release()
