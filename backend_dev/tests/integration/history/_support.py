"""Disposable history database and WAV builders for this feature's tests."""

import wave
from pathlib import Path

from fakes.clock import FakeClock
from fakes.events import FakeEventSink
from fakes.ids import FakeIdFactory

from wispr_clone.storage import Connection, Database, Migration


def _settings_stand_in(conn: Connection) -> None:
    conn.execute("CREATE TABLE settings (id TEXT PRIMARY KEY, value TEXT NOT NULL)")


def _dictionary_stand_in(conn: Connection) -> None:
    conn.execute(
        "CREATE TABLE dictionary_entries (id TEXT PRIMARY KEY, word TEXT NOT NULL)"
    )


def migrations() -> list[Migration]:
    from wispr_clone.storage.migrations import m001_base, m004_history

    return [
        Migration(m001_base.VERSION, m001_base.NAME, m001_base.apply),
        Migration(2, "settings_test_placeholder", _settings_stand_in),
        Migration(3, "dictionary_test_placeholder", _dictionary_stand_in),
        Migration(m004_history.VERSION, m004_history.NAME, m004_history.apply),
    ]


def database(path: Path) -> Database:
    return Database(path, migrations())


def wav(path: Path) -> Path:
    """Create a valid, tiny silent PCM WAV on disk."""
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(b"\0\0" * 16)
    return path


def repo(
    db: Database,
    audio_dir: Path,
    clock: FakeClock,
    events: FakeEventSink,
    **kwargs: object,
):
    from wispr_clone.history.repo import HistoryRepo

    return HistoryRepo(
        db, clock=clock.now, audio_dir=audio_dir, events=events, **kwargs
    )


async def create(history, ids: FakeIdFactory, **kwargs: object):
    run_id = ids.new("run")
    return await history.create_run(
        run_id=run_id,
        start_request_id=ids.new("start"),
        config={"cleanup": False},
        **kwargs,
    )
