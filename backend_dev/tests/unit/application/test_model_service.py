"""WO-M4b model readiness and command contracts."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from fakes.events import FakeEventSink

from wispr_clone.application.api import Api
from wispr_clone.application.commands.model_commands import ModelCommands
from wispr_clone.application.model_service import ModelService
from wispr_clone.cleanup.lmstudio_cleanup import LmStudioCleanup
from wispr_clone.contracts.common import ErrorCode, ThirdPartyError, WisprError
from wispr_clone.history.repo import HistoryRepo
from wispr_clone.models.registry import ModelInfo, ModelRegistry, default_registry
from wispr_clone.settings.store import SettingsStore
from wispr_clone.storage import Database, Migration
from wispr_clone.storage.migrations import (
    m001_base,
    m002_settings,
    m003_dictionary,
    m004_history,
)

STT_ID = "openai/whisper-large-v3-turbo"
CLEANUP_ID = "meta-llama-3.1-8b-instruct"
OTHER_LOCAL_ID = "other-local-cleanup"
OTHER_STT_ID = "other-local-stt"
CLOUD_ID = "cloud-cleanup"


class RecordingStt:
    def __init__(self, ready: bool = True) -> None:
        self.ready = ready
        self.start_calls = 0

    async def start(self) -> None:
        self.start_calls += 1


class RecordingCleanup:
    def __init__(self, response: bool | Exception = True) -> None:
        self.response = response
        self.health_calls = 0
        self.clean_calls = 0

    async def health(self) -> bool:
        self.health_calls += 1
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    async def clean(self, request: object) -> str:
        self.clean_calls += 1
        raise AssertionError("model readiness must not send a cleanup request")


class HangingCleanup(RecordingCleanup):
    async def health(self) -> bool:
        self.health_calls += 1
        await asyncio.Event().wait()
        return True


class Rig:
    def __init__(
        self, store: SettingsStore, registry: ModelRegistry, events: FakeEventSink
    ) -> None:
        self.store = store
        self.events = events
        self.stt = RecordingStt()
        self.cleanup = RecordingCleanup()
        self.other_cleanup = RecordingCleanup()
        self.other_stt = RecordingStt()
        self.cloud_cleanup = RecordingCleanup()
        self.stt_engines: dict[str, RecordingStt] = {
            STT_ID: self.stt,
            OTHER_STT_ID: self.other_stt,
        }
        self.cleanup_engines: dict[str, RecordingCleanup] = {
            CLEANUP_ID: self.cleanup,
            OTHER_LOCAL_ID: self.other_cleanup,
            CLOUD_ID: self.cloud_cleanup,
        }
        self.cleanup_contacts: list[str] = []
        self.service = ModelService(
            registry,
            store,
            stt_for=self.stt_for,
            cleanup_for=self.cleanup_for,
            events=events,
            health_timeout_s=0.01,
        )

    def stt_for(self, model_id: str) -> RecordingStt | None:
        return self.stt_engines.get(model_id)

    def cleanup_for(self, model_id: str) -> RecordingCleanup | None:
        self.cleanup_contacts.append(model_id)
        return self.cleanup_engines.get(model_id)


@asynccontextmanager
async def scenario(path: Path) -> AsyncIterator[Rig]:
    registry = ModelRegistry(
        (
            *default_registry().list_models(),
            ModelInfo(OTHER_LOCAL_ID, "cleanup", "Other local", True, None),
            ModelInfo(OTHER_STT_ID, "stt", "Other STT", True, None),
            ModelInfo(CLOUD_ID, "cleanup", "Cloud", False, None),
        )
    )
    migrations = [
        Migration(module.VERSION, module.NAME, module.apply)
        for module in (m001_base, m002_settings, m003_dictionary, m004_history)
    ]
    async with Database(path / "model-service.db", migrations) as db:
        store = SettingsStore(db, registry)
        await store.load()
        yield Rig(store, registry, FakeEventSink())


def item(
    model_id: str, role: str, ready: bool, error_code: str | None = None
) -> dict[str, object]:
    return {
        "model_id": model_id,
        "role": role,
        "ready": ready,
        "error_code": error_code,
    }


@pytest.mark.asyncio
async def test_T_APP_005_poll_preserves_active_run_and_publishes_only_changes(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as rig:
        migrations = [
            Migration(module.VERSION, module.NAME, module.apply)
            for module in (m001_base, m002_settings, m003_dictionary, m004_history)
        ]
        async with Database(tmp_path / "runs.db", migrations) as db:
            history = HistoryRepo(
                db, clock=lambda: 100.0, audio_dir=tmp_path, events=rig.events
            )
            before = await history.create_run(
                run_id="active", start_request_id="start-active", config={}
            )
            rig.events.publish(
                {
                    "name": "run:state",
                    "run_id": before.id,
                    "version": before.version,
                    "status": before.status.value,
                }
            )
            baseline = list(rig.events.events)
            await rig.service.poll()
            assert rig.events.events[len(baseline) :] == [
                {
                    "name": "models:status",
                    "models": [
                        item(STT_ID, "stt", True),
                        item(CLEANUP_ID, "cleanup", True),
                    ],
                }
            ]
            await rig.service.poll()
            assert len(rig.events.events) == len(baseline) + 1
            rig.cleanup.response = False
            await rig.service.poll()
            assert rig.events.events[-1] == {
                "name": "models:status",
                "models": [
                    item(STT_ID, "stt", True),
                    item(CLEANUP_ID, "cleanup", False, "cleanup_unavailable"),
                ],
            }
            assert len(rig.events.by_name("run:state")) == 1
            assert rig.events.by_name("run:recovery") == []
            after = await history.get("active")
            assert (after.status, after.version) == (before.status, before.version)


@pytest.mark.asyncio
async def test_T_APP_006_cloud_selection_and_test_are_allowed(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        assert await rig.service.test(CLOUD_ID) == item(CLOUD_ID, "cleanup", True)
        selected = await rig.service.select(CLOUD_ID)
        assert selected["settings"]["cleanup_model_id"] == CLOUD_ID
        assert rig.store.current().cleanup_model_id == CLOUD_ID
        assert rig.cleanup_contacts


@pytest.mark.asyncio
async def test_T_APP_013_status_and_test_readiness_codes(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        rig.stt.ready = False
        assert await rig.service.status() == [
            item(STT_ID, "stt", False, "api_key_missing"),
            item(CLEANUP_ID, "cleanup", True),
        ]
        rig.stt_engines.clear()
        assert await rig.service.status() == [
            item(STT_ID, "stt", False, "stt_unavailable"),
            item(CLEANUP_ID, "cleanup", True),
        ]
        rig.cleanup.response = RuntimeError("private dependency detail")
        assert await rig.service.test(CLEANUP_ID) == item(
            CLEANUP_ID, "cleanup", False, "cleanup_unavailable"
        )
        rig.cleanup_engines.pop(CLEANUP_ID)
        assert await rig.service.test(CLEANUP_ID) == item(
            CLEANUP_ID, "cleanup", False, "cleanup_unavailable"
        )
        hanging = HangingCleanup()
        rig.cleanup_engines[CLEANUP_ID] = hanging
        assert await rig.service.test(CLEANUP_ID) == item(
            CLEANUP_ID, "cleanup", False, "cleanup_timeout"
        )
        assert hanging.health_calls == 1


@pytest.mark.asyncio
async def test_T_APP_014_select_persists_and_unknown_id_is_validation(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as rig:
        result = await rig.service.select(OTHER_LOCAL_ID)
        assert result == {
            "settings": rig.store.current().model_dump(mode="json"),
            "models": [
                item(STT_ID, "stt", True),
                item(OTHER_LOCAL_ID, "cleanup", True),
            ],
        }
        assert (await rig.store.load()).cleanup_model_id == OTHER_LOCAL_ID
        assert rig.events.by_name("models:status") == [
            {"name": "models:status", "models": result["models"]}
        ]
        for operation in (rig.service.select, rig.service.test):
            with pytest.raises(WisprError) as error:
                await operation("missing-model")
            assert error.value.error_code == ErrorCode.VALIDATION
            assert error.value.where == "models"
            assert error.value.why == "model_id"


@pytest.mark.asyncio
async def test_T_APP_015_readiness_operations_never_load_models(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        await rig.service.status()
        await rig.service.test(OTHER_LOCAL_ID)
        await rig.service.select(OTHER_LOCAL_ID)
        await rig.service.poll()
        assert rig.stt.start_calls == 0
        assert all(
            engine.clean_calls == 0
            for engine in (rig.cleanup, rig.other_cleanup, rig.cloud_cleanup)
        )


@pytest.mark.asyncio
async def test_T_APP_016_model_commands_session_deadline_and_error_codes(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as rig:
        api = Api(
            ModelCommands(rig.service).specs(),
            session_token="session-1",
            clock=lambda: 100.0,
        )
        for name, fields in (
            ("models_status", {}),
            ("models_test", {"model_id": OTHER_LOCAL_ID}),
            ("models_select", {"model_id": OTHER_LOCAL_ID, "deadline": 105.0}),
        ):
            assert (
                await api.call(name, {"session_token": "wrong", **fields})
            ).error == ErrorCode.PREVIOUS_SESSION_TOKEN
        status = await api.call("models_status", {"session_token": "session-1"})
        assert status.ok and status.data == {"models": await rig.service.status()}
        tested = await api.call(
            "models_test", {"session_token": "session-1", "model_id": OTHER_LOCAL_ID}
        )
        assert tested.ok and tested.data == item(OTHER_LOCAL_ID, "cleanup", True)
        missing_deadline = await api.call(
            "models_select", {"session_token": "session-1", "model_id": OTHER_LOCAL_ID}
        )
        assert missing_deadline.error == ErrorCode.VALIDATION
        selected = await api.call(
            "models_select",
            {
                "session_token": "session-1",
                "deadline": 105.0,
                "model_id": OTHER_LOCAL_ID,
            },
        )
        assert (
            selected.ok
            and selected.data["settings"]["cleanup_model_id"] == OTHER_LOCAL_ID
        )
        invalid = await api.call(
            "models_test", {"session_token": "session-1", "model_id": "missing"}
        )
        assert invalid.error == ErrorCode.VALIDATION
        allowed = await api.call(
            "models_test", {"session_token": "session-1", "model_id": CLOUD_ID}
        )
        assert allowed.ok and allowed.data == item(CLOUD_ID, "cleanup", True)
        repeated = await api.call(
            "models_test", {"session_token": "session-1", "model_id": CLOUD_ID}
        )
        assert repeated.ok and repeated.data == item(CLOUD_ID, "cleanup", True)


@pytest.mark.asyncio
async def test_T_APP_017_health_must_return_a_bool(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        rig.cleanup.response = "loaded"  # type: ignore[assignment]
        assert await rig.service.test(CLEANUP_ID) == item(
            CLEANUP_ID, "cleanup", False, "cleanup_unavailable"
        )


@pytest.mark.asyncio
async def test_T_APP_017_stale_poll_must_not_publish_after_select(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as rig:
        entered = asyncio.Event()
        release = asyncio.Event()
        rig.service._health_timeout_s = 1.0

        class PausedCleanup(RecordingCleanup):
            async def health(self) -> bool:
                entered.set()
                await release.wait()
                return True

        rig.cleanup_engines[CLEANUP_ID] = PausedCleanup()
        poll = asyncio.create_task(rig.service.poll())
        try:
            await asyncio.wait_for(entered.wait(), 1)
            await rig.service.select(OTHER_LOCAL_ID)
        finally:
            release.set()
            await poll
        published = rig.events.by_name("models:status")
        assert len(published) == 1
        assert published[0]["models"][1]["model_id"] == OTHER_LOCAL_ID


@pytest.mark.asyncio
async def test_T_APP_017_select_result_cannot_mutate_published_event(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as rig:
        status = await rig.service.status()
        status.clear()
        assert len(await rig.service.status()) == 2
        result = await rig.service.select(OTHER_LOCAL_ID)
        models = result["models"]
        assert isinstance(models, list)
        models.clear()
        assert rig.events.by_name("models:status")[0]["models"] == [
            item(STT_ID, "stt", True),
            item(OTHER_LOCAL_ID, "cleanup", True),
        ]


@pytest.mark.asyncio
async def test_T_APP_017_cloud_models_and_registered_role(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        stt_result = await rig.service.select(OTHER_STT_ID)
        assert stt_result["settings"]["stt_model_id"] == OTHER_STT_ID
        selected = await rig.service.select(CLOUD_ID)
        assert selected["settings"]["cleanup_model_id"] == CLOUD_ID
        assert await rig.service.test(CLOUD_ID) == item(CLOUD_ID, "cleanup", True)
        with pytest.raises(WisprError) as error:
            await rig.service.select(STT_ID, role="cleanup")
        assert error.value.error_code == ErrorCode.VALIDATION
        with pytest.raises(WisprError) as error:
            await rig.store.update({"local_only": True})
        assert error.value.error_code == ErrorCode.VALIDATION


@pytest.mark.asyncio
async def test_T_APP_017_store_must_be_loaded_before_readiness(tmp_path: Path) -> None:
    migrations = [
        Migration(module.VERSION, module.NAME, module.apply)
        for module in (m001_base, m002_settings, m003_dictionary, m004_history)
    ]
    async with Database(tmp_path / "unloaded.db", migrations) as db:
        store = SettingsStore(db, default_registry())
        service = ModelService(
            default_registry(),
            store,
            stt_for=lambda _: None,
            cleanup_for=lambda _: None,
            events=FakeEventSink(),
        )
        with pytest.raises(WisprError) as error:
            await service.status()
        assert error.value.error_code == ErrorCode.STORAGE_ERROR


@pytest.mark.asyncio
async def test_T_APP_017_real_cleanup_readiness_does_not_load() -> None:
    requests: list[tuple[str, str]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        return httpx.Response(
            200,
            json={"data": [{"id": CLEANUP_ID, "state": "not-loaded"}]},
        )

    cleanup = LmStudioCleanup(
        model_id=CLEANUP_ID, transport=httpx.MockTransport(respond)
    )
    try:
        assert await cleanup.health() is False
        assert requests == [("GET", "/api/v0/models")]
    finally:
        await cleanup.aclose()


@pytest.mark.asyncio
async def test_T_APP_049_catalog_lists_live_models_and_keeps_current_choice(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as rig:

        async def stt_models() -> list[dict[str, object]]:
            return [{"model_id": "deepgram/nova-3", "display_name": "Nova-3"}]

        async def cleanup_models() -> list[dict[str, object]]:
            raise ThirdPartyError(
                "lmstudio", "models", "connect", ErrorCode.CLEANUP_UNAVAILABLE
            )

        rig.service._list_stt = stt_models
        rig.service._list_cleanup = cleanup_models
        catalog = await rig.service.catalog()
        # The saved choice is listed first and flagged when the provider dropped it.
        assert catalog["stt"] == {
            "models": [
                {
                    "model_id": STT_ID,
                    "display_name": "Whisper Large v3 Turbo (DeepInfra)",
                    "missing": True,
                },
                {"model_id": "deepgram/nova-3", "display_name": "Nova-3"},
            ],
            "error_code": None,
        }
        assert catalog["cleanup"] == {
            "provider": "lmstudio",
            "models": [
                {
                    "model_id": CLEANUP_ID,
                    "display_name": "Llama 3.1 8B Instruct",
                    "missing": False,
                },
            ],
            "error_code": "cleanup_unavailable",
        }


@pytest.mark.asyncio
async def test_T_APP_050_select_discovered_model_by_role(tmp_path: Path) -> None:
    async with scenario(tmp_path) as rig:
        result = await rig.service.select("qwen/qwen3-8b", "cleanup")
        assert result["settings"]["cleanup_model_id"] == "qwen/qwen3-8b"
        await rig.service.select("deepgram/nova-3", "stt")
        assert rig.store.current().stt_model_id == "deepgram/nova-3"
        with pytest.raises(WisprError) as error:
            await rig.service.select("no-vendor", "stt")
        assert error.value.error_code == ErrorCode.VALIDATION
        # Without a role only registered models can be chosen, as before.
        with pytest.raises(WisprError):
            await rig.service.select("qwen/qwen3-8b")


@pytest.mark.asyncio
async def test_T_APP_051_keeps_cleanup_model_loaded_and_backs_off(
    tmp_path: Path,
) -> None:
    async with scenario(tmp_path) as rig:
        now = [100.0]
        loads: list[str] = []
        seen_while_loading: list[object] = []
        outcome: list[object] = [True]

        async def load(model_id: str) -> bool:
            loads.append(model_id)
            rig.cleanup.response = False
            seen_while_loading.append((await rig.service.status())[1]["error_code"])
            result = outcome[0]
            if isinstance(result, Exception):
                raise result
            rig.cleanup.response = True
            return bool(result)

        rig.service._load_cleanup = load
        rig.service._clock = lambda: now[0]
        await rig.service.keep_cleanup_loaded()
        assert loads == [CLEANUP_ID]
        assert seen_while_loading == ["model_loading"]
        assert rig.events.by_name("models:status")[-1]["models"][1]["ready"] is True

        outcome[0] = ThirdPartyError(
            "lmstudio", "load", "http 500", ErrorCode.MODEL_LOAD_FAILED
        )
        await rig.service.keep_cleanup_loaded()
        await rig.service.keep_cleanup_loaded()  # inside the retry window: skipped
        assert len(loads) == 2
        await rig.service.keep_cleanup_loaded(force=True)  # a new selection retries now
        assert len(loads) == 3
        now[0] += 61
        outcome[0] = True
        await rig.service.keep_cleanup_loaded()
        assert len(loads) == 4

        await rig.store.update({"cleanup_enabled": False})
        await rig.service.keep_cleanup_loaded(force=True)
        assert len(loads) == 4


@pytest.mark.asyncio
async def test_provider_edit_invalidates_a_pending_local_health_poll(
    tmp_path: Path,
) -> None:
    from wispr_clone.application.commands.settings_commands import SettingsCommands

    async with scenario(tmp_path) as rig:
        entered, release = asyncio.Event(), asyncio.Event()

        class PausedCleanup(RecordingCleanup):
            async def health(self) -> bool:
                entered.set()
                await release.wait()
                return True

        rig.service._health_timeout_s = 1.0
        rig.cleanup_engines[CLEANUP_ID] = PausedCleanup()
        commands = SettingsCommands(
            rig.store,
            None,
            None,
            session_token=lambda: "test-session",
            readiness=rig.service.status,
            model_service=rig.service,
        )
        poll = asyncio.create_task(rig.service.poll())
        try:
            await asyncio.wait_for(entered.wait(), 1.0)
            result = await commands.specs()["settings_update"].handler(
                {
                    "patch": {"cleanup_provider": "nvidia"},
                }
            )
            assert result["cleanup_provider"] == "nvidia"
            await rig.service.poll()
        finally:
            release.set()
            await poll
        events = rig.events.by_name("models:status")
        assert len(events) == 1
        assert events[-1]["models"][1]["model_id"] == "deepseek-ai/deepseek-v4.1-flash"
