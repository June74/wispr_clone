"""Application composition root and worker/GUI lifecycle."""

from __future__ import annotations

import asyncio
import ctypes
import os
import secrets
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol, cast

from wispr_clone import config
from wispr_clone.application.api import Api, CommandSpec
from wispr_clone.application.commands.audio_commands import AudioCommands
from wispr_clone.application.commands.dictionary_commands import DictionaryCommands
from wispr_clone.application.commands.history_commands import HistoryCommands
from wispr_clone.application.commands.model_commands import ModelCommands
from wispr_clone.application.commands.run_commands import RunCommands
from wispr_clone.application.commands.settings_commands import SettingsCommands
from wispr_clone.application.model_service import ModelService
from wispr_clone.audio.capture import AudioCapture
from wispr_clone.audio.device_lease import DeviceLease, LeaseOwner
from wispr_clone.audio.devices import InputDevice, list_input_devices
from wispr_clone.audio.wav_writer import WavWriter
from wispr_clone.cleanup.base import CleanupEngine
from wispr_clone.cleanup.lmstudio_cleanup import LmStudioCleanup
from wispr_clone.contracts.events import EventPayload, EventSink
from wispr_clone.contracts.run import RunStatus
from wispr_clone.dictionary.repo import DictionaryRepo
from wispr_clone.history.repo import HistoryRepo
from wispr_clone.hotkeys.hotkey_service import HotkeyService
from wispr_clone.insertion.destination import DestinationSnapshot, capture
from wispr_clone.insertion.uia import UiaApi
from wispr_clone.insertion.win32 import Win32Api
from wispr_clone.models.registry import default_registry
from wispr_clone.pipeline.insertion_protocol import InsertionProtocol
from wispr_clone.pipeline.run_controller import RunController, RunServices
from wispr_clone.pipeline.state_machine import RunEvent, RunState, transition
from wispr_clone.settings.schema import Settings
from wispr_clone.settings.store import SettingsStore
from wispr_clone.storage.db import Database
from wispr_clone.stt.base import SttEngine
from wispr_clone.ui.bridge import Bridge
from wispr_clone.ui.events import WebviewEventSink
from wispr_clone.ui.overlay import open_hud
from wispr_clone.ui.windows import open_settings
from wispr_clone.ui.windows import start as start_webview


class CaptureLike(Protocol):
    def start(self) -> None: ...
    def chunks(self) -> Any: ...
    def stop(self) -> None: ...
    def cancel(self) -> None: ...


