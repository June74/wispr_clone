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
        stt.endpoint,
    ) == (
        "openai/whisper-large-v3-turbo",
        "stt",
        "Whisper Large v3 Turbo (DeepInfra)",
        False,
        "https://openrouter.ai/api/v1",
    )
    assert (
        cleanup.model_id,
        cleanup.role,
        cleanup.display_name,
        cleanup.local,
        cleanup.endpoint,
    ) == (
        config.LM_STUDIO_MODEL_ID,
        "cleanup",
        "Llama 3.1 8B Instruct",
        True,
        config.LM_STUDIO_ENDPOINT,
    )
    assert len(models.list_models()) == 2
    assert models.list_models("stt") == (stt,)
    assert models.list_models("cleanup") == (cleanup,)
    for item in (stt, cleanup):
        assert models.get(item.model_id) == item
        assert models.role_of(item.model_id) == item.role
        assert models.is_local(item.model_id) is item.local
    assert models.get("missing") is None
    assert models.role_of("missing") is None
    assert models.is_local("missing") is False


@pytest.mark.unit
def test_T_REG_001_duplicate_and_empty_ids_rejected() -> None:
    module = registry()
    item = module.ModelInfo("one", "stt", "One", True, None)
    for items in (
        (item, item),
        (module.ModelInfo("", "stt", "Empty", True, None),),
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
    local = module.ModelInfo("local", "cleanup", "Local", True, remote)
    with pytest.raises(WisprError) as caught:
        module.ModelRegistry([local])
    assert caught.value.error_code == ErrorCode.NON_LOOPBACK_ENDPOINT
    assert caught.value.where == "models.registry"

    cloud = module.ModelInfo("cloud", "cleanup", "Cloud", False, remote)
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
    local = module.ModelInfo("local", "cleanup", "Local", True, endpoint)
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


@pytest.mark.unit
@pytest.mark.parametrize(
    ("role", "model_id", "accepted"),
    [
        ("stt", "deepgram/nova-3", True),
        ("stt", "qwen/qwen3-asr-flash-2026-02-10", True),
        ("stt", "no-vendor-prefix", False),
        ("stt", "Upper/Case", False),
        ("cleanup", "meta-llama-3.1-8b-instruct", True),
        ("cleanup", "qwen/qwen3-8b@q4_k_m", True),
        ("cleanup", "has space", False),
        ("cleanup", "../escape", False),
        ("cleanup", "a" * 201, False),
        ("other", "deepgram/nova-3", False),
    ],
)
def test_T_REG_004_discovered_ids_are_accepted_by_shape_per_role(
    role: str, model_id: str, accepted: bool
) -> None:
    from wispr_clone.models.registry import default_registry

    models = default_registry()
    assert models.accepts(role, model_id) is accepted
    resolved = models.resolve(role, model_id)
    assert (resolved is not None) is accepted
    if resolved is not None:
        assert resolved.role == role
        assert resolved.local is (role == "cleanup")


@pytest.mark.unit
def test_T_REG_004_registered_ids_keep_their_role() -> None:
    from wispr_clone.models.registry import default_registry

    models = default_registry()
    assert models.resolve("cleanup", "openai/whisper-large-v3-turbo") is None
    assert models.resolve("stt", "openai/whisper-large-v3-turbo") is not None
