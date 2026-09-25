"""Observable P0.2 contracts shared by the application and UI."""

import ast
import json
import sys
from pathlib import Path

import pytest


@pytest.mark.unit
@pytest.mark.invariant("Result has exactly one success or error branch")
def test_T_CON_001_result_exclusivity() -> None:
    from wispr_clone.contracts.common import ErrorCode, Result

    code = next(iter(ErrorCode))
    data = {"text": "synthetic transcript"}
    success = Result(ok=True, data=data, error=None)
    failure = Result(ok=False, data=None, error=code)

    assert success.ok is True
    assert success.data == data
    assert success.error is None
    assert failure.ok is False
    assert failure.data is None
    assert failure.error == code or getattr(failure.error, "error_code", None) == code

    for fields in (
        {"ok": True, "data": data, "error": code},
        {"ok": True, "data": None, "error": None},
        {"ok": False, "data": data, "error": code},
        {"ok": False, "data": None, "error": None},
    ):
        with pytest.raises((TypeError, ValueError)):
            Result(**fields)


@pytest.mark.unit
@pytest.mark.invariant("Every ErrorCode has a message and recovery action")
def test_T_CON_002_error_messages_cover_every_code() -> None:
    from wispr_clone.contracts.common import ErrorCode
    from wispr_clone.util.error_messages import (
        get_error_message,
        get_recovery_actions,
    )

    assert list(ErrorCode), "ErrorCode must contain the application's error cases"
    for code in ErrorCode:
        message = get_error_message(code)
        actions = get_recovery_actions(code)
        assert isinstance(message, str) and message.strip(), code
        assert isinstance(actions, (tuple, list)) and actions, code
        assert all(isinstance(action, str) and action.strip() for action in actions), (
            code
        )


@pytest.mark.unit
def test_T_CON_002_required_failure_behaviors_have_error_codes() -> None:
    from wispr_clone.contracts.common import ErrorCode

    required = {
        "validation",
        "unknown_command",
        "stale_version",
        "expired_command",
        "previous_session_token",
        "run_not_found",
        "run_expired",
        "run_deleted",
        "duplicate_request",
        "device_lease_conflict",
        "microphone_unavailable",
        "microphone_disconnected",
        "audio_queue_overflow",
        "no_speech_detected",
        "stt_unavailable",
        "model_load_failed",
        "stt_timeout",
        "stt_stream_closed",
        "cleanup_unavailable",
        "cleanup_timeout",
        "cleanup_rejected",
        "cloud_model_forbidden",
        "non_loopback_endpoint",
        "destination_unverifiable",
        "destination_closed",
        "destination_wait_limit_exceeded",
        "insertion_failed",
        "insertion_uncertain",
        "storage_error",
        "deletion_failed",
    }
    assert required <= {code.value for code in ErrorCode}


