"""In-process boundaries for the WO-M5 composition tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fakes.audio import FakeCapture
from fakes.cleanup import FakeCleanupEngine
from fakes.insertion import FakeUiaApi, FakeWin32Api
from fakes.stt import FakeSttEngine
from fakes.webview import FakeWebview

from wispr_clone.storage.db import Database

if TYPE_CHECKING:
    from wispr_clone.app import AppFactories


class RecordingDatabase(Database):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.closed_by_app = False

    async def close(self) -> None:
        await super().close()
        self.closed_by_app = True


class Listener:
    def __init__(self, service: Any) -> None:
        self.service = service
        self.starts = 0
        self.stops = 0

    def start(self) -> None:
        self.starts += 1

    def stop(self) -> None:
        self.stops += 1


class ClosableCleanup(FakeCleanupEngine):
    def __init__(self) -> None:
        super().__init__("fixed text")
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


@dataclass
class Boundaries:
    db_path: Path | None = None
    now: float = 1000.0
    monotonic_now: float | None = None
    stt: FakeSttEngine = field(default_factory=lambda: FakeSttEngine("fixed text"))
    win32: FakeWin32Api = field(default_factory=FakeWin32Api)
    uia: FakeUiaApi = field(default_factory=FakeUiaApi)
    webview: FakeWebview = field(default_factory=FakeWebview)
    captures: list[FakeCapture] = field(default_factory=list)
    capture_devices: list[int | None] = field(default_factory=list)
    listeners: list[Listener] = field(default_factory=list)
    databases: list[RecordingDatabase] = field(default_factory=list)
    cleanups: list[ClosableCleanup] = field(default_factory=list)

    def factories(self, *, gui: bool = False) -> AppFactories:
        from wispr_clone.app import AppFactories

        def open_database(path: Path) -> RecordingDatabase:
            database = RecordingDatabase(self.db_path or path)
            self.databases.append(database)
            return database

        def new_capture(_lease: Any, device: int | None, _owner: Any) -> FakeCapture:
            capture = FakeCapture()
            self.captures.append(capture)
            self.capture_devices.append(device)
            return capture

        def new_listener(service: Any) -> Listener:
            listener = Listener(service)
            self.listeners.append(listener)
            return listener

        def cleanup_for(_model_id: str) -> ClosableCleanup:
            cleanup = ClosableCleanup()
            self.cleanups.append(cleanup)
            return cleanup

        return AppFactories(
            open_database=open_database,
            stt_engine=lambda _settings: self.stt,
            cleanup_for=cleanup_for,
            win32=lambda: self.win32,
            uia=lambda: self.uia,
            new_capture=new_capture,
            list_devices=lambda: (),
            hotkey_listener=new_listener,
            webview=(lambda: self.webview) if gui else None,
            clock=lambda: self.now,
            monotonic=lambda: (
                self.now if self.monotonic_now is None else self.monotonic_now
            ),
        )