class ListenerLike(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...


@dataclass(frozen=True, slots=True)
class AppFactories:
    open_database: Callable[[Path], Database]
    stt_engine: Callable[[Settings], SttEngine]
    cleanup_for: Callable[[str], CleanupEngine | None]
    win32: Callable[[], Win32Api]
    uia: Callable[[], UiaApi]
    new_capture: Callable[[DeviceLease, int | None, LeaseOwner], CaptureLike]
    list_devices: Callable[[], tuple[InputDevice, ...]]
    hotkey_listener: Callable[[HotkeyService], ListenerLike]
    webview: Callable[[], Any] | None
    clock: Callable[[], float]
    monotonic: Callable[[], float]


def real_factories() -> AppFactories:
    """Create lazy adapters; platform libraries load only when a factory is used."""

    def stt(settings: Settings) -> SttEngine:
        import importlib

        del settings
        native = importlib.import_module("transcribe_cpp")
        from wispr_clone.stt.voxtral_transcribe_cpp import VoxtralTranscribeCpp

        return VoxtralTranscribeCpp(config.stt_model_path(), module=native)

    def cleanup(model_id: str) -> CleanupEngine:
        return LmStudioCleanup(model_id=model_id, base_url=config.LM_STUDIO_ENDPOINT)

    def make_capture(
        lease: DeviceLease, device: int | None, owner: LeaseOwner
    ) -> CaptureLike:
        import sounddevice  # type: ignore[import-untyped]

        return AudioCapture(lease, device_id=device, owner=owner, module=sounddevice)

    def devices() -> tuple[InputDevice, ...]:
        import sounddevice

        return list_input_devices(sounddevice)

    def listener(service: HotkeyService) -> ListenerLike:
        import importlib

        keyboard = importlib.import_module("pynput.keyboard")
        from wispr_clone.hotkeys.pynput_listener import PynputListener

        return PynputListener(service, module=keyboard)

    def win32() -> Win32Api:
        from wispr_clone.insertion.win32 import RealWin32

        return RealWin32()

    def uia() -> UiaApi:
        from wispr_clone.insertion.uia import RealUia

        return RealUia()

    def webview_factory() -> Any:
        import webview  # type: ignore[import-not-found]

        return webview

    return AppFactories(
        open_database=Database,
        stt_engine=stt,
        cleanup_for=cleanup,
        win32=win32,
        uia=uia,
        new_capture=make_capture,
        list_devices=devices,
        hotkey_listener=listener,
        webview=webview_factory,
        clock=time.time,
        monotonic=time.monotonic,
    )


class MemoryEvents(EventSink):
    def __init__(self) -> None:
        self.events: list[EventPayload] = []

    def publish(self, event: EventPayload) -> None:
        self.events.append(event)


class EventRouter(EventSink):
    """Keep service event references stable while selecting a UI sink."""

    def __init__(self) -> None:
        self.target: EventSink = MemoryEvents()
        self.hud: Any = None

    def publish(self, event: EventPayload) -> None:
        self.target.publish(event)
        if self.hud is None or event["name"] != "run:state":
            return
        if event.get("status") in {
            "recording",
            "processing",
            "awaiting_cleanup_choice",
            "awaiting_destination",
        }:
            self.hud.show()
        else:
            try:
                asyncio.get_running_loop().call_later(1.5, self.hud.hide)
            except RuntimeError:
                pass


class SingleInstance:
    """Keep an OS mutex or advisory lock held until application shutdown."""

    def __init__(self, handle: Any, file: Any = None) -> None:
        self._handle = handle
        self._file = file
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        if self._file is not None:
            try:
                if os.name == "nt":
                    import msvcrt

                    self._file.seek(0)
                    cast(Any, msvcrt).locking(
                        self._file.fileno(), cast(Any, msvcrt).LK_UNLCK, 1
                    )
                else:
                    import fcntl

                    fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            finally:
                self._file.close()
        if self._handle:
            cast(Any, ctypes).windll.kernel32.CloseHandle(self._handle)


def acquire_single_instance(
    name: str = "WisprClone", *, lock_dir: Path | None = None
) -> SingleInstance | None:
    if sys.platform == "win32" and lock_dir is None:
        kernel = cast(Any, ctypes).windll.kernel32
        handle = kernel.CreateMutexW(None, False, f"Local\\{name}")
        if not handle:
            raise OSError("mutex unavailable")
        if kernel.GetLastError() == 183:
            kernel.CloseHandle(handle)
            return None
        return SingleInstance(handle)
    directory = lock_dir if lock_dir is not None else config.app_data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)
    lock_file = (directory / f".{safe_name}.lock").open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0)
            if lock_file.read(1) == b"":
                lock_file.seek(0)
                lock_file.write(b"0")
                lock_file.flush()
            lock_file.seek(0)
            try:
                cast(Any, msvcrt).locking(
                    lock_file.fileno(), cast(Any, msvcrt).LK_NBLCK, 1
                )
            except OSError:
                lock_file.close()
                return None
        else:
            import fcntl

            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                lock_file.close()
                return None
        return SingleInstance(None, lock_file)
    except BaseException:
        lock_file.close()
        raise


