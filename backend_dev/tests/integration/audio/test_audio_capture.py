"""T-AUD capture behavior through a threaded, microphone-free sounddevice fake."""

import asyncio
import importlib
import sys
import threading

import numpy as np
import pytest

from wispr_clone.contracts.common import ErrorCode, ThirdPartyError, WisprError

from .fake_sounddevice_audio import FakeStatus, make_fake_sounddevice


def audio_modules():
    return (
        importlib.import_module("wispr_clone.audio.capture"),
        importlib.import_module("wispr_clone.audio.device_lease"),
    )


async def drain(capture):
    return await asyncio.wait_for(_collect(capture), 8)


async def _collect(capture):
    result = []
    async for chunk in capture.chunks():
        result.append(chunk)
    return result


@pytest.mark.integration
@pytest.mark.invariant
def test_T_AUD_001_lease_is_exclusive_in_both_directions_and_stale_safe():
    capture_mod, lease_mod = audio_modules()
    lease = lease_mod.DeviceLease()
    fake = make_fake_sounddevice()
    capture = capture_mod.AudioCapture(lease, module=fake)
    capture.start()
    assert lease.holder == "capture"
    with pytest.raises(WisprError) as caught:
        lease.acquire("mic_test")
    assert caught.value.error_code == ErrorCode.DEVICE_LEASE_CONFLICT
    contender = capture_mod.AudioCapture(lease, module=fake, owner="mic_test")
    with pytest.raises(WisprError) as caught:
        contender.start()
    assert caught.value.error_code == ErrorCode.DEVICE_LEASE_CONFLICT
    assert len(fake.streams) == 1
    capture.stop()
    token = lease.acquire("mic_test")
    lease.release(token)
    replacement = lease.acquire("capture")
    lease.release(token)
    assert lease.holder == "capture"
    lease.release(replacement)

    first = lease.acquire("mic_test")
    with pytest.raises(WisprError) as caught:
        capture_mod.AudioCapture(lease, module=fake).start()
    assert caught.value.error_code == ErrorCode.DEVICE_LEASE_CONFLICT
    assert len(fake.streams) == 1
    lease.release(first)


@pytest.mark.unit
@pytest.mark.invariant
def test_T_AUD_001_concurrent_lease_acquire_has_exactly_one_winner():
    _, lease_mod = audio_modules()
    lease = lease_mod.DeviceLease()
    gate = threading.Event()
    ready = threading.Barrier(3)
    winners = []
    losers = []

    def attempt(owner):
        ready.wait(timeout=5)
        assert gate.wait(5)
        try:
            winners.append(lease.acquire(owner))
        except WisprError as exc:
            losers.append(exc.error_code)

    threads = [
        threading.Thread(target=attempt, args=(owner,))
        for owner in ("capture", "mic_test")
    ]
    for thread in threads:
        thread.start()
    ready.wait(timeout=5)
    gate.set()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert len(winners) == 1
    assert losers == [ErrorCode.DEVICE_LEASE_CONFLICT]
    lease.release(winners[0])


@pytest.mark.integration
@pytest.mark.parametrize("exit_kind", ["stop", "cancel", "open", "start"])
def test_T_AUD_002_lease_released_after_exit_or_open_failure(exit_kind):
    capture_mod, lease_mod = audio_modules()
    lease = lease_mod.DeviceLease()
    fake = make_fake_sounddevice()
    if exit_kind == "open":
        fake.open_error = RuntimeError("private device name")
    if exit_kind == "start":
        fake.start_error = RuntimeError("private device name")
    capture = capture_mod.AudioCapture(lease, module=fake)
    if exit_kind in ("open", "start"):
        with pytest.raises(ThirdPartyError) as caught:
            capture.start()
        assert (
            caught.value.dependency,
            caught.value.operation,
            caught.value.error_code,
        ) == ("sounddevice", "open", ErrorCode.MICROPHONE_UNAVAILABLE)
        assert "private device name" not in str(caught.value)
    else:
        capture.start()
        getattr(capture, exit_kind)()
        getattr(capture, exit_kind)()
        assert fake.streams[0].closed and fake.streams[0].stopped
    assert lease.holder is None


@pytest.mark.integration
@pytest.mark.invariant
@pytest.mark.asyncio
async def test_T_AUD_006_overflow_yields_accepted_prefix_then_errors():
    capture_mod, lease_mod = audio_modules()
    lease = lease_mod.DeviceLease()
    fake = make_fake_sounddevice()
    fake.devices[1]["default_samplerate"] = 16_000
    capture = capture_mod.AudioCapture(lease, module=fake, queue_max_blocks=2)
    capture.start()
    for value in (0.1, 0.2, 0.3):
        fake.streams[0].fire(np.full(1280, value, dtype=np.float32))
    yielded = []

    async def consume():
        async for chunk in capture.chunks():
            yielded.append(chunk)

    with pytest.raises(WisprError) as caught:
        await asyncio.wait_for(consume(), 8)
    assert caught.value.error_code == ErrorCode.AUDIO_QUEUE_OVERFLOW
    assert sum(len(chunk.samples) for chunk in yielded) == 2560
    assert np.mean(yielded[0].samples) == pytest.approx(0.1, abs=0.01)
    assert np.mean(yielded[1].samples) == pytest.approx(0.2, abs=0.01)
    assert lease.holder is None
    assert fake.streams[0].closed


