"""WO-feat-stt acceptance tests against an injectable native API."""

import array
import asyncio
import importlib
import struct
import sys
import threading
import wave
from pathlib import Path

import pytest

from wispr_clone.contracts.common import ErrorCode, ThirdPartyError, WisprError

from .fake_transcribe_cpp import ModelLoadError, StreamText, make_fake


def engine(module=None):
    from wispr_clone.stt.voxtral_transcribe_cpp import VoxtralTranscribeCpp

    return VoxtralTranscribeCpp(Path("synthetic.gguf"), module=module)


def names(module):
    return [name for name, _thread in module.control.calls]


def assert_error(exc, dependency, operation, detail, code):
    assert (exc.dependency, exc.operation, exc.detail, exc.error_code) == (
        dependency,
        operation,
        detail,
        code,
    )


@pytest.mark.asyncio
async def test_T_STT_001_start_loads_named_device_and_warms_once(monkeypatch):
    fake = make_fake()
    stt = engine(fake)
    with pytest.raises(WisprError) as caught:
        stt.start_session()
    assert (caught.value.error_code, caught.value.where, caught.value.why) == (
        ErrorCode.STT_UNAVAILABLE,
        "stt",
        "not ready",
    )
    assert not stt.ready
    await stt.start()
    assert stt.ready
    assert fake.control.devices == [
        next(d for d in fake.backends() if d.name == "CUDA0")
    ]
    assert names(fake).count("run") == 1
    assert len(fake.control.run_pcm) == 1
    assert fake.control.run_pcm[0] == [0.0] * 16_000
    assert names(fake).count("Model") == 1
    await stt.start()
    assert names(fake).count("Model") == 1
    await stt.close()

    # Construct separately because the public device selection is constructor-only.
    from wispr_clone.stt.voxtral_transcribe_cpp import VoxtralTranscribeCpp

    missing = VoxtralTranscribeCpp(
        Path("synthetic.gguf"), device_name="MISSING", module=make_fake()
    )
    with pytest.raises(ThirdPartyError) as caught:
        await missing.start()
    assert_error(
        caught.value,
        "transcribe-cpp",
        "load",
        "device not found",
        ErrorCode.MODEL_LOAD_FAILED,
    )
    await missing.close()

    bad = make_fake()
    bad.control.load_error = ModelLoadError("PRIVATE MODEL PATH")
    with pytest.raises(ThirdPartyError) as caught:
        await engine(bad).start()
    assert_error(
        caught.value,
        "transcribe-cpp",
        "load",
        "ModelLoadError",
        ErrorCode.MODEL_LOAD_FAILED,
    )
    assert "PRIVATE MODEL PATH" not in str(caught.value)

    def unavailable(_name):
        raise ImportError("private module path")

    monkeypatch.setattr(importlib, "import_module", unavailable)
    with pytest.raises(ThirdPartyError) as caught:
        await engine().start()
    assert_error(
        caught.value,
        "transcribe-cpp",
        "import",
        "ImportError",
        ErrorCode.STT_UNAVAILABLE,
    )


@pytest.mark.asyncio
async def test_T_STT_002_feeds_ordered_on_one_native_thread_without_blocking_loop():
    fake = make_fake()
    fake.control.block_feed = True
    stt = engine(fake)
    await stt.start()
    session = stt.start_session()
    first = array.array("f", [0.125] * 1280)
    second = array.array("f", [-0.25] * 1280)
    session.push_audio(first)
    assert await asyncio.to_thread(fake.control.feed_entered.wait, 5)
    session.push_audio(second)  # first native feed remains blocked
    assert not fake.control.feed_release.is_set()
    fake.control.feed_release.set()
    await session.finish()
    assert fake.control.chunks == [list(first), list(second)]
    native = {
        tid
        for name, tid in fake.control.calls
        if name
        in {
            "Model",
            "session",
            "run",
            "stream",
            "feed",
            "text",
            "finalize",
            "model.close",
        }
    }
    assert len(native) == 1
    assert threading.get_ident() not in native
    await stt.close()


