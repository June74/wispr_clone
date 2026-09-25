"""Shared result and error contracts."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar


class ErrorCode(StrEnum):
    """Stable identifiers for user-visible failures."""

    VALIDATION = "validation"
    UNKNOWN_COMMAND = "unknown_command"
    STALE_VERSION = "stale_version"
    EXPIRED_COMMAND = "expired_command"
    PREVIOUS_SESSION_TOKEN = "previous_session_token"
    RUN_NOT_FOUND = "run_not_found"
    RUN_EXPIRED = "run_expired"
    RUN_DELETED = "run_deleted"
    DUPLICATE_REQUEST = "duplicate_request"
    DEVICE_LEASE_CONFLICT = "device_lease_conflict"
    MICROPHONE_UNAVAILABLE = "microphone_unavailable"
    MICROPHONE_DISCONNECTED = "microphone_disconnected"
    AUDIO_QUEUE_OVERFLOW = "audio_queue_overflow"
    NO_SPEECH_DETECTED = "no_speech_detected"
    STT_UNAVAILABLE = "stt_unavailable"
    MODEL_LOAD_FAILED = "model_load_failed"
    STT_TIMEOUT = "stt_timeout"
    STT_STREAM_CLOSED = "stt_stream_closed"
    CLEANUP_UNAVAILABLE = "cleanup_unavailable"
    CLEANUP_TIMEOUT = "cleanup_timeout"
    CLEANUP_REJECTED = "cleanup_rejected"
    CLOUD_MODEL_FORBIDDEN = "cloud_model_forbidden"
    NON_LOOPBACK_ENDPOINT = "non_loopback_endpoint"
    DESTINATION_UNVERIFIABLE = "destination_unverifiable"
    DESTINATION_CLOSED = "destination_closed"
    DESTINATION_WAIT_LIMIT_EXCEEDED = "destination_wait_limit_exceeded"
    INSERTION_FAILED = "insertion_failed"
    INSERTION_UNCERTAIN = "insertion_uncertain"
    STORAGE_ERROR = "storage_error"
    DELETION_FAILED = "deletion_failed"


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Result(Generic[T]):
    """A result with exactly one populated branch."""

    ok: bool
    data: T | None
    error: ErrorCode | None

    def __post_init__(self) -> None:
        if type(self.ok) is not bool:
            raise TypeError("ok must be a bool")
        if self.ok:
            if self.data is None or self.error is not None:
                raise ValueError("successful results require data and no error")
        elif self.data is not None or not isinstance(self.error, ErrorCode):
            raise ValueError("failed results require an ErrorCode and no data")


class ThirdPartyError(Exception):
    """A dependency failure normalized at an adapter boundary."""

    def __init__(
        self, dependency: str, operation: str, detail: str, error_code: ErrorCode
    ) -> None:
        self.dependency = dependency
        self.operation = operation
        self.detail = detail
        self.error_code = error_code
        super().__init__(f"{dependency} {operation} failed: {detail}")


class WisprError(Exception):
    """An application invariant or validation failure."""

    def __init__(self, error_code: ErrorCode, where: str, why: str) -> None:
        self.error_code = error_code
        self.where = where
        self.why = why
        super().__init__(f"{error_code.value} at {where}: {why}")
