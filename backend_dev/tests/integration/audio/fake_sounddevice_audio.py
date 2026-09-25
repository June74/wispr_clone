"""Controllable sounddevice-shaped module; callback always runs on its own thread."""

import threading
from types import ModuleType, SimpleNamespace

import numpy as np


class FakeStatus:
    def __init__(self, detail="", *, input_overflow=False, input_underflow=False):
        self.detail = detail
        self.input_overflow = input_overflow
        self.input_underflow = input_underflow

    def __bool__(self):
        return bool(self.detail or self.input_overflow or self.input_underflow)

    def __str__(self):
        return self.detail or (
            "input overflow"
            if self.input_overflow
            else "input underflow"
            if self.input_underflow
            else ""
        )


class FakeInputStream:
    def __init__(self, module, **kwargs):
        if module.open_error is not None:
            raise module.open_error
        self.module = module
        self.kwargs = kwargs
        self.started = False
        self.stopped = False
        self.closed = False
        self.audio_thread_ident = None
        self.finished = False
        module.streams.append(self)

    def start(self):
        if self.module.start_error is not None:
            raise self.module.start_error
        self.started = True
        return self

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True

    def finish_on_its_own(self):
        """Simulate PortAudio ending a stream without an application stop."""
        self.finished = True
        callback = self.kwargs.get("finished_callback")
        if callback is not None:
            callback()

    def fire(self, data, status=None):
        """Deliver one copied test buffer synchronously via a bounded audio thread."""
        finished = threading.Event()
        errors = []
        frames = np.asarray(data, dtype=np.float32).reshape(-1, 1)

        def invoke():
            self.audio_thread_ident = threading.get_ident()
            try:
                self.kwargs["callback"](
                    frames, len(frames), None, status or FakeStatus()
                )
            except BaseException as exc:
                errors.append(exc)
            finally:
                finished.set()

        worker = threading.Thread(
            target=invoke, name="fake-audio-callback", daemon=True
        )
        worker.start()
        assert finished.wait(5), "audio callback exceeded the fake's 5 s bound"
        worker.join(timeout=1)
        if errors:
            raise errors[0]
        return frames


def make_fake_sounddevice():
    module = ModuleType("fake_sounddevice_audio")
    module.streams = []
    module.open_error = None
    module.start_error = None
    module.query_error = None
    module.default = SimpleNamespace(device=(1, 0))
    module.devices = [
        {
            "name": "synthetic output",
            "max_input_channels": 0,
            "default_samplerate": 48_000,
        },
        {
            "name": "synthetic mic",
            "max_input_channels": 1,
            "default_samplerate": 48_000,
        },
    ]

    def input_stream(**kwargs):
        return FakeInputStream(module, **kwargs)

    def query_devices(device=None, kind=None):
        if module.query_error is not None:
            raise module.query_error
        if device is not None:
            return module.devices[1]
        return module.devices

    module.InputStream = input_stream
    module.query_devices = query_devices
    return module