@pytest.mark.asyncio
async def test_T_STT_003_returns_only_committed_and_emits_tentative_on_loop():
    fake = make_fake()
    fake.control.updates = [
        StreamText("full draft", "committed draft", "tentative draft")
    ]
    fake.control.final = StreamText("full final", "committed final", "tentative final")
    stt = engine(fake)
    await stt.start()
    updates = []
    delivered = asyncio.Event()

    def on_text(committed, tentative):
        updates.append((committed, tentative))
        delivered.set()

    session = stt.start_session(on_text)
    with pytest.raises(TypeError):
        session.push_audio(array.array("h", [1]))
    with pytest.raises(TypeError):
        session.push_audio([0.5])
    session.push_audio(array.array("f", [0.5]))
    await asyncio.wait_for(delivered.wait(), 5)
    result = await session.finish()
    assert result == "committed final"
    assert ("committed draft", "tentative draft") in updates
    assert "finalize" in names(fake)
    with pytest.raises(WisprError) as caught:
        session.push_audio(array.array("f", [0.5]))
    assert caught.value.error_code == ErrorCode.STT_STREAM_CLOSED
    await stt.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["feed", "finalize"])
async def test_T_STT_004_native_errors_are_sanitized_and_release_slot(operation):
    fake = make_fake()
    setattr(fake.control, f"{operation}_error", ModelLoadError("PRIVATE SENTINEL"))
    stt = engine(fake)
    await stt.start()
    session = stt.start_session()
    if operation == "feed":
        session.push_audio(array.array("f", [0.1]))
    with pytest.raises(ThirdPartyError) as caught:
        await session.finish()
    assert_error(
        caught.value,
        "transcribe-cpp",
        operation,
        "ModelLoadError",
        ErrorCode.STT_UNAVAILABLE,
    )
    assert "PRIVATE SENTINEL" not in str(caught.value)
    setattr(fake.control, f"{operation}_error", None)
    await stt.start_session().finish()
    await stt.close()


@pytest.mark.asyncio
async def test_T_STT_005_cancel_unblocks_feed_and_suppresses_queued_updates():
    fake = make_fake()
    fake.control.block_feed = True
    stt = engine(fake)
    await stt.start()
    updates = []
    session = stt.start_session(lambda *parts: updates.append(parts))
    session.push_audio(array.array("f", [0.1]))
    assert await asyncio.to_thread(fake.control.feed_entered.wait, 5)
    session.push_audio(array.array("f", [0.2]))
    session.cancel()
    session.cancel()
    assert fake.control.sessions[-1].was_aborted
    assert "cancel" in names(fake)
    with pytest.raises(WisprError) as caught:
        await session.finish()
    assert caught.value.error_code == ErrorCode.STT_STREAM_CLOSED
    await asyncio.sleep(0)  # drain one event-loop turn, without a time delay
    assert updates == []
    await stt.close()


def wav(path, samples, *, rate=16000, channels=1, width=2):
    with wave.open(str(path), "wb") as writer:
        writer.setparams((channels, width, rate, 0, "NONE", "not compressed"))
        writer.writeframes(b"".join(struct.pack("<h", sample) for sample in samples))


@pytest.mark.asyncio
async def test_T_STT_006_wav_replay_matches_live_and_rejects_formats(tmp_path):
    samples = [((n * 173) % 60000) - 30000 for n in range(2601)]
    path = tmp_path / "synthetic.wav"
    wav(path, samples)
    fake = make_fake()
    stt = engine(fake)
    await stt.start()
    live = stt.start_session()
    floats = [sample / 32768.0 for sample in samples]
    for offset in range(0, len(floats), 1280):
        live.push_audio(array.array("f", floats[offset : offset + 1280]))
    live_result = await live.finish()
    live_chunks = list(fake.control.chunks)
    fake.control.chunks.clear()
    replay_result = await stt.transcribe_file(path)
    assert replay_result == live_result
    assert fake.control.chunks == live_chunks
    assert list(map(len, live_chunks)) == [1280, 1280, 41]
    for rate, channels, width in [(8000, 1, 2), (16000, 2, 2), (16000, 1, 1)]:
        invalid = tmp_path / f"invalid-{rate}-{channels}-{width}.wav"
        if width == 1:
            with wave.open(str(invalid), "wb") as writer:
                writer.setparams((channels, width, rate, 0, "NONE", "not compressed"))
                writer.writeframes(bytes([128] * 16))
        else:
            wav(invalid, samples[:16], rate=rate, channels=channels, width=width)
        with pytest.raises(WisprError) as caught:
            await stt.transcribe_file(invalid)
        assert (caught.value.error_code, caught.value.where, caught.value.why) == (
            ErrorCode.VALIDATION,
            "stt",
            "wav format",
        )
    await stt.close()


