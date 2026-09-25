"""Thread-safe exclusive ownership of the input device."""

from dataclasses import dataclass
from threading import Lock
from typing import Literal

from wispr_clone.contracts.common import ErrorCode, WisprError

LeaseOwner = Literal["capture", "mic_test"]


@dataclass(frozen=True, slots=True)
class LeaseToken:
    """Identifies one successful device lease acquisition."""

    owner: LeaseOwner
    serial: int


class DeviceLease:
    """Allow one capture or microphone test at a time."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._token: LeaseToken | None = None
        self._serial = 0

    def acquire(self, owner: LeaseOwner) -> LeaseToken:
        with self._lock:
            if self._token is not None:
                raise WisprError(ErrorCode.DEVICE_LEASE_CONFLICT, "audio", "lease held")
            self._serial += 1
            token = LeaseToken(owner, self._serial)
            self._token = token
            return token

    def release(self, token: LeaseToken) -> None:
        with self._lock:
            if self._token == token:
                self._token = None

    @property
    def holder(self) -> LeaseOwner | None:
        with self._lock:
            return self._token.owner if self._token is not None else None
