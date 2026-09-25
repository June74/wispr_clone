"""Pinned model registry behavior for WO-feat-settings-models."""

import importlib

import pytest

from wispr_clone import config
from wispr_clone.contracts.common import ErrorCode, WisprError


def registry():
    return importlib.import_module("wispr_clone.models.registry")


@pytest.mark.unit
def test_T_REG_001_defaults_order_filters_and_lookups() -> None:
    module = registry()
    models = module.default_registry()
    stt, cleanup = models.list_models()
    assert (
        stt.model_id,
        stt.role,
        stt.display_name,
        stt.local,
        stt.runtime,
        stt.endpoint,
    ) == (
        "voxtral-mini-4b-realtime-2602",
        "stt",
        "Voxtral Mini 4B Realtime",
        True,
        "transcribe-cpp",
        None,
    )
    assert (
        cleanup.model_id,
        cleanup.role,
        cleanup.display_name,
        cleanup.local,
        cleanup.runtime,
        cleanup.endpoint,
    ) == (
        config.LM_STUDIO_MODEL_ID,
        "cleanup",
        "Llama 3.1 8B Instruct",
        True,
        "lmstudio",
        config.LM_STUDIO_ENDPOINT,
    )
    assert len(models.list_models()) == 2
    assert models.list_models("stt") == (stt,)
    assert models.list_models("cleanup") == (cleanup,)
    for item in (stt, cleanup):
        assert models.get(item.model_id) == item
        assert models.role_of(item.model_id) == item.role
        assert models.is_local(item.model_id) is True
    assert models.get("missing") is None
    assert models.role_of("missing") is None
    assert models.is_local("missing") is False


@pytest.mark.unit
def test_T_REG_001_duplicate_and_empty_ids_rejected() -> None:
    module = registry()
    item = module.ModelInfo("one", "stt", "One", True, "transcribe-cpp", None)
    for items in (
        (item, item),
        (module.ModelInfo("", "stt", "Empty", True, "transcribe-cpp", None),),
    ):
        with pytest.raises(WisprError) as caught:
            module.ModelRegistry(items)
        assert caught.value.error_code == ErrorCode.VALIDATION
        assert caught.value.where == "models.registry"


@pytest.mark.unit
@pytest.mark.invariant("local endpoint loopback")
@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://127.0.0.1:1234/v1", True),
        ("http://127.0.0.5:1234", True),
        ("http://[::1]:1234", True),
        ("http://[::ffff:127.0.0.1]:1234", True),
        ("HTTP://127.0.0.1:1234", True),
        ("https://127.0.0.1", True),
        ("http://localhost:1234", False),
        ("http://0.0.0.0:1234", False),
        ("http://192.168.1.20:1234", False),
        ("https://api.example.com", False),
        ("ftp://127.0.0.1", False),
        ("", False),
        ("not a url", False),
        ("http://[::1", False),
        ("http:///missing-host", False),
        ("http://127.0.0.1:99999", False),
        ("http://127.0.0.1:0", False),
        ("http://127.0.0.1:not-a-port", False),
        ("http://user:pw@127.0.0.1:1234", False),
    ],
)
def test_T_REG_002_loopback_endpoint_truth_table(url: str, expected: bool) -> None:
    assert registry().is_loopback_endpoint(url) is expected


@pytest.mark.unit
def test_T_REG_002_local_remote_endpoint_rejected_cloud_accepted() -> None:
    module = registry()
    remote = "https://api.example.com/v1"
    local = module.ModelInfo("local", "cleanup", "Local", True, "lmstudio", remote)
    with pytest.raises(WisprError) as caught:
        module.ModelRegistry([local])
    assert caught.value.error_code == ErrorCode.NON_LOOPBACK_ENDPOINT
    assert caught.value.where == "models.registry"

    cloud = module.ModelInfo("cloud", "cleanup", "Cloud", False, "provider", remote)
    models = module.ModelRegistry([cloud])
    assert models.list_models() == (cloud,)
    assert models.is_local("cloud") is False


@pytest.mark.unit
@pytest.mark.invariant("local endpoint loopback")
@pytest.mark.parametrize(
    "endpoint",
    [
        "http://127.0.0.1:99999",
        "http://127.0.0.1:0",
        "http://127.0.0.1:not-a-port",
        "http://user:pw@127.0.0.1:1234",
    ],
)
def test_T_REG_002_local_model_rejects_invalid_port_or_user_info(
    endpoint: str,
) -> None:
    module = registry()
    local = module.ModelInfo("local", "cleanup", "Local", True, "lmstudio", endpoint)
    with pytest.raises(WisprError) as caught:
        module.ModelRegistry([local])
    assert caught.value.error_code == ErrorCode.NON_LOOPBACK_ENDPOINT
    assert caught.value.where == "models.registry"


@pytest.mark.unit
@pytest.mark.invariant("local endpoint loopback")
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:1234\nX-Injected: value",
        "http://127.0.0.1:1234\tX-Injected: value",
    ],
)
def test_T_REG_002_rejects_url_with_control_characters(url: str) -> None:
    assert registry().is_loopback_endpoint(url) is False
