"""Secret storage never persists a readable OpenRouter key."""

import sys
from pathlib import Path

import pytest

from wispr_clone.contracts.common import ErrorCode, WisprError

FAKE_KEY = "sk-or-v1-test-secret-store"
NAME = "openrouter_api_key"


@pytest.mark.unit
def test_T_SET_020_memory_store_round_trip_and_validation() -> None:
    from wispr_clone.settings.secret_store import MemorySecretStore

    store = MemorySecretStore()
    assert store.get(NAME) is None
    store.set(NAME, FAKE_KEY)
    assert store.get(NAME) == FAKE_KEY
    store.clear(NAME)
    assert store.get(NAME) is None
    for invalid in ("", "x" * 513, "has space", "has\nnewline", "has\x00control"):
        with pytest.raises(WisprError) as caught:
            store.set(NAME, invalid)
        assert caught.value.error_code == ErrorCode.VALIDATION


@pytest.mark.unit
@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI only")
def test_T_SET_020_dpapi_ciphertext_corrupt_file_and_clear(tmp_path: Path) -> None:
    from wispr_clone.settings.secret_store import DpapiSecretStore

    store = DpapiSecretStore(tmp_path)
    assert store.get(NAME) is None
    store.set(NAME, FAKE_KEY)
    path = tmp_path / f"{NAME}.dpapi"
    ciphertext = path.read_bytes()
    assert ciphertext
    assert FAKE_KEY.encode() not in ciphertext
    assert store.get(NAME) == FAKE_KEY
    path.write_bytes(b"corrupt test ciphertext")
    assert store.get(NAME) is None
    store.clear(NAME)
    assert not path.exists()


@pytest.mark.unit
@pytest.mark.skipif(sys.platform == "win32", reason="non-Windows contract")
def test_T_SET_020_dpapi_unavailable_outside_windows(tmp_path: Path) -> None:
    from wispr_clone.settings.secret_store import DpapiSecretStore

    with pytest.raises(OSError):
        DpapiSecretStore(tmp_path)
