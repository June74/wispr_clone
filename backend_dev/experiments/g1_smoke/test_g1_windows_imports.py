"""Phase -1.1 (G1) disposable smoke test: Windows venv + WSL checkout. Not product code."""
import sys


def test_python_is_312_on_windows():
    assert sys.platform == "win32" and sys.version_info[:2] == (3, 12)


def test_native_windows_packages_import():
    import pynput.keyboard  # noqa: F401  global hotkey hook
    import sounddevice  # noqa: F401  PortAudio capture
    import webview  # noqa: F401  pywebview host
    import win32clipboard  # noqa: F401  pywin32
    import transcribe_cpp
    assert any(d.device_type == "gpu" for d in transcribe_cpp.backends())


def test_sqlite_on_windows_disk(tmp_path):
    import sqlite3
    con = sqlite3.connect(tmp_path / "t.db")
    assert con.execute("pragma journal_mode=wal").fetchone()[0] == "wal"
    con.close()
