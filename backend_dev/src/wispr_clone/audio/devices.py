"""Input device discovery with lazy sounddevice loading."""

from dataclasses import dataclass
from types import ModuleType

from wispr_clone.contracts.common import ErrorCode, ThirdPartyError


@dataclass(frozen=True, slots=True)
class InputDevice:
    """A sounddevice input device that can be selected by the UI."""

    device_id: int
    name: str
    channels: int
    default_samplerate: float
    is_default: bool


def list_input_devices(module: ModuleType | None = None) -> tuple[InputDevice, ...]:
    """Return available inputs, normalizing import and PortAudio failures."""
    try:
        if module is None:
            import sounddevice as sd  # type: ignore[import-untyped]
        else:
            sd = module
        devices = sd.query_devices()
        default_device = sd.default.device[0]
        result = []
        for device_id, device in enumerate(devices):
            channels = int(device["max_input_channels"])
            if channels > 0:
                result.append(
                    InputDevice(
                        device_id=device_id,
                        name=str(device["name"]),
                        channels=channels,
                        default_samplerate=float(device["default_samplerate"]),
                        is_default=device_id == default_device,
                    )
                )
        return tuple(result)
    except Exception as exc:
        raise ThirdPartyError(
            "sounddevice",
            "query",
            type(exc).__name__,
            ErrorCode.MICROPHONE_UNAVAILABLE,
        ) from exc
