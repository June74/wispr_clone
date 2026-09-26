"""WO-M4a application command contracts (RED until application exists)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from fakes.audio import FakeCapture
from fakes.clock import FakeClock
from fakes.events import FakeEventSink
from fakes.insertion import FakeUiaApi, FakeWin32Api
from fakes.stt import FakeSttEngine
from wispr_clone.application.api import Api, CommandSpec
from wispr_clone.application.commands.run_commands import RunCommands
from wispr_clone.application.commands.settings_commands import SettingsCommands

from wispr_clone.audio.wav_writer import WavWriter
from wispr_clone.contracts.common import ErrorCode, ThirdPartyError, WisprError
from wispr_clone.contracts.run import RecoveryAction, RunStatus
from wispr_clone.dictionary.repo import DictionaryRepo
from wispr_clone.history.repo import HistoryRepo
from wispr_clone.insertion.destination import capture
from wispr_clone.models.registry import default_registry
from wispr_clone.pipeline.insertion_protocol import InsertionProtocol
from wispr_clone.pipeline.run_controller import RunController, RunServices
from wispr_clone.settings.store import SettingsStore
from wispr_clone.storage import Database, Migration
from wispr_clone.storage.migrations import (
    m001_base,
    m002_settings,
    m003_dictionary,
    m004_history,
)


class Rig:
    def __init__(
        self,
        controller: RunController,
        history: HistoryRepo,
        store: SettingsStore,
        clock: FakeClock,
        events: FakeEventSink,
        win: FakeWin32Api,
        destination: object,
    ) -> None:
        self.controller = controller
        self.history = history
        self.store = store
        self.clock = clock
        self.events = events
        self.win = win
        self.destination = destination
        self.clipboard: list[str] = []
        self.selected_destination: object | None = None
        self.readiness = [{"model_id": "ready-stt", "ready": True}]
        self.runs = RunCommands(
            controller,
            clock=clock.now,
            copy_to_clipboard=self.copy,
            last_external_destination=lambda: self.selected_destination,
        )
        self.settings = SettingsCommands(
            store,
            history,
            controller,
            session_token=lambda: "session-1",
            readiness=self.models,
        )
        self.api = Api(
            {**self.runs.specs(), **self.settings.specs()},
            session_token="session-1",
            clock=clock.now,
        )

    async def copy(self, value: str) -> None:
        self.clipboard.append(value)

    async def models(self) -> list[dict[str, object]]:
        return self.readiness

    async def call(self, name: str, **fields: object) -> Any:
        return await self.api.call(
            name,
            {"session_token": "session-1", "deadline": self.clock.now() + 5, **fields},
        )

    def sends(self) -> int:
        return sum(name == "send_inputs" for name, _, _ in self.win.calls)


@asynccontextmanager
async def scenario(path: Path) -> AsyncIterator[Rig]:
    migrations = [
        Migration(module.VERSION, module.NAME, module.apply)
        for module in (m001_base, m002_settings, m003_dictionary, m004_history)
    ]
    async with Database(path / "application.db", migrations) as db:
        clock = FakeClock(100)
        events = FakeEventSink()
        history = HistoryRepo(db, clock=clock.now, audio_dir=path, events=events)
        store = SettingsStore(db, default_registry())
        await store.load()
        win, uia = FakeWin32Api(), FakeUiaApi()
        destination = capture(win, uia)
        win.calls.clear()
        uia.calls.clear()
        stt = FakeSttEngine("private dictated words")
        captures: list[FakeCapture] = []
        ids = iter(f"run-{index}" for index in range(20))

        async def inline(operation: Callable[[], Any]) -> Any:
            return operation()

        async def capture_destination() -> Any:
            return destination

        def new_capture() -> FakeCapture:
            result = FakeCapture()
            captures.append(result)
            return result

        controller = RunController(
            RunServices(
                history=history,
                dictionary=DictionaryRepo(db, clock=clock.now),
                stt=stt,
                insertion=InsertionProtocol(
                    history,
                    win,
                    uia,
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
        yield Rig(controller, history, store, clock, events, win, destination)
        if controller.active_run_id is not None:
            await controller.cancel_current()


def assert_error(result: Any, code: ErrorCode) -> None:
    assert result.ok is False
    assert result.data is None
    assert result.error == code


@pytest.mark.asyncio
async def test_T_APP_001_router_errors_and_private_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "PRIVATE PAYLOAD SENTINEL"

    async def known(_: Mapping[str, object]) -> Mapping[str, object]:
        raise WisprError(ErrorCode.VALIDATION, "test", secret)

    async def third_party(_: Mapping[str, object]) -> Mapping[str, object]:
        raise ThirdPartyError("test", "read", secret, ErrorCode.STT_UNAVAILABLE)

    async def unexpected(_: Mapping[str, object]) -> Mapping[str, object]:
        raise RuntimeError(secret)

    api = Api(
        {
            "known": CommandSpec(known, mutating=False),
            "third_party": CommandSpec(third_party, mutating=False),
            "unexpected": CommandSpec(unexpected, mutating=False),
        },
        session_token="session-1",
        clock=lambda: 100.0,
    )
    with caplog.at_level(logging.DEBUG):
        assert_error(
            await api.call("missing", {"secret": secret}), ErrorCode.UNKNOWN_COMMAND
        )
        for name, code in (
            ("known", ErrorCode.VALIDATION),
            ("third_party", ErrorCode.STT_UNAVAILABLE),
            ("unexpected", ErrorCode.STORAGE_ERROR),
        ):
            assert_error(
                await api.call(name, {"session_token": "session-1", "secret": secret}),
                code,
            )
    assert secret not in caplog.text


@pytest.mark.asyncio
async def test_T_APP_002_start_deduplicates_serial_and_concurrent(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as rig:
        first = await rig.call("run_start", request_id="same")
        second = await rig.call("run_start", request_id="same")
        assert first.data == {"run_id": "run-0", "deduplicated": False}
        assert second.data == {"run_id": "run-0", "deduplicated": True}
        assert len(await rig.history.list_runs()) == 1
        await rig.call("run_cancel", run_id="run-0")
        await rig.controller.settled("run-0")
        original_start = rig.controller.start
        entered = asyncio.Event()
        release = asyncio.Event()
        start_calls = 0

        async def gated_start(*, start_request_id: str) -> str:
            nonlocal start_calls
            start_calls += 1
            entered.set()
            await release.wait()
            return await original_start(start_request_id=start_request_id)

        rig.controller.start = gated_start  # type: ignore[method-assign]
        left_task = asyncio.create_task(rig.call("run_start", request_id="concurrent"))
        await entered.wait()
        right_task = asyncio.create_task(rig.call("run_start", request_id="concurrent"))
        await asyncio.sleep(0)
        release.set()
        left, right = await asyncio.gather(left_task, right_task)
        assert {left.data["deduplicated"], right.data["deduplicated"]} == {False, True}
        assert left.data["run_id"] == right.data["run_id"] == "run-1"
        assert start_calls == 1
        assert len(await rig.history.list_runs()) == 2


@pytest.mark.asyncio
async def test_T_APP_003_session_deadline_and_reconnect(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        for payload, code in (
            (
                {"session_token": "old", "deadline": 105, "request_id": "a"},
                ErrorCode.PREVIOUS_SESSION_TOKEN,
            ),
            (
                {"session_token": "session-1", "deadline": 99, "request_id": "a"},
                ErrorCode.EXPIRED_COMMAND,
            ),
            (
                {"session_token": "session-1", "deadline": 131, "request_id": "a"},
                ErrorCode.VALIDATION,
            ),
            ({"session_token": "session-1", "request_id": "a"}, ErrorCode.VALIDATION),
            (
                {"session_token": "session-1", "deadline": "105", "request_id": "a"},
                ErrorCode.VALIDATION,
            ),
        ):
            assert_error(await rig.api.call("run_start", payload), code)
        state = await rig.api.call("state_get", {})
        assert state.ok and state.data["session_token"] == "session-1"
        assert await rig.history.list_runs() == ()


@pytest.mark.asyncio
async def test_T_APP_004_invalidated_start_cannot_recreate_run(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        first = await rig.call("run_start", request_id="deleted-request")
        run_id = first.data["run_id"]
        await rig.call("run_cancel", run_id=run_id)
        await rig.controller.settled(run_id)
        rig.runs.invalidate(run_id)
        assert_error(
            await rig.call("run_start", request_id="deleted-request"),
            ErrorCode.RUN_DELETED,
        )
        assert len(await rig.history.list_runs()) == 1


@pytest.mark.asyncio
async def test_T_APP_007_state_snapshot_is_ordered_and_private(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        first = (await rig.call("run_start", request_id="one")).data["run_id"]
        rig.win.foreground = 20
        await rig.call("run_stop", run_id=first)
        await rig.controller.settled(first)
        rig.clock.advance(1)
        second = (await rig.call("run_start", request_id="two")).data["run_id"]
        state = await rig.api.call("state_get", {})
        assert state.ok
        assert state.data["session_token"] == "session-1"
        assert state.data["settings"] == rig.store.current().model_dump(mode="json")
        assert state.data["models"] == rig.readiness
        assert state.data["active_run_id"] == second
        runs = state.data["runs"]
        assert [item["run_id"] for item in runs] == [second, first]
        for item in runs:
            assert set(item) == {"run_id", "version", "status", "created_at", "actions"}
            assert item["actions"] == sorted(item["actions"])
        assert "copy" in runs[1]["actions"]
        assert "private dictated words" not in str(state.data)


@pytest.mark.asyncio
async def test_T_APP_008_copy_only_to_clipboard(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        run_id = (await rig.call("run_start", request_id="copy")).data["run_id"]
        rig.win.foreground = 20
        await rig.call("run_stop", run_id=run_id)
        before = await rig.controller.settled(run_id)
        result = await rig.call(
            "run_recover",
            run_id=run_id,
            expected_version=before.version,
            action=RecoveryAction.COPY.value,
        )
        assert result.ok and result.data == {"run_id": run_id}
        assert rig.clipboard == [await rig.controller.copy_text(run_id)]
        after = await rig.history.get(run_id)
        assert (after.status, after.version) == (before.status, before.version)
        assert rig.sends() == 0
        assert "private dictated words" not in str(result)


@pytest.mark.asyncio
async def test_T_APP_009_selected_destination_requires_snapshot(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        run_id = (await rig.call("run_start", request_id="insert")).data["run_id"]
        rig.win.foreground = 20
        await rig.call("run_stop", run_id=run_id)
        held = await rig.controller.settled(run_id)
        assert held.status in {RunStatus.HELD, RunStatus.AWAITING_DESTINATION}
        payload = {
            "run_id": run_id,
            "expected_version": held.version,
            "action": RecoveryAction.INSERT.value,
            "use_selected_destination": True,
        }
        assert_error(
            await rig.call("run_recover", **payload), ErrorCode.DESTINATION_UNVERIFIABLE
        )
        rig.selected_destination = rig.destination
        original_recover = rig.controller.recover
        received: list[object | None] = []

        async def tracked_recover(*args: Any, **kwargs: Any) -> None:
            received.append(kwargs.get("destination"))
            await original_recover(*args, **kwargs)

        rig.controller.recover = tracked_recover  # type: ignore[method-assign]
        result = await rig.call("run_recover", **payload)
        assert result.ok and result.data == {"run_id": run_id}
        assert received == [rig.destination]


@pytest.mark.asyncio
async def test_T_APP_010_cancel_current_and_repeated_commands(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        run_id = (await rig.call("run_start", request_id="cancel")).data["run_id"]
        assert (await rig.call("run_cancel")).data == {"run_id": run_id}
        await rig.controller.settled(run_id)
        count = len(rig.events.by_name("run:state"))
        assert (await rig.call("run_cancel", run_id=run_id)).ok
        assert (await rig.call("run_stop", run_id=run_id)).ok
        assert (await rig.call("run_cancel")).data == {"run_id": None}
        assert len(rig.events.by_name("run:state")) == count


@pytest.mark.asyncio
async def test_T_APP_011_settings_patch_validation_and_persistence(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as rig:
        assert_error(
            await rig.call("settings_update", patch={"theme": "neon"}),
            ErrorCode.VALIDATION,
        )
        changed = await rig.call("settings_update", patch={"theme": "dark"})
        assert changed.ok
        assert changed.data["theme"] == "dark"
        assert (await rig.call("settings_get")).data == changed.data
        assert (await rig.store.load()).theme == "dark"
