"""Small secret stores for credentials that must stay out of application state."""

from __future__ import annotations

import ctypes
import os
import re
import tempfile
from ctypes import wintypes
from pathlib import Path
from typing import Any, Protocol, cast

from wispr_clone.contracts.common import ErrorCode, WisprError


class SecretStore(Protocol):
    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def clear(self, name: str) -> None: ...


_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _validate_name(name: str) -> None:
    if not isinstance(name, str) or _NAME.fullmatch(name) is None:
        raise WisprError(ErrorCode.VALIDATION, "secrets", "name")


def _validate_value(value: str) -> None:
    if not isinstance(value, str) or not 1 <= len(value) <= 512:
        raise WisprError(ErrorCode.VALIDATION, "secrets", "value")
    if any(
        character.isspace() or ord(character) < 32 or ord(character) == 127
        for character in value
    ):
        raise WisprError(ErrorCode.VALIDATION, "secrets", "value")


class MemorySecretStore:
    """In-memory implementation for tests and the offline self-test."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        _validate_name(name)
        return self._values.get(name)

    def set(self, name: str, value: str) -> None:
        _validate_name(name)
        _validate_value(value)
        self._values[name] = value

    def clear(self, name: str) -> None:
        _validate_name(name)
        self._values.pop(name, None)


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


class DpapiSecretStore:
    """Encrypt one credential per file with Windows user-scope DPAPI."""

    def __init__(self, directory: Path, *, entropy: bytes = b"WisprClone.v1") -> None:
        if os.name != "nt":
            raise OSError("DPAPI is available only on Windows")
        self.directory = directory
        self.entropy = entropy

    def _path(self, name: str) -> Path:
        _validate_name(name)
        return self.directory / f"{name}.dpapi"

    @staticmethod
    def _blob(data: bytes) -> tuple[_Blob, ctypes.Array[ctypes.c_ubyte] | None]:
        if not data:
            return _Blob(0, None), None
        buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        return _Blob(
            len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        ), buffer

    def _crypt(self, data: bytes, *, decrypt: bool) -> bytes:
        source, source_buffer = self._blob(data)
        entropy, entropy_buffer = self._blob(self.entropy)
        output = _Blob()
        win_dll = cast(Any, getattr(ctypes, "WinDLL"))
        crypt32 = win_dll("crypt32", use_last_error=True)
        kernel32 = win_dll("kernel32", use_last_error=True)
        function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
        if decrypt:
            function.argtypes = [
                ctypes.POINTER(_Blob),
                ctypes.c_void_p,
                ctypes.POINTER(_Blob),
                ctypes.c_void_p,
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.POINTER(_Blob),
            ]
        else:
            function.argtypes = [
                ctypes.POINTER(_Blob),
                wintypes.LPCWSTR,
                ctypes.POINTER(_Blob),
                ctypes.c_void_p,
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.POINTER(_Blob),
            ]
        function.restype = wintypes.BOOL
        try:
            if decrypt:
                ok = function(
                    ctypes.byref(source),
                    None,
                    ctypes.byref(entropy),
                    None,
                    None,
                    0x1,
                    ctypes.byref(output),
                )
            else:
                ok = function(
                    ctypes.byref(source),
                    "Wispr Clone",
                    ctypes.byref(entropy),
                    None,
                    None,
                    0x1,
                    ctypes.byref(output),
                )
            if not ok:
                get_last_error = cast(Any, getattr(ctypes, "get_last_error"))
                raise OSError(get_last_error(), "DPAPI operation failed")
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            del source_buffer, entropy_buffer
            if output.pbData:
                kernel32.LocalFree(output.pbData)

    def get(self, name: str) -> str | None:
        path = self._path(name)
        try:
            return self._crypt(path.read_bytes(), decrypt=True).decode("utf-8")
        except (OSError, UnicodeError, ValueError):
            return None

    def set(self, name: str, value: str) -> None:
        _validate_value(value)
        path = self._path(name)
        self.directory.mkdir(parents=True, exist_ok=True)
        encrypted = self._crypt(value.encode("utf-8"), decrypt=False)
        descriptor, temporary = tempfile.mkstemp(dir=self.directory, prefix=".secret-")
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def clear(self, name: str) -> None:
        self._path(name).unlink(missing_ok=True)
