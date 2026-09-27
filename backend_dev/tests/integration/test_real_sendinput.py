"""T-INS-SI-002: opt-in native SendInput acceptance check."""

import os
import sys

import pytest

from wispr_clone.insertion.win32 import KeyEvent, RealWin32

pytestmark = [pytest.mark.integration, pytest.mark.windows, pytest.mark.manual]


def test_T_INS_SI_002_real_sendinput_accepts_single_key_up() -> None:
    if sys.platform != "win32" or os.environ.get("WISPR_REAL_GUI") != "1":
        pytest.skip("requires Windows and WISPR_REAL_GUI=1")

    # 0xFF is unassigned; key-up alone cannot type text or press a held key.
    assert RealWin32().send_inputs((KeyEvent(vk=0xFF, flags=0x0002),)) == 1
