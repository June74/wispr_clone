"""Fixed, privacy-safe user-facing messages for stable error codes."""

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
    ErrorCode.API_KEY_MISSING: (
        "Add your OpenRouter API key in Models to enable dictation."
    ),
    ErrorCode.API_KEY_INVALID: (
        "The OpenRouter API key was rejected. Check it in Models."
    ),
    ErrorCode.MODEL_LOAD_FAILED: "A selected model could not be loaded.",
    ErrorCode.MODEL_LOADING: "Loading the model in LM Studio…",
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


def get_error_message(code: ErrorCode) -> str:
    """Return fixed user-facing text; never interpolate private content."""
    return _MESSAGES[code]
