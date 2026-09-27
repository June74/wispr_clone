# WO-fix-key-paste-trim — Pasted API key rejected as "invalid" (user-reported)

```text
Symptom: pasting the OpenRouter key and clicking Save shows "Some settings or command details
  are invalid" (ErrorCode validation).
Root cause (reproduced on the real PC with fake keys through real DPAPI):
  - `secret_store._validate_value` rejects any whitespace. Pasted keys often carry a leading or
    trailing space, newline or NBSP. A clean key saves fine.
  - Also, a trailing zero-width space (U+200B) is accepted, but the service would then reject the
    key.
Branch / worktree: fix/key-paste-trim / ~/projects/wc-trim
Writable: Luna: src/wispr_clone/application/commands/settings_commands.py, web/app.js
          Sol:  tests/unit/application/test_secret_commands*.py, web/tests/**
```

## Rules

1. `secret_set` normalizes before validating: it strips leading and trailing characters that are
   `str.isspace()`, or in {U+200B, U+200C, U+200D, U+2060, U+FEFF}.
   - Interior whitespace or control characters are still rejected (VALIDATION); interior
     zero-width characters are rejected too.
   - An empty result is rejected (VALIDATION).
   - The stored value is the normalized one.
2. The UI trims the same way before sending (a convenience; the backend is authoritative). It
   still clears the input immediately.
3. The value is never echoed or logged (unchanged).

## Tests (Sol)

| ID | Assertion |
|---|---|
| T-APP-032 | Through Api, secret_set with a fake key plus a leading/trailing space, "\n", "\r\n", NBSP, U+200B or U+FEFF → ok, configured true, and the stored value equals the clean key; an interior space or interior U+200B → validation; all-whitespace → validation |
| T-WEB-012 | The UI's normalize helper (exported from a pure module, e.g. lib/secrets.js) trims those characters; app.js uses it before secret_set |
