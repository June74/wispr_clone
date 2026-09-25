"""Fixed, privacy-safe messages and recovery guidance for stable error codes."""

from wispr_clone.contracts.common import ErrorCode

_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.VALIDATION: "Some settings or command details are invalid.",
    ErrorCode.UNKNOWN_COMMAND: "That action is not available.",
    ErrorCode.STALE_VERSION: "This result changed before the action could be applied.",
    ErrorCode.EXPIRED_COMMAND: "This action expired. Try again from the app.",
    ErrorCode.PREVIOUS_SESSION_TOKEN: "The app restarted. Refresh and try again.",
    ErrorCode.RUN_NOT_FOUND: "This dictation is no longer available.",
    ErrorCode.RUN_EXPIRED: "This dictation has expired.",
    ErrorCode.RUN_DELETED: "This dictation was deleted.",
    ErrorCode.DUPLICATE_REQUEST: "This action was already received.",
    ErrorCode.DEVICE_LEASE_CONFLICT: "The microphone is busy with another task.",
    ErrorCode.MICROPHONE_UNAVAILABLE: "The selected microphone is unavailable.",
    ErrorCode.MICROPHONE_PERMISSION_DENIED: (
        "Enable microphone access for Wispr Clone in Windows privacy settings."
    ),
    ErrorCode.MICROPHONE_DISCONNECTED: "The microphone was disconnected.",
    ErrorCode.AUDIO_QUEUE_OVERFLOW: "Audio could not be processed quickly enough.",
    ErrorCode.NO_SPEECH_DETECTED: "No speech was detected in this recording.",
    ErrorCode.STT_UNAVAILABLE: "Speech recognition is unavailable.",
    ErrorCode.MODEL_LOAD_FAILED: "A selected model could not be loaded.",
    ErrorCode.STT_TIMEOUT: "Speech recognition took too long.",
    ErrorCode.STT_STREAM_CLOSED: "The speech recognition session ended unexpectedly.",
    ErrorCode.CLEANUP_UNAVAILABLE: "Text cleanup is unavailable.",
    ErrorCode.CLEANUP_TIMEOUT: "Text cleanup took too long.",
    ErrorCode.CLEANUP_REJECTED: "The cleanup result did not pass safety checks.",
    ErrorCode.CLOUD_MODEL_FORBIDDEN: "Cloud models are disabled in local-only mode.",
    ErrorCode.NON_LOOPBACK_ENDPOINT: "The model endpoint must use this computer only.",
    ErrorCode.DESTINATION_UNVERIFIABLE: "The original field could not be confirmed.",
    ErrorCode.DESTINATION_CLOSED: "The original destination is no longer open.",
    ErrorCode.DESTINATION_WAIT_LIMIT_EXCEEDED: "The destination wait limit expired.",
    ErrorCode.INSERTION_FAILED: "Text could not be inserted.",
    ErrorCode.INSERTION_UNCERTAIN: "Text delivery could not be confirmed.",
    ErrorCode.STORAGE_ERROR: "Local data could not be saved or read.",
    ErrorCode.DELETION_FAILED: "Some local dictation data could not be deleted yet.",
}

_ACTIONS: dict[ErrorCode, tuple[str, ...]] = {
    ErrorCode.VALIDATION: ("review_settings",),
    ErrorCode.UNKNOWN_COMMAND: ("dismiss",),
    ErrorCode.STALE_VERSION: ("refresh_state",),
    ErrorCode.EXPIRED_COMMAND: ("retry",),
    ErrorCode.PREVIOUS_SESSION_TOKEN: ("refresh_state",),
    ErrorCode.RUN_NOT_FOUND: ("dismiss",),
    ErrorCode.RUN_EXPIRED: ("dismiss",),
    ErrorCode.RUN_DELETED: ("dismiss",),
    ErrorCode.DUPLICATE_REQUEST: ("refresh_state",),
    ErrorCode.DEVICE_LEASE_CONFLICT: ("wait",),
    ErrorCode.MICROPHONE_UNAVAILABLE: ("choose_mic", "open_settings"),
    ErrorCode.MICROPHONE_PERMISSION_DENIED: ("open_settings", "choose_mic"),
    ErrorCode.MICROPHONE_DISCONNECTED: ("choose_mic", "retry"),
    ErrorCode.AUDIO_QUEUE_OVERFLOW: ("retry", "dismiss"),
    ErrorCode.NO_SPEECH_DETECTED: ("retry_stt", "dismiss"),
    ErrorCode.STT_UNAVAILABLE: ("open_settings", "retry_stt"),
    ErrorCode.MODEL_LOAD_FAILED: ("open_settings", "retry"),
    ErrorCode.STT_TIMEOUT: ("retry_stt", "use_original", "copy"),
    ErrorCode.STT_STREAM_CLOSED: ("retry_stt", "use_original", "copy"),
    ErrorCode.CLEANUP_UNAVAILABLE: ("retry_cleanup", "use_original", "copy"),
    ErrorCode.CLEANUP_TIMEOUT: ("retry_cleanup", "use_original", "copy"),
    ErrorCode.CLEANUP_REJECTED: ("retry_cleanup", "use_original", "copy"),
    ErrorCode.CLOUD_MODEL_FORBIDDEN: ("open_settings",),
    ErrorCode.NON_LOOPBACK_ENDPOINT: ("open_settings",),
    ErrorCode.DESTINATION_UNVERIFIABLE: ("copy", "insert"),
    ErrorCode.DESTINATION_CLOSED: ("copy", "insert"),
    ErrorCode.DESTINATION_WAIT_LIMIT_EXCEEDED: ("copy", "insert"),
    ErrorCode.INSERTION_FAILED: ("copy", "retry_insert"),
    ErrorCode.INSERTION_UNCERTAIN: ("copy", "review_before_retry"),
    ErrorCode.STORAGE_ERROR: ("retry", "open_settings"),
    ErrorCode.DELETION_FAILED: ("retry_delete", "dismiss"),
}


def get_error_message(code: ErrorCode) -> str:
    """Return fixed user-facing text; never interpolate private content."""
    return _MESSAGES[code]


def get_recovery_actions(code: ErrorCode) -> tuple[str, ...]:
    """Return the actions appropriate to a stable error code."""
    return _ACTIONS[code]