@pytest.mark.integration
@pytest.mark.invariant
@pytest.mark.asyncio
async def test_T_AUD_006_portaudio_input_overflow_is_explicit():
    capture_mod, lease_mod = audio_modules()
    lease = lease_mod.DeviceLease()
    fake = make_fake_sounddevice()
    capture = capture_mod.AudioCapture(lease, module=fake)
    capture.start()
    fake.streams[0].fire(np.full(3840, 0.1, dtype=np.float32))
    fake.streams[0].fire(
        np.full(3840, 0.2, dtype=np.float32), FakeStatus(input_overflow=True)
    )
    yielded = []

    async def consume():
        async for chunk in capture.chunks():
            yielded.append(chunk)

    with pytest.raises(WisprError) as caught:
        await asyncio.wait_for(consume(), 8)
    assert caught.value.error_code == ErrorCode.AUDIO_QUEUE_OVERFLOW
    assert sum(len(chunk.samples) for chunk in yielded) == 1280
    assert np.mean(yielded[0].samples) == pytest.approx(0.1, abs=0.01)
    assert lease.holder is None


@pytest.mark.integration
@pytest.mark.invariant
@pytest.mark.asyncio
async def test_T_AUD_007_callback_only_copies_and_enqueues(monkeypatch, caplog):
    capture_mod, lease_mod = audio_modules()
    fake = make_fake_sounddevice()
    capture = capture_mod.AudioCapture(lease_mod.DeviceLease(), module=fake)
    capture.start()
    called = []

    def forbidden(*args, **kwargs):
        called.append(threading.get_ident())
        raise AssertionError("processing or file I/O ran inside callback")

    with monkeypatch.context() as patch:
        patch.setattr(capture_mod, "to_mono_16k", forbidden, raising=False)
        patch.setattr(capture_mod, "band_levels", forbidden, raising=False)
        writer_mod = importlib.import_module("wispr_clone.audio.wav_writer")
        patch.setattr(writer_mod, "WavWriter", forbidden)
        source = np.full(1280, 0.25, dtype=np.float32)
        fake.streams[0].fire(source)
        source[:] = 0.75
    assert not called
    assert fake.streams[0].audio_thread_ident != threading.get_ident()
    assert not caplog.records
    capture.stop()
    chunks = await drain(capture)
    assert len(chunks) == 1
    assert np.mean(chunks[0].samples) == pytest.approx(0.25, abs=0.01)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_T_AUD_008_chunks_order_bands_stop_drain_and_cancel():
    capture_mod, lease_mod = audio_modules()
    lease = lease_mod.DeviceLease()
    fake = make_fake_sounddevice()
    capture = capture_mod.AudioCapture(lease, module=fake, block_ms=80)
    capture.start()
    stream = fake.streams[0]
    assert (
        stream.kwargs["channels"],
        stream.kwargs["dtype"],
        stream.kwargs["samplerate"],
    ) == (1, "float32", 48_000)
    assert stream.kwargs["blocksize"] == 3840
    # Two 48 kHz blocks become three 1280-sample chunks at 16 kHz.
    for value in (0.1, 0.2):
        stream.fire(np.full(5760, value, dtype=np.float32))
    capture.stop()
    chunks = await drain(capture)
    assert [len(chunk.samples) for chunk in chunks] == [1280, 1280, 1280]
    assert np.mean(chunks[0].samples) == pytest.approx(0.1, abs=0.02)
    assert np.mean(chunks[-1].samples) == pytest.approx(0.2, abs=0.02)
    assert all(len(chunk.bands) == 12 for chunk in chunks)
    assert lease.holder is None

    cancelled = capture_mod.AudioCapture(lease, module=fake)
    cancelled.start()
    fake.streams[-1].fire(np.ones(3840, dtype=np.float32))
    cancelled.cancel()
    assert await drain(cancelled) == []
    assert lease.holder is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_T_AUD_002_008_device_error_releases_lease_and_reports_disconnect():
    capture_mod, lease_mod = audio_modules()
    lease = lease_mod.DeviceLease()
    fake = make_fake_sounddevice()
    capture = capture_mod.AudioCapture(lease, module=fake)
    capture.start()
    fake.streams[0].fire(np.ones(3840, dtype=np.float32), FakeStatus("device lost"))
    with pytest.raises(ThirdPartyError) as caught:
        await drain(capture)
    assert (
        caught.value.dependency,
        caught.value.operation,
        caught.value.error_code,
    ) == ("sounddevice", "stream", ErrorCode.MICROPHONE_DISCONNECTED)
    assert lease.holder is None


@pytest.mark.integration
def test_T_AUD_008_device_list_filters_inputs_and_import_failure(monkeypatch):
    devices = importlib.import_module("wispr_clone.audio.devices")
    fake = make_fake_sounddevice()
    result = devices.list_input_devices(module=fake)
    assert len(result) == 1
    assert (result[0].device_id, result[0].name, result[0].channels) == (
        1,
        "synthetic mic",
        1,
    )
    assert result[0].default_samplerate == 48_000
    assert result[0].is_default

    monkeypatch.setitem(sys.modules, "sounddevice", None)
    with pytest.raises(ThirdPartyError) as caught:
        devices.list_input_devices()
    assert (
        caught.value.dependency,
        caught.value.operation,
        caught.value.detail,
        caught.value.error_code,
    ) == (
        "sounddevice",
        "query",
        "ModuleNotFoundError",
        ErrorCode.MICROPHONE_UNAVAILABLE,
    )
