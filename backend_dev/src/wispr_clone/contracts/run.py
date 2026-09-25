"""Run lifecycle and recovery values."""

from enum import StrEnum


class RunStatus(StrEnum):
    RECORDING = "recording"
    PROCESSING = "processing"
    AWAITING_CLEANUP_CHOICE = "awaiting_cleanup_choice"
    AWAITING_DESTINATION = "awaiting_destination"
    HELD = "held"
    DONE = "done"
    ERROR = "error"
    UNCERTAIN = "uncertain"
    CANCELLED = "cancelled"


class AttemptOutcome(StrEnum):
    IN_FLIGHT = "in_flight"
    INSERTED = "inserted"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    CANCELLED = "cancelled"


class InsertionOutcome(StrEnum):
    NONE = "none"
    IN_FLIGHT = "in_flight"
    INSERTED = "inserted"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    CANCELLED = "cancelled"


class CleanupStatus(StrEnum):
    OFF = "off"
    PENDING = "pending"
    OK = "ok"
    FAILED = "failed"
    REJECTED = "rejected"


class RecoveryAction(StrEnum):
    RETRY_STT = "retry_stt"
    RETRY_CLEANUP = "retry_cleanup"
    USE_ORIGINAL = "use_original"
    COPY = "copy"
    INSERT = "insert"
