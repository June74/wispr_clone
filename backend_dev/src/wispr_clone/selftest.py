"""Offline end-to-end composition check using only in-process boundaries."""

from __future__ import annotations

import asyncio
import importlib
import os
import tempfile
from pathlib import Path
from typing import Any, cast

import numpy as np

_app = importlib.import_module("wispr_clone.app")
_capture = importlib.import_module("wispr_clone.audio.capture")
_common = importlib.import_module("wispr_clone.contracts.common")
_storage = importlib.import_module("wispr_clone.storage.db")
App = _app.App
AppFactories = _app.AppFactories
CaptureChunk = _capture.CaptureChunk
ErrorCode = _common.ErrorCode
Database = _storage.Database


class _Session:
    async def finish(self) -> str:
        return "self test dictation"

    def push_audio(self, _samples: Any) -> None:
        return

    def cancel(self) -> None:
        return


class _Stt:
    ready = True

    async def start(self) -> None:
        return

    def start_session(self) -> _Session:
        return _Session()

    async def transcribe_file(self, _path: Path) -> str:
        return "self test dictation"

    async def close(self) -> None:
        return


class _Cleanup:
    async def clean(self, request: Any) -> str:
        return cast(str, request.text)

    async def health(self) -> bool:
        return True


class _Capture:
    def __init__(self) -> None:
        self.stopped = False
        self.cancelled = False

    def start(self) -> None:
        return

    async def chunks(self) -> Any:
        yield CaptureChunk(np.zeros(1280, dtype=np.float32), [0.0] * 12)
        while not self.stopped and not self.cancelled:
            await asyncio.sleep(0.005)

    def stop(self) -> None:
        self.stopped = True

    def cancel(self) -> None:
        self.cancelled = True


class _Win32:
    def __init__(self) -> None:
        self.foreground = 10
        self.clipboard: str | None = None
        self.on_insert: Any = None

    def foreground_window(self) -> int:
        return self.foreground

    def is_window(self, hwnd: int) -> bool:
        return hwnd == 10

    def window_process(self, hwnd: int) -> tuple[int, str]:
        return (os.getpid() + 1, "target.exe")

    def window_title(self, hwnd: int) -> str:
        return "target"

    def keyboard_layout(self, hwnd: int) -> int:
        return 0x0409

    def set_foreground(self, hwnd: int) -> bool:
        self.foreground = hwnd
        return True

    def idle_ms(self) -> int:
        return 10_000

    def send_inputs(self, inputs: Any) -> int:
        if self.on_insert is not None:
            self.on_insert()
        return len(inputs)

    def clipboard_text(self) -> str | None:
        return self.clipboard

    def set_clipboard(self, text: str, *, exclusion_formats: bool) -> None:
        self.clipboard = text

    def clear_clipboard(self) -> None:
        self.clipboard = None


class _Uia:
    def __init__(self) -> None:
        self.text = ""

    def focused_element(self) -> tuple[int, ...]:
        return (1,)

    def element_control_type(self, _rid: tuple[int, ...]) -> str:
        return "Edit"

    def selected_tab(self, _hwnd: int) -> None:
        return None

    def select_tab(self, _hwnd: int, _tab: tuple[int, ...]) -> bool:
        return True

    def focus_element(self, _rid: tuple[int, ...]) -> bool:
        return True

    def element_text(self, _rid: tuple[int, ...]) -> str:
        return self.text

    def is_on_screen(self, _rid: tuple[int, ...]) -> bool:
        return True


class _Listener:
    def start(self) -> None:
        return

    def stop(self) -> None:
        return


def run_self_test() -> int:
    async def run() -> None:
        with tempfile.TemporaryDirectory(prefix="wispr-self-test-") as temporary:
            data_dir = Path(temporary)
            win32, uia, stt = _Win32(), _Uia(), _Stt()
            win32.on_insert = lambda: setattr(
                uia, "text", uia.text + "self test dictation"
            )

            def capture_factory(
                _lease: Any, _device: int | None, _owner: Any
            ) -> _Capture:
                return _Capture()

            factories = AppFactories(
                open_database=Database,
                stt_engine=lambda _settings: stt,
                cleanup_for=lambda _model: _Cleanup(),
                win32=lambda: win32,
                uia=lambda: uia,
                new_capture=capture_factory,
                list_devices=lambda: (),
                hotkey_listener=lambda _service: _Listener(),
                webview=None,
                clock=lambda: 1000.0,
                monotonic=lambda: 1000.0,
            )
            app = App(factories, data_dir=data_dir)
            await app.startup()
            start = await app.api.call(
                "run_start",
                {
                    "session_token": app.api.session_token,
                    "deadline": 1010.0,
                    "request_id": "self-test",
                },
            )
            if not start.ok or not start.data:
                raise RuntimeError(ErrorCode.STORAGE_ERROR.value)
            run_id = str(start.data["run_id"])
            await app.api.call(
                "run_stop",
                {
                    "session_token": app.api.session_token,
                    "deadline": 1010.0,
                    "run_id": run_id,
                },
            )
            deadline = asyncio.get_running_loop().time() + 10
            while asyncio.get_running_loop().time() < deadline:
                record = await app._history.get(run_id) if app._history else None
                if record is not None and record.status.value == "done":
                    break
                await asyncio.sleep(0.02)
            else:
                raise RuntimeError(ErrorCode.STORAGE_ERROR.value)
            attempts = await app._history.attempts(run_id) if app._history else ()
            attempt = next(iter(attempts), None)
            if (
                len(attempts) != 1
                or attempt is None
                or attempt.outcome.value != "inserted"
            ):
                raise RuntimeError(ErrorCode.STORAGE_ERROR.value)
            await app.shutdown()

    try:
        asyncio.run(run())
        print("self-test ok")
        if os.environ.get("WISPR_SELF_TEST_PRINT_MODULES") == "1":
            forbidden = ("webview", "pynput", "sounddevice", "uiautomation", "win32gui")
            imported = sorted(
                name
                for name in __import__("sys").modules
                if any(
                    name == item or name.startswith(item + ".") for item in forbidden
                )
            )
            print(f"self-test modules: {','.join(imported)}")
        return 0
    except Exception:
        print("self-test failed: storage_error")
        return 1