@pytest.mark.asyncio
async def test_T_STT_007_only_one_active_session_even_for_file_replay(tmp_path):
    fake = make_fake()
    stt = engine(fake)
    await stt.start()
    active = stt.start_session()
    with pytest.raises(WisprError) as caught:
        stt.start_session()
    assert (caught.value.error_code, caught.value.where, caught.value.why) == (
        ErrorCode.STT_UNAVAILABLE,
        "stt",
        "session active",
    )
    path = tmp_path / "synthetic.wav"
    wav(path, [1, 2, 3])
    with pytest.raises(WisprError) as caught:
        await stt.transcribe_file(path)
    assert caught.value.error_code == ErrorCode.STT_UNAVAILABLE
    await active.finish()
    cancelled = stt.start_session()
    cancelled.cancel()
    await stt.start_session().finish()
    await stt.close()


@pytest.mark.asyncio
async def test_T_STT_008_lazy_import_and_idempotent_close(monkeypatch):
    real_import = importlib.import_module

    def refuse(name, *args, **kwargs):
        if name == "transcribe_cpp":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", refuse)
    sys.modules.pop("wispr_clone.stt.voxtral_transcribe_cpp", None)
    real_import("wispr_clone.stt.voxtral_transcribe_cpp")
    fake = make_fake()
    stt = engine(fake)
    await stt.start()
    stt.start_session()
    await stt.close()
    assert fake.control.sessions[-1].was_aborted
    await stt.close()
    assert names(fake).count("model.close") == 1


def test_T_STT_009_fake_native_classes_expose_only_real_public_attributes():
    fake = make_fake()
    real_public = {
        "Model": {
            "accepts",
            "arch",
            "backend",
            "capabilities",
            "close",
            "device",
            "session",
            "supports",
            "tokenize",
            "variant",
        },
        "Session": {
            "cancel",
            "close",
            "limits",
            "run",
            "run_batch",
            "stream",
            "was_aborted",
        },
        "Stream": {
            "feed",
            "finalize",
            "last_status",
            "reset",
            "revision",
            "snapshot",
            "state",
            "text",
        },
    }
    for name, allowed in real_public.items():
        cls = getattr(fake, name)
        instance = (
            cls(Path("synthetic.gguf"))
            if name == "Model"
            else cls()
            if name == "Session"
            else cls(fake.Session())
        )
        exposed = {attr for attr in dir(instance) if not attr.startswith("_")}
        assert exposed <= allowed, f"{name}: {sorted(exposed - allowed)}"


@pytest.mark.asyncio
async def test_T_STT_003_finish_exits_native_contexts_on_stt_thread():
    fake = make_fake()
    stt = engine(fake)
    await stt.start()
    session = stt.start_session()
    session.push_audio(array.array("f", [0.25]))
    try:
        assert await session.finish() == "committed"
        calls = fake.control.calls
        assert sum(name == "stream.__exit__" for name, _ in calls) == 1
        assert sum(name == "session.__exit__" for name, _ in calls) == 2
        assert sum(name == "session.close" for name, _ in calls) == 2
        native_threads = {
            tid
            for name, tid in calls
            if name
            in {"stream.__exit__", "session.__exit__", "session.close", "finalize"}
        }
        assert len(native_threads) == 1
        assert threading.get_ident() not in native_threads
    finally:
        await stt.close()


@pytest.mark.asyncio
async def test_T_STT_005_cancel_before_native_open_does_not_wait():
    fake = make_fake()
    stt = engine(fake)
    await stt.start()
    fake.control.session_entered.clear()
    fake.control.block_session = True
    session = stt.start_session()
    assert await asyncio.to_thread(fake.control.session_entered.wait, 5)
    returned = threading.Event()

    def cancel():
        session.cancel()
        returned.set()

    task = asyncio.create_task(asyncio.to_thread(cancel))
    try:
        immediate = await asyncio.to_thread(returned.wait, 0.5)
    finally:
        fake.control.session_release.set()
        await asyncio.wait_for(task, 5)
        await stt.close()
    assert immediate, "cancel waited for the blocked native session open"


@pytest.mark.asyncio
async def test_T_STT_004_feed_error_exits_native_contexts():
    fake = make_fake()
    fake.control.feed_error = RuntimeError("PRIVATE AUDIO")
    stt = engine(fake)
    await stt.start()
    session = stt.start_session()
    session.push_audio(array.array("f", [0.25]))
    try:
        with pytest.raises(ThirdPartyError) as caught:
            await session.finish()
        assert caught.value.operation == "feed"
        assert names(fake).count("stream.__exit__") == 1
        assert names(fake).count("session.__exit__") == 2
        assert names(fake).count("session.close") == 2
    finally:
        await stt.close()
