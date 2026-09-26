"""WO-M2 crash boundary with a real SQLite file and a killed child process."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fakes.clock import FakeClock
from fakes.events import FakeEventSink
from fakes.insertion import FakeUiaApi, FakeWin32Api

from wispr_clone.contracts.run import AttemptOutcome
from wispr_clone.history.repo import HistoryRepo
from wispr_clone.insertion.destination import capture
from wispr_clone.pipeline.insertion_protocol import InsertionProtocol, ProtocolOutcome
from wispr_clone.storage import Connection, Database, Migration


def _settings(conn: Connection) -> None:
    conn.execute("CREATE TABLE settings (id TEXT PRIMARY KEY, value TEXT NOT NULL)")


def _dictionary(conn: Connection) -> None:
    conn.execute(
        "CREATE TABLE dictionary_entries (id TEXT PRIMARY KEY, word TEXT NOT NULL)"
    )


def _database(path: Path) -> Database:
    from wispr_clone.storage.migrations import m001_base, m004_history

    return Database(
        path,
        [
            Migration(m001_base.VERSION, m001_base.NAME, m001_base.apply),
            Migration(2, "settings_test_placeholder", _settings),
            Migration(3, "dictionary_test_placeholder", _dictionary),
            Migration(m004_history.VERSION, m004_history.NAME, m004_history.apply),
        ],
    )


async def _inline(call: Callable[[], Any]) -> Any:
    return call()


_CHILD = r"""
import asyncio
import os
import sys
from pathlib import Path
from fakes.clock import FakeClock
from fakes.events import FakeEventSink
from fakes.insertion import FakeUiaApi, FakeWin32Api
from wispr_clone.history.repo import HistoryRepo
from wispr_clone.insertion.destination import capture
from wispr_clone.pipeline.insertion_protocol import InsertionProtocol
from wispr_clone.storage import Connection, Database, Migration
from wispr_clone.storage.migrations import m001_base, m004_history

def settings(conn):
    conn.execute("CREATE TABLE settings (id TEXT PRIMARY KEY, value TEXT NOT NULL)")
def dictionary(conn):
    conn.execute(
        "CREATE TABLE dictionary_entries (id TEXT PRIMARY KEY, word TEXT NOT NULL)"
    )

async def main():
    path = Path(sys.argv[1])
    db = Database(path, [
        Migration(m001_base.VERSION, m001_base.NAME, m001_base.apply),
        Migration(2, "settings_test_placeholder", settings),
        Migration(3, "dictionary_test_placeholder", dictionary),
        Migration(m004_history.VERSION, m004_history.NAME, m004_history.apply),
    ])
    clock = FakeClock(100)
    win, uia = FakeWin32Api(), FakeUiaApi()
    snapshot = capture(win, uia)
    async with db:
        history = HistoryRepo(
            db, clock=clock.now, audio_dir=path.parent, events=FakeEventSink()
        )
        await history.create_run(run_id="run-1", start_request_id="start-1", config={})
        async def offload(call):
            if await history.attempts("run-1"):
                os._exit(1)
            return call()
        protocol = InsertionProtocol(
            history, win, uia, offload=offload, clock=clock.now,
            new_id=lambda: "attempt-1", paste_settle_s=0.0,
        )
        await protocol.attempt(
            "run-1", "PRIVATE TRANSCRIPT", snapshot,
            request_id="request-1", kind="automatic", is_cancelled=lambda: False,
        )
    os._exit(99)

asyncio.run(main())
"""


@pytest.mark.asyncio
async def test_T_PRO_005_crash_after_claim_recovers_uncertain(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    env = os.environ.copy()
    root = Path(__file__).resolve().parents[3]
    env["PYTHONPATH"] = os.pathsep.join(
        (str(root / "src"), str(root / "tests"), env.get("PYTHONPATH", ""))
    )
    child = subprocess.run(
        [sys.executable, "-c", _CHILD, str(path)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert child.returncode == 1, child.stderr
    clock = FakeClock(100)
    async with _database(path) as db:
        history = HistoryRepo(
            db, clock=clock.now, audio_dir=tmp_path, events=FakeEventSink()
        )
        report = await history.recover_on_startup()
        assert report.in_flight_to_uncertain == ("attempt-1",)
        assert (await history.attempts("run-1"))[0].outcome == AttemptOutcome.UNCERTAIN
        win, uia = FakeWin32Api(), FakeUiaApi()
        protocol = InsertionProtocol(
            history,
            win,
            uia,
            offload=_inline,
            clock=clock.now,
            new_id=lambda: "unused",
            paste_settle_s=0.0,
        )
        repeated = await protocol.attempt(
            "run-1",
            "PRIVATE TRANSCRIPT",
            capture(win, uia),
            request_id="request-1",
            kind="automatic",
            is_cancelled=lambda: False,
        )
        assert (repeated.outcome, repeated.reason, repeated.attempt_id) == (
            ProtocolOutcome.DUPLICATE,
            "duplicate request",
            "attempt-1",
        )
        assert not any(name == "send_inputs" for name, _, _ in win.calls)
