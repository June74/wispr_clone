# WO-fix-sendinput-struct: SendInput is rejected (INPUT struct too small)

```text
User report: the model works, but nothing is pasted into Notepad.
Evidence (run status and outcome codes only): runs reach insertion with output_selection=original.
  The automatic attempt ends 'failed' after about 0.55 s, which is ProtocolResult "no events":
  SendInput accepted 0 events.
Root cause (reproduced on the real PC): RealWin32.send_inputs defines INPUT with a union holding
  ONLY KEYBDINPUT, so sizeof(INPUT) = 32 on x64, where Windows requires 40 (the union must also hold
  MOUSEINPUT and HARDWAREINPUT). SendInput(cbSize=32) fails with ERROR_INVALID_PARAMETER (87).
  Ctrl+V is never sent, and the clipboard is restored, so nothing appears.
Why tests missed it: the fake Win32 returns len(inputs) (fake drift).
Branch / worktree: fix/sendinput-struct / ~/projects/wc-input
Writable: Luna: src/wispr_clone/insertion/win32.py
          Sol:  tests/unit/insertion/*, tests/integration/test_real_sendinput.py (new)
```

## Rules

1. Define MOUSEINPUT, KEYBDINPUT, HARDWAREINPUT, the INPUT union (all three) and INPUT at module
   level in win32.py, with Windows field types. `dwExtraInfo` is ULONG_PTR (`ctypes.c_size_t`).
2. `send_inputs` uses a private `ctypes.WinDLL("user32", use_last_error=True)`:
   - SendInput argtypes (UINT, POINTER(INPUT), c_int), restype UINT;
   - cbSize = sizeof(INPUT);
   - it returns the accepted count;
   - if that count is 0, it logs a code-only warning with GetLastError, and never logs the text.
3. Audit the other ctypes uses in win32.py: they must not set argtypes on the shared
   `ctypes.windll`. Leave the rest of the behaviour unchanged.

## Tests (Sol)

| ID | Assertion |
|---|---|
| T-INS-SI-001 | Pure layout checks: sizeof(INPUT) == 40 on 64-bit Python (28 on 32-bit); INPUT.union offset == 8 on 64-bit; the union holds ki, mi and hi |
| T-INS-SI-002 (real, win32, WISPR_REAL_GUI=1) | SendInput with ONE harmless event (a VK_NONAME 0xFC key-up, or KEYEVENTF_KEYUP of an unassigned VK such as 0xFF) through RealWin32.send_inputs returns 1. It must not type text or disturb the user. No screenshots |
| T-INS-SI-003 | The fake Win32 used by the insertion tests still behaves the same (no regression) |