@pytest.mark.unit
def test_T_CON_contracts_import_only_stdlib_or_contracts() -> None:
    contracts_dir = Path(__file__).resolve().parents[3] / "src/wispr_clone/contracts"
    for path in contracts_dir.glob("*.py"):
        module = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(module):
            if isinstance(node, ast.Import):
                names = (alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, (path.name, node.module)
                names = (node.module or "",)
            else:
                continue
            for name in names:
                assert (
                    name == "wispr_clone.contracts"
                    or name.startswith("wispr_clone.contracts.")
                    or name.split(".", maxsplit=1)[0] in sys.stdlib_module_names
                ), (
                    path.name,
                    name,
                )


EVENT_NAMES = {
    "run:state",
    "run:recovery",
    "models:status",
    "history:changed",
    "audio:level",
}

EVENT_SAMPLES: dict[str, dict[str, object]] = {
    "run:state": {
        "name": "run:state",
        "run_id": "synthetic-run",
        "version": 2,
        "status": "processing",
    },
    "run:recovery": {
        "name": "run:recovery",
        "run_id": "synthetic-run",
        "version": 2,
        "status": "held",
        "actions": ["retry_stt", "copy"],
    },
    "models:status": {
        "name": "models:status",
        "models": [
            {
                "model_id": "synthetic-stt",
                "role": "stt",
                "ready": True,
                "error_code": None,
            },
            {
                "model_id": "synthetic-cleanup",
                "role": "cleanup",
                "ready": False,
                "error_code": "model_load_failed",
            },
        ],
    },
    "history:changed": {
        "name": "history:changed",
        "run_ids": ["synthetic-run"],
        "reason": "updated",
    },
    "audio:level": {
        "name": "audio:level",
        "run_id": None,
        "bands": [0.0, 0.25, 1.0],
    },
}


def _assert_data_only(value: object) -> None:
    if value is None or type(value) in (str, int, float, bool):
        return
    if type(value) is list:
        for item in value:
            _assert_data_only(item)
        return
    if type(value) is dict:
        for key, item in value.items():
            assert type(key) is str
            _assert_data_only(item)
        return
    pytest.fail(f"event contains a non-data value: {type(value).__name__}")


@pytest.mark.unit
def test_T_CON_003_every_event_payload_is_json_data() -> None:
    from wispr_clone.contracts.events import EVENT_PAYLOAD_TYPES

    assert set(EVENT_PAYLOAD_TYPES) == EVENT_NAMES
    assert set(EVENT_SAMPLES) == EVENT_NAMES
    for name, payload_type in EVENT_PAYLOAD_TYPES.items():
        fields = EVENT_SAMPLES[name]
        assert payload_type.__required_keys__ == set(fields), name
        payload = payload_type(**fields)
        _assert_data_only(payload)
        encoded = json.dumps(payload, allow_nan=False)
        assert json.loads(encoded) == payload


@pytest.mark.unit
def test_T_CON_004_boundary_exceptions_expose_fields() -> None:
    from wispr_clone.contracts.common import ErrorCode, ThirdPartyError, WisprError

    code = next(iter(ErrorCode))
    external = ThirdPartyError(
        dependency="synthetic-dependency",
        operation="synthetic-operation",
        detail="synthetic failure",
        error_code=code,
    )
    internal = WisprError(
        error_code=code, where="synthetic-boundary", why="synthetic invariant"
    )

    assert isinstance(external, Exception)
    assert external.dependency == "synthetic-dependency"
    assert external.operation == "synthetic-operation"
    assert external.detail == "synthetic failure"
    assert external.error_code == code
    assert isinstance(internal, Exception)
    assert internal.error_code == code
    assert internal.where == "synthetic-boundary"
    assert internal.why == "synthetic invariant"


@pytest.mark.unit
@pytest.mark.parametrize("error_kind", ["third_party", "wispr"])
def test_T_CON_004_exception_messages_do_not_echo_private_detail(
    error_kind: str,
) -> None:
    from wispr_clone.contracts.common import ErrorCode, ThirdPartyError, WisprError

    private_text = "SYNTHETIC_PRIVATE_TRANSCRIPT"
    if error_kind == "third_party":
        error = ThirdPartyError(
            "stt", "finalize", private_text, ErrorCode.STT_UNAVAILABLE
        )
    else:
        error = WisprError(ErrorCode.VALIDATION, "command", private_text)

    assert private_text not in str(error)


@pytest.mark.unit
def test_T_CON_005_status_outcome_and_contract_values() -> None:
    from wispr_clone.contracts import CONTRACT_VERSION
    from wispr_clone.contracts.run import (
        AttemptOutcome,
        CleanupStatus,
        InsertionOutcome,
        RecoveryAction,
        RunStatus,
    )

    assert CONTRACT_VERSION == 1
    assert {member.value for member in RunStatus} == {
        "recording",
        "processing",
        "awaiting_cleanup_choice",
        "awaiting_destination",
        "held",
        "done",
        "error",
        "uncertain",
        "cancelled",
    }
    assert {member.value for member in AttemptOutcome} == {
        "in_flight",
        "inserted",
        "failed",
        "uncertain",
        "cancelled",
    }
    assert {member.value for member in InsertionOutcome} == {
        "none",
        "in_flight",
        "inserted",
        "failed",
        "uncertain",
        "cancelled",
    }
    assert {member.value for member in CleanupStatus} == {
        "off",
        "pending",
        "ok",
        "failed",
        "rejected",
    }
    assert {member.value for member in RecoveryAction} == {
        "retry_stt",
        "retry_cleanup",
        "use_original",
        "copy",
        "insert",
    }
