"""T-INS-SI-001: Win32 SendInput layout matches the native INPUT ABI."""

import ctypes


def test_T_INS_SI_001_input_layout() -> None:
    from wispr_clone.insertion.win32 import (
        HARDWAREINPUT,
        INPUT,
        INPUT_UNION,
        KEYBDINPUT,
        MOUSEINPUT,
    )

    pointer_size = ctypes.sizeof(ctypes.c_void_p)
    assert ctypes.sizeof(INPUT) == (40 if pointer_size == 8 else 28)
    if pointer_size == 8:
        assert INPUT.union.offset == 8

    fields = dict(INPUT_UNION._fields_)
    assert fields["ki"] is KEYBDINPUT
    assert fields["mi"] is MOUSEINPUT
    assert fields["hi"] is HARDWAREINPUT
    assert dict(KEYBDINPUT._fields_)["dwExtraInfo"] is ctypes.c_size_t
