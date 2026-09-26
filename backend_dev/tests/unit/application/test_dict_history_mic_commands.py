"""WO-M4c command contracts against real repositories and the M3 controller."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fakes.audio import FakeCapture
from fakes.clock import FakeClock
from fakes.events import FakeEventSink
from fakes.insertion import FakeUiaApi, FakeWin32Api
from fakes.stt import FakeSttEngine

from wispr_clone.application.api import Api
from wispr_clone.application.commands.audio_commands import AudioCommands
from wispr_clone.application.commands.dictionary_commands import DictionaryCommands
from wispr_clone.application.commands.history_commands import HistoryCommands
from wispr_clone.application.commands.run_commands import RunCommands
from wispr_clone.audio.capture import CaptureChunk
from wispr_clone.audio.device_lease import DeviceLease
from wispr_clone.audio.devices import InputDevice
from wispr_clone.audio.wav_writer import WavWriter
from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.dictionary.repo import DictionaryRepo
from wispr_clone.history.repo import HistoryRepo
from wispr_clone.insertion.destination import capture
from wispr_clone.pipeline.insertion_protocol import InsertionProtocol
from wispr_clone.pipeline.run_controller import RunController, RunServices
from wispr_clone.storage import Database, Migration
from wispr_clone.storage.migrations import (
    m001_base,
    m002_settings,
    m003_dictionary,
    m004_history,
)


class LeasedCapture(FakeCapture):
    """M3 capture fake with the real microphone ownership boundary."""

    def __init__(self, lease: DeviceLease, owner: str) -> None:
        super().__init__()
        self.lease = lease
        self.owner = owner
        self.token: Any = None
        self.fail_pump = False

    async def chunks(self) -> AsyncIterator[CaptureChunk]:
        if self.fail_pump:
            self.cancel()
            raise RuntimeError("synthetic pump failure")
        async for chunk in super().chunks():
            yield chunk

    def start(self) -> None:
        self.token = self.lease.acquire(self.owner)  # type: ignore[arg-type]
        super().start()

    def stop(self) -> None:
        super().stop()
        if self.token is not None:
            self.lease.release(self.token)
            self.token = None

    def cancel(self) -> None:
        super().cancel()
        if self.token is not None:
            self.lease.release(self.token)
            self.token = None


class Rig:
    def __init__(
        self,
        db: Database,
        path: Path,
        clock: FakeClock,
        events: FakeEventSink,
    ) -> None:
        self.clock = clock
        self.events = events
        self.lease = DeviceLease()
        self.history = HistoryRepo(db, clock=clock.now, audio_dir=path, events=events)
        self.dictionary = DictionaryRepo(db, clock=clock.now)
        self.win, self.uia = FakeWin32Api(), FakeUiaApi()
        destination = capture(self.win, self.uia)
        self.win.calls.clear()
        self.uia.calls.clear()
        self.recording_captures: list[LeasedCapture] = []
        self.test_captures: list[LeasedCapture] = []
        self.fail_next_test_pump = False
        self.clipboard: list[str] = []
        ids = iter(f"run-{index}" for index in range(20))

        async def inline(operation: Callable[[], Any]) -> Any:
            return operation()

        async def capture_destination() -> Any:
            return destination

        def new_capture() -> LeasedCapture:
            item = LeasedCapture(self.lease, "capture")
            self.recording_captures.append(item)
            return item

        def new_test_capture(device_id: int | None) -> LeasedCapture:
            self.last_device_id = device_id
            item = LeasedCapture(self.lease, "mic_test")
            item.fail_pump = self.fail_next_test_pump
            self.fail_next_test_pump = False
            self.test_captures.append(item)
            return item

        self.controller = RunController(
            RunServices(
                history=self.history,
                dictionary=self.dictionary,
                stt=FakeSttEngine("PRIVATE DICTATION SENTINEL"),
                insertion=InsertionProtocol(
                    self.history,
                    self.win,
                    self.uia,
                    offload=inline,
                    clock=clock.now,
                    new_id=lambda: "attempt-1",
                    paste_settle_s=0.0,
                ),
                events=events,
                capture_destination=capture_destination,
                new_capture=new_capture,
                new_wav=WavWriter,
                new_id=lambda: next(ids),
                audio_dir=path,
                config_snapshot=lambda: {},
                clock=clock.now,
            )
        )
        self.runs = RunCommands(
            self.controller,
            clock=clock.now,
            copy_to_clipboard=self.copy,
            last_external_destination=lambda: None,
        )
        self.audio = AudioCommands(
            list_devices=lambda: (InputDevice(2, "Test input", 1, 16000.0, True),),
            new_test_capture=new_test_capture,
            events=events,
            max_test_s=0.02,
        )
        self.api = Api(
            {
                **self.runs.specs(),
                **DictionaryCommands(self.dictionary).specs(),
                **HistoryCommands(
                    self.history,
                    self.controller,
                    self.runs,
                    copy_to_clipboard=self.copy,
                ).specs(),
                **self.audio.specs(),
            },
            session_token="session-1",
            clock=clock.now,
        )

    async def copy(self, text: str) -> None:
        self.clipboard.append(text)

    async def call(self, name: str, **fields: object) -> Any:
        return await self.api.call(
            name,
            {"session_token": "session-1", "deadline": self.clock.now() + 5, **fields},
        )

    async def finished_run(self, request_id: str) -> str:
        run_id = (await self.call("run_start", request_id=request_id)).data["run_id"]
        self.win.foreground = 20
        assert (await self.call("run_stop", run_id=run_id)).ok
        await self.controller.settled(run_id)
        return run_id


@asynccontextmanager
async def scenario(path: Path) -> AsyncIterator[Rig]:
    migrations = [
        Migration(module.VERSION, module.NAME, module.apply)
        for module in (m001_base, m002_settings, m003_dictionary, m004_history)
    ]
    async with Database(path / "m4c.db", migrations) as db:
        rig = Rig(db, path, FakeClock(100), FakeEventSink())
        try:
            yield rig
        finally:
            if rig.controller.active_run_id is not None:
                await rig.controller.cancel_current()
            await rig.call("mic_test_stop")


def assert_error(result: Any, code: ErrorCode) -> None:
    assert result.ok is False
    assert result.data is None
    assert result.error == code


@pytest.mark.asyncio
async def test_T_APP_020_dictionary_crud_and_validation(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        entry = {"spelling": "OpenWhispr", "aliases": ["open whisper"], "note": "term"}
        added = await rig.call("dict_add", entry=entry)
        assert added.ok
        entry_id = added.data["id"]
        assert type(entry_id) is int
        assert added.data == {"id": entry_id, **entry}
        assert (await rig.call("dict_list")).data == {"entries": [added.data]}
        assert_error(await rig.call("dict_add", entry=entry), ErrorCode.VALIDATION)
        changed = {"spelling": "Wispr", "aliases": [], "note": "updated"}
        assert (await rig.call("dict_update", id=entry_id, entry=changed)).data == {
            "id": entry_id,
            **changed,
        }
        for fields in (
            {"entry": {"spelling": "Bad", "unexpected": "value"}},
            {"entry": {"spelling": 3}},
        ):
            assert_error(await rig.call("dict_add", **fields), ErrorCode.VALIDATION)
        assert_error(
            await rig.call("dict_update", id=True, entry=changed), ErrorCode.VALIDATION
        )
        assert_error(await rig.call("dict_delete", id=True), ErrorCode.VALIDATION)
        assert (await rig.call("dict_delete", id=entry_id)).ok
        assert (await rig.call("dict_list")).data == {"entries": []}


@pytest.mark.asyncio
async def test_T_APP_021_dictionary_import_export_round_trip(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        await rig.call("dict_add", entry={"spelling": "Existing"})
        text = json.dumps(
            {
                "format": "wispr-clone-dictionary",
                "version": 1,
                "entries": [
                    {"spelling": "existing"},
                    {"spelling": "New", "aliases": ["new phrase"], "note": "메모"},
                    {"spelling": "NEW"},
                    {"spelling": "Last"},
                ],
            }
        )
        assert (await rig.call("dict_import", text=text)).data == {
            "added": 2,
            "skipped_duplicates": [0, 2],
        }
        entries = (await rig.call("dict_list")).data["entries"]
        exported = (await rig.call("dict_export")).data
        assert set(exported) == {"text"}
        await rig.call("dict_delete", id=entries[0]["id"])
        await rig.call("dict_delete", id=entries[1]["id"])
        await rig.call("dict_delete", id=entries[2]["id"])
        assert (await rig.call("dict_import", text=exported["text"])).data == {
            "added": 3,
            "skipped_duplicates": [],
        }
        restored = (await rig.call("dict_list")).data["entries"]
        assert [
            {k: e[k] for k in ("spelling", "aliases", "note")} for e in restored
        ] == [{k: e[k] for k in ("spelling", "aliases", "note")} for e in entries]


@pytest.mark.asyncio
async def test_T_APP_022_history_list_get_selection_and_expiry(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        first = await rig.finished_run("first")
        original = await rig.history.get(first)
        await rig.history.update_run(
            first,
            expected_version=original.version,
            adjusted_text="ADJUSTED SENTINEL",
            cleaned_text="CLEANED SENTINEL",
            output_selection="cleaned",
        )
        rig.clock.advance(1)
        second = await rig.finished_run("second")
        listed = (await rig.call("history_list")).data["runs"]
        assert [item["run_id"] for item in listed] == [second, first]
        assert listed[0]["text"] == "PRIVATE DICTATION SENTINEL"
        assert listed[1]["text"] == "CLEANED SENTINEL"
        assert set(listed[1]) == set(
            rig.controller.run_snapshot(await rig.history.get(first))
        ) | {"text"}
        detail = (await rig.call("history_get", run_id=first)).data
        assert detail["text"] == "CLEANED SENTINEL"
        assert detail["original_text"] == "PRIVATE DICTATION SENTINEL"
        assert detail["adjusted_text"] == "ADJUSTED SENTINEL"
        assert detail["cleaned_text"] == "CLEANED SENTINEL"
        rig.clock.advance(86_400)
        assert_error(await rig.call("history_get", run_id=first), ErrorCode.RUN_EXPIRED)


@pytest.mark.asyncio
async def test_T_APP_023_delete_active_run_aborts_and_invalidates(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as rig:
        run_id = (await rig.call("run_start", request_id="active")).data["run_id"]
        capture = rig.recording_captures[-1]
        assert rig.lease.holder == "capture"
        deleted = await rig.call("history_delete", run_id=run_id)
        assert deleted.ok and deleted.data == {
            "run_ids": [run_id],
            "audio_pending": False,
        }
        assert capture.cancelled and rig.lease.holder is None
        assert await rig.history.list_runs() == ()
        assert_error(
            await rig.call("run_start", request_id="active"), ErrorCode.RUN_DELETED
        )
        count = len(rig.events.events)
        await asyncio.sleep(0)
        assert len(rig.events.events) == count
        assert rig.controller.active_run_id is None


@pytest.mark.asyncio
async def test_T_APP_024_delete_all_aborts_and_invalidates(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        first = await rig.finished_run("one")
        rig.clock.advance(1)
        second = (await rig.call("run_start", request_id="two")).data["run_id"]
        result = await rig.call("history_delete_all")
        assert result.ok
        assert set(result.data["run_ids"]) == {first, second}
        assert result.data["audio_pending"] is False
        assert rig.recording_captures[-1].cancelled
        assert await rig.history.list_runs() == ()
        for request_id in ("one", "two"):
            assert_error(
                await rig.call("run_start", request_id=request_id),
                ErrorCode.RUN_DELETED,
            )


@pytest.mark.asyncio
async def test_T_APP_028_delete_all_does_not_orphan_concurrent_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with scenario(tmp_path) as rig:
        await rig.finished_run("old")
        listed = asyncio.Event()
        resume = asyncio.Event()
        list_runs = rig.history.list_runs

        async def pause_after_snapshot() -> Any:
            records = await list_runs()
            listed.set()
            await resume.wait()
            return records

        monkeypatch.setattr(rig.history, "list_runs", pause_after_snapshot)
        deletion = asyncio.create_task(rig.call("history_delete_all"))
        await asyncio.wait_for(listed.wait(), 1)
        started = await rig.call("run_start", request_id="during-delete")
        assert started.ok
        run_id = started.data["run_id"]
        resume.set()
        result = await deletion
        monkeypatch.setattr(rig.history, "list_runs", list_runs)

        assert run_id in result.data["run_ids"]
        with pytest.raises(WisprError) as error:
            await rig.history.get(run_id)
        assert error.value.error_code == ErrorCode.RUN_NOT_FOUND
        assert rig.controller.active_run_id is None
        assert rig.lease.holder is None
        assert_error(
            await rig.call("run_start", request_id="during-delete"),
            ErrorCode.RUN_DELETED,
        )


@pytest.mark.asyncio
async def test_T_APP_028_failed_mic_start_releases_acquired_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with scenario(tmp_path) as rig:

        def broken_capture(device_id: int | None) -> LeasedCapture:
            capture = LeasedCapture(rig.lease, "mic_test")

            def start_then_fail() -> None:
                LeasedCapture.start(capture)
                raise RuntimeError("synthetic open failure")

            monkeypatch.setattr(capture, "start", start_then_fail)
            return capture

        monkeypatch.setattr(rig.audio, "_new_test_capture", broken_capture)
        assert_error(
            await rig.call("mic_test_start", device_id=None), ErrorCode.STORAGE_ERROR
        )
        assert rig.lease.holder is None


@pytest.mark.asyncio
async def test_T_APP_028_dictionary_types_and_empty_history_text(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as rig:
        for entry in (
            {"spelling": "Bad", "aliases": "alias"},
            {"spelling": "Bad", "aliases": [1]},
        ):
            assert_error(await rig.call("dict_add", entry=entry), ErrorCode.VALIDATION)
        for entry_id in (True, "1"):
            assert_error(
                await rig.call("dict_update", id=entry_id, entry={"spelling": "Good"}),
                ErrorCode.VALIDATION,
            )
            assert_error(
                await rig.call("dict_delete", id=entry_id), ErrorCode.VALIDATION
            )

        started = await rig.call("run_start", request_id="without-output")
        assert started.ok
        run_id = started.data["run_id"]
        listed = (await rig.call("history_list")).data["runs"]
        assert listed[0]["run_id"] == run_id
        assert listed[0]["text"] is None


@pytest.mark.asyncio
async def test_T_APP_025_history_copy_uses_only_clipboard(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        run_id = await rig.finished_run("copy")
        result = await rig.call("history_copy", run_id=run_id)
        assert result.ok and result.data == {"run_id": run_id}
        assert rig.clipboard == [await rig.controller.copy_text(run_id)]
        assert not any(name == "send_inputs" for name, _, _ in rig.win.calls)
        assert "PRIVATE DICTATION SENTINEL" not in str(result)


@pytest.mark.asyncio
async def test_T_APP_026_mic_levels_conflicts_stop_and_timeout(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        assert (await rig.call("mic_list")).data == {
            "devices": [{"device_id": 2, "name": "Test input", "is_default": True}]
        }
        run_id = (await rig.call("run_start", request_id="mic-conflict")).data["run_id"]
        assert_error(
            await rig.call("mic_test_start", device_id=2),
            ErrorCode.DEVICE_LEASE_CONFLICT,
        )
        await rig.call("run_cancel", run_id=run_id)
        await rig.controller.settled(run_id)
        assert (await rig.call("mic_test_start", device_id=2)).ok
        assert rig.last_device_id == 2
        assert_error(
            await rig.call("mic_test_start", device_id=2),
            ErrorCode.DEVICE_LEASE_CONFLICT,
        )
        chunk = CaptureChunk(np.zeros(1280, dtype=np.float32), [0.1, 0.2])
        rig.test_captures[-1].queue(chunk)
        await asyncio.wait_for(rig.test_captures[-1].pumped.wait(), 1)
        levels = rig.events.by_name("audio:level")
        assert levels and levels[-1] == {
            "name": "audio:level",
            "run_id": None,
            "bands": [0.1, 0.2],
        }
        assert (await rig.call("mic_test_stop")).data == {"stopped": True}
        assert rig.lease.holder is None
        assert (await rig.call("mic_test_stop")).data == {"stopped": False}
        assert (await rig.call("mic_test_start", device_id=None)).ok
        await asyncio.wait_for(_wait_until(lambda: rig.lease.holder is None), 1)
        assert rig.test_captures[-1].stopped
        event_count = len(rig.events.events)
        rig.fail_next_test_pump = True
        assert (await rig.call("mic_test_start", device_id=None)).ok
        await asyncio.wait_for(_wait_until(lambda: rig.lease.holder is None), 1)
        assert len(rig.events.events) == event_count


async def _wait_until(predicate: Callable[[], bool]) -> None:
    while not predicate():
        await asyncio.sleep(0.001)


@pytest.mark.asyncio
async def test_T_APP_027_text_never_leaks_into_logs_or_events(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async with scenario(tmp_path) as rig:
        with caplog.at_level(logging.DEBUG):
            await _assert_private_commands(rig, caplog)


async def _assert_private_commands(rig: Rig, caplog: pytest.LogCaptureFixture) -> None:
    secret = "PRIVATE DICTATION SENTINEL"
    await rig.call("dict_add", entry={"spelling": "PrivateTerm"})
    run_id = await rig.finished_run("privacy")
    assert (await rig.call("history_get", run_id=run_id)).data["text"] == secret
    assert (await rig.call("history_list")).data["runs"][0]["text"] == secret
    for name, fields in (
        ("history_copy", {"run_id": run_id}),
        ("history_delete", {"run_id": run_id}),
        ("dict_export", {}),
    ):
        result = await rig.call(name, **fields)
        assert result.ok
        assert secret not in str(result)
    assert secret not in caplog.text
    assert secret not in json.dumps(rig.events.events)