class App:
    def __init__(
        self, factories: AppFactories, *, data_dir: Path, debug: bool = False
    ) -> None:
        self.factories = factories
        self.data_dir = data_dir
        self.debug = debug
        self.startup_log: list[str] = []
        self.shutdown_log: list[str] = []
        self.timer_errors: dict[str, int] = {}
        self.insertion_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="wispr-insertion"
        )
        self._cleanup_cache: dict[str, CleanupEngine] = {}
        self._tasks: list[asyncio.Task[None]] = []
        self._timers: list[asyncio.Task[None]] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._worker: threading.Thread | None = None
        self._worker_ready = threading.Event()
        self._worker_done = threading.Event()
        self._worker_error: BaseException | None = None
        self._gui_thread_id: int | None = None
        self._instance: SingleInstance | None = None
        self._started = False
        self._closed = False
        self._win32: Win32Api | None = None
        self._uia: UiaApi | None = None
        self._destination: DestinationSnapshot | None = None
        self._last_hwnd: int | None = None
        self._windows: list[Any] = []
        self._hud: Any = None
        self._settings: Settings | None = None
        self._api: Api | None = None
        self._hotkey: HotkeyService | None = None
        self._listener: ListenerLike | None = None
        self._history: HistoryRepo | None = None
        self._db: Database | None = None
        self._stt: SttEngine | None = None
        self._controller: RunController | None = None
        self._run_commands: RunCommands | None = None
        self._audio_commands: AudioCommands | None = None
        self._model_service: ModelService | None = None
        self._events = EventRouter()
        self._run_ids: set[str] = set()

    @property
    def api(self) -> Api:
        if self._api is None:
            raise RuntimeError("app not started")
        return self._api

    def last_external_destination(self) -> DestinationSnapshot | None:
        return self._destination

    async def startup(self) -> None:
        if self._started:
            return
        self.data_dir.mkdir(parents=True, exist_ok=True)
        audio_dir = self.data_dir / "history"
        audio_dir.mkdir(parents=True, exist_ok=True)
        self.startup_log.append("directories")
        self._db = self.factories.open_database(self.data_dir / "wispr_clone.db")
        await self._db.open()
        self.startup_log.append("database")
        win32, uia = self.factories.win32(), self.factories.uia()
        self._win32, self._uia = win32, uia
        self._history = HistoryRepo(
            self._db,
            clock=self.factories.clock,
            audio_dir=audio_dir,
            events=self._events,
            on_run_evicted=self._on_evicted,
        )
        await self._history.recover_on_startup()
        self.startup_log.append("history_recovery")
        for record in await self._history.list_runs():
            if record.status in {RunStatus.RECORDING, RunStatus.PROCESSING}:
                failed = RunState(record.status, record.version)
                next_state = transition(failed, RunEvent.FAIL)
                await self._history.update_run(
                    record.id,
                    expected_version=record.version,
                    status=next_state.status,
                    error_code="storage_error",
                )
        self.startup_log.append("interrupted_runs")
        registry = default_registry()
        store = SettingsStore(self._db, registry)
        self._settings = await store.load()
        self.startup_log.append("settings")
        self._stt = self.factories.stt_engine(self._settings)
        lease = DeviceLease()
        self._model_service = ModelService(
            registry,
            store,
            stt_for=lambda model_id: (
                self._stt
                if self._settings and model_id == self._settings.stt_model_id
                else None
            ),
            cleanup_for=self._cleanup,
            events=self._events,
        )
        insertion = InsertionProtocol(
            self._history,
            self._win32,
            self._uia,
            offload=self._offload,
            clock=self.factories.monotonic,
            new_id=lambda: secrets.token_urlsafe(18),
        )
        dictionary = DictionaryRepo(self._db, clock=self.factories.clock)

        async def destination() -> DestinationSnapshot:
            return cast(
                DestinationSnapshot,
                await self._offload(
                    lambda: capture(win32, uia, exclude_pids=frozenset({os.getpid()}))
                ),
            )

        def new_run_capture() -> CaptureLike:
            device = self._settings.microphone_id if self._settings else None
            device_id = int(device) if device and device.isdigit() else None
            return self.factories.new_capture(lease, device_id, "capture")

        self._controller = RunController(
            RunServices(
                history=self._history,
                dictionary=dictionary,
                stt=self._stt,
                insertion=insertion,
                events=self._events,
                capture_destination=destination,
                new_capture=new_run_capture,
                new_wav=WavWriter,
                new_id=lambda: secrets.token_urlsafe(18),
                audio_dir=audio_dir,
                config_snapshot=lambda: (
                    self._settings.model_dump(mode="json") if self._settings else {}
                ),
                cleanup=self._cleanup(self._settings.cleanup_model_id)
                if self._settings and self._settings.cleanup_enabled
                else None,
                clock=self.factories.clock,
            )
        )

        async def copy_clipboard(text: str) -> None:
            await self._offload(
                lambda: win32.set_clipboard(text, exclusion_formats=True)
            )

        self._run_commands = RunCommands(
            self._controller,
            clock=self.factories.clock,
            copy_to_clipboard=copy_clipboard,
            last_external_destination=self.last_external_destination,
        )
        audio = AudioCommands(
            list_devices=self.factories.list_devices,
            new_test_capture=lambda device: self.factories.new_capture(
                lease, device, "mic_test"
            ),
            events=self._events,
        )
        self._audio_commands = audio
        model_service = self._model_service
        assert model_service is not None

        async def readiness() -> list[dict[str, object]]:
            return cast(list[dict[str, object]], await model_service.status())

        settings_commands = SettingsCommands(
            store,
            self._history,
            self._controller,
            session_token=lambda: self.api.session_token,
            readiness=readiness,
        )
        commands: dict[str, CommandSpec] = {}
        commands.update(self._run_commands.specs())
        commands.update(audio.specs())
        commands.update(ModelCommands(self._model_service).specs())
        commands.update(settings_commands.specs())
        commands.update(DictionaryCommands(dictionary).specs())
        commands.update(
            HistoryCommands(
                self._history,
                self._controller,
                self._run_commands,
                copy_to_clipboard=copy_clipboard,
            ).specs()
        )
        state_spec = commands["state_get"]

        async def state_with_starting_run(payload: Any) -> Any:
            result = await state_spec.handler(payload)
            if result.get("active_run_id") is None:
                runs = result.get("runs", [])
                if isinstance(runs, list):
                    active = next(
                        (
                            item.get("run_id")
                            for item in runs
                            if isinstance(item, dict)
                            and item.get("status") == RunStatus.RECORDING.value
                        ),
                        None,
                    )
                    if isinstance(active, str):
                        result = {**result, "active_run_id": active}
            return result

        commands["state_get"] = CommandSpec(
            state_with_starting_run,
            state_spec.mutating,
            state_spec.needs_session,
        )
        commands["run_start"] = self._track_command(commands["run_start"])
        commands["run_recover"] = self._track_command(commands["run_recover"])
        original_update = commands["settings_update"]

        async def update_and_rebuild(payload: Any) -> Any:
            result = await original_update.handler(payload)
            self._settings = store.current()
            self._rebuild_hotkey()
            return result

        commands["settings_update"] = CommandSpec(
            update_and_rebuild, original_update.mutating, original_update.needs_session
        )
        self._api = Api(
            commands,
            session_token=secrets.token_urlsafe(24),
            clock=self.factories.clock,
        )
        self.startup_log.append("services")
        try:
            await self._stt.start()
        except Exception:
            pass
        self.startup_log.append("stt")
        self._start_hotkey()
        self._start_timers()
        self.startup_log.append("timers_hotkeys")
        if self.factories.webview is not None and self._worker is None:
            self._create_windows()
        if self.factories.webview is None or self._worker is None:
            self.startup_log.append("windows")
        self._started = True

    async def _offload(self, operation: Callable[[], Any]) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.insertion_executor, operation)

    def _cleanup(self, model_id: str) -> CleanupEngine | None:
        if model_id not in self._cleanup_cache:
            adapter = self.factories.cleanup_for(model_id)
            if adapter is not None:
                self._cleanup_cache[model_id] = adapter
        return self._cleanup_cache.get(model_id)

    def _track_command(self, spec: CommandSpec) -> CommandSpec:
        async def tracked(payload: Any) -> Any:
            result = await spec.handler(payload)
            run_id = result.get("run_id")
            if isinstance(run_id, str):
                self._run_ids.add(run_id)
            return result

        return CommandSpec(tracked, spec.mutating, spec.needs_session)

    def _on_evicted(self, run_id: str) -> None:
        if self._controller is not None:
            self._controller.abort(run_id)
        if self._run_commands is not None:
            self._run_commands.invalidate(run_id)

    def _post_hotkey(self, callback: Callable[[], None]) -> None:
        loop = self._loop or asyncio.get_running_loop()
        loop.call_soon_threadsafe(callback)

    def _start_hotkey(self) -> None:
        if self._settings is None or self._api is None:
            return
        from wispr_clone.contracts.shortcuts import parse_binding

        async def invoke(name: str, extra: dict[str, object] | None = None) -> None:
            payload: dict[str, object] = {
                "session_token": self.api.session_token,
                "deadline": self.factories.clock() + 10,
            }
            if extra:
                payload.update(extra)
            result = await self.api.call(name, payload)
            if result.ok and result.data and isinstance(result.data.get("run_id"), str):
                self._run_ids.add(str(result.data["run_id"]))

        def schedule(name: str, extra: dict[str, object] | None = None) -> None:
            loop = self._loop or asyncio.get_running_loop()
            task = loop.create_task(invoke(name, extra))
            task.add_done_callback(
                lambda done: done.exception() if not done.cancelled() else None
            )

        service = HotkeyService(
            dictation=parse_binding(self._settings.dictation_shortcut),
            cancel=parse_binding(self._settings.cancel_shortcut),
            mode=self._settings.recording_mode,
            on_start=lambda: schedule(
                "run_start", {"request_id": secrets.token_urlsafe(18)}
            ),
            on_stop=lambda: (
                schedule("run_stop", {"run_id": self._controller.active_run_id})
                if self._controller and self._controller.active_run_id
                else None
            ),
            on_cancel=lambda: schedule("run_cancel"),
            post=self._post_hotkey,
        )
        self._hotkey = service
        self._listener = self.factories.hotkey_listener(service)
        self._listener.start()

    def _rebuild_hotkey(self) -> None:
        if self._listener is not None:
            self._listener.stop()
        self._start_hotkey()

    def _start_timers(self) -> None:
        self._timers = [
            asyncio.create_task(
                self._periodic("delivery", config.DELIVERY_TICK_S, self._delivery)
            ),
            asyncio.create_task(
                self._periodic("models", config.MODEL_POLL_S, self._poll_models)
            ),
            asyncio.create_task(
                self._periodic("tracker", config.TRACKER_S, self._track_destination)
            ),
            asyncio.create_task(self._retention_loop()),
        ]

    async def _periodic(
        self, name: str, interval: float, callback: Callable[[], Any]
    ) -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                result = callback()
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                self.timer_errors[name] = self.timer_errors.get(name, 0) + 1

    async def _delivery(self) -> None:
        if self._controller:
            await self._controller.delivery_tick()

    async def _poll_models(self) -> None:
        if self._model_service:
            await self._model_service.poll()

    async def _track_destination(self) -> None:
        if self._win32 is None or self._uia is None:
            return
        win32, uia = self._win32, self._uia
        hwnd = await self._offload(win32.foreground_window)
        if hwnd == self._last_hwnd:
            return
        self._last_hwnd = hwnd
        if not hwnd or not await self._offload(lambda: win32.is_window(hwnd)):
            return
        pid, _ = await self._offload(lambda: win32.window_process(hwnd))
        if pid == os.getpid():
            return
        try:
            self._destination = await self._offload(
                lambda: capture(win32, uia, exclude_pids=frozenset({os.getpid()}))
            )
        except Exception:
            return

    async def _retention_loop(self) -> None:
        while True:
            delay = 60.0
            if self._history:
                expiry = self._history.next_expiry_at()
                if expiry is not None:
                    delay = max(0.0, expiry - self.factories.clock())
            await asyncio.sleep(delay)
            try:
                if self._history:
                    await self._history.enforce_retention()
            except Exception:
                self.timer_errors["retention"] = (
                    self.timer_errors.get("retention", 0) + 1
                )

    def _schedule_shutdown(self) -> None:
        loop = self._loop
        if loop is not None:
            future = asyncio.run_coroutine_threadsafe(self.shutdown(), loop)
            future.add_done_callback(lambda _done: loop.call_soon_threadsafe(loop.stop))

    def _create_windows(self) -> None:
        if self.factories.webview is None or self._windows:
            return
        webview = self.factories.webview()
        hud_url = (Path(__file__).resolve().parents[2] / "web" / "hud.html").as_uri()
        self._hud = open_hud(webview, hud_url=hud_url)
        self._events.target = WebviewEventSink(
            None, self._hud, clock=self.factories.monotonic
        )
        assert self._api is not None and self._loop is not None
        settings_window = open_settings(
            webview, Bridge(self._api, self._loop), debug=self.debug
        )
        self._windows = [settings_window, self._hud]
        cast(Any, settings_window).events.closed += lambda: self._schedule_shutdown()
        self._events.target = WebviewEventSink(
            settings_window, self._hud, clock=self.factories.monotonic
        )
        self._events.hud = self._hud
        self.startup_log.append("windows")

    async def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
        self.shutdown_log.append("hotkeys")
        for timer in self._timers:
            timer.cancel()
        await asyncio.gather(*self._timers, return_exceptions=True)
        self.shutdown_log.append("timers")
        if self._controller is not None:
            try:
                await self._controller.cancel_current()
            except Exception:
                pass
        if self._audio_commands is not None:
            try:
                await self._audio_commands._stop({})
            except Exception:
                pass
        self.shutdown_log.append("runs_and_mic")

        async def settle() -> None:
            if self._controller is None:
                return
            for run_id in tuple(self._run_ids):
                try:
                    record = await self._history.get(run_id) if self._history else None
                    if record is not None and record.status not in {
                        RunStatus.DONE,
                        RunStatus.ERROR,
                        RunStatus.CANCELLED,
                        RunStatus.HELD,
                        RunStatus.UNCERTAIN,
                    }:
                        await self._controller.settled(run_id)
                except Exception:
                    pass

        try:
            await asyncio.wait_for(settle(), timeout=5.0)
        except TimeoutError:
            pass
        self.shutdown_log.append("live_tasks")
        engines = list(self._cleanup_cache.values())
        if self._controller is not None:
            # Controller uses one of the cached adapters when cleanup is enabled.
            pass
        for engine in engines:
            close = getattr(engine, "aclose", None)
            if callable(close):
                try:
                    result = close()
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    pass
        if self._stt is not None:
            try:
                await self._stt.close()
            except Exception:
                pass
        self.shutdown_log.append("models")
        self.insertion_executor.shutdown(wait=True, cancel_futures=True)
        self.shutdown_log.append("insertion_executor")
        if self._db is not None:
            await self._db.close()
        self.shutdown_log.append("database")
        self.shutdown_log.append("worker_loop")
        if self._instance is not None:
            self._instance.release()
            self._instance = None
        self.shutdown_log.append("single_instance")

    def run(self) -> int:
        if self._worker is None:
            self._worker = threading.Thread(
                target=self._worker_main, name="wispr-app", daemon=True
            )
            self._worker.start()
        self._worker_ready.wait()
        if self._worker_error is not None:
            return 1
        if self.factories.webview is not None:
            self._create_windows()
            self._gui_thread_id = threading.get_ident()
            try:
                start_webview(self.factories.webview(), debug=self.debug)
            finally:
                self._schedule_shutdown()
        else:
            self._worker_done.wait()
        self._worker_done.wait()
        return 0

    def _worker_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self.startup())
            self._worker_ready.set()
            if self.factories.webview is None:
                loop.run_until_complete(self.shutdown())
            else:
                loop.run_forever()
        except BaseException as error:
            self._worker_error = error
            self._worker_ready.set()
        finally:
            if not self._closed:
                loop.run_until_complete(self.shutdown())
            loop.close()
            self._worker_done.set()
