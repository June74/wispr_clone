# WO-feat-settings-shortcuts — T-SET-002: settings validate shortcuts with the contract

```text
Work-order ID: WO-feat-settings-shortcuts
Role file / requested model: RED + verify: sol-feature-test-author.md / gpt-6-sol
                             GREEN: luna-core-programmer.md / gpt-6-luna
Pipeline branch or P0/M stage: follow-up to feat/settings-models (T-SET-002 was deferred until
  feat/hotkeys merged; it has, PR #16)
Outcome and observable acceptance:
  parse_settings rejects a dictation or cancel shortcut that the shortcut contract rejects, and a
  dictation/cancel pair that conflicts; valid shortcuts are stored in canonical form.
Base revision / worktree / branch: origin/main / ~/projects/wc-settings-shortcuts / feat/settings-shortcuts
Relevant sections: WO-feat-settings-models (T-SET-002 deferral), WO-feat-hotkeys (parse_binding,
  format_binding, validate_bindings and their error rules); CODEMAP §3 (settings -> contracts.shortcuts).
Exact writable paths (under backend_dev/):
  Sol:  tests/unit/settings/test_schema_shortcuts.py (new file)
  Luna: src/wispr_clone/settings/schema.py
Allowed imports: settings.schema may import wispr_clone.contracts.shortcuts.
Check commands (from backend_dev/, UV_LINK_MODE=copy):
  uv sync --locked; uv run ruff check .; uv run ruff format --check .;
  uv run mypy src scripts tests/_attribution tests/fakes; uv run python scripts/check_imports.py;
  uv run pytest -q -W error
Authorization: edit only writable paths; no git writes; no PRs; no new dependencies.
```

## Rules

- In `parse_settings`, after pydantic validation and before the catalog checks: parse both
  shortcut fields with `contracts.shortcuts.parse_binding`; a `WisprError` from it becomes
  `WisprError(ErrorCode.VALIDATION, "settings.schema", "<field name>")` (field name only, never the
  typed text); then `validate_bindings(dictation, cancel)` → conflict becomes
  `WisprError(VALIDATION, "settings.schema", "dictation_shortcut, cancel_shortcut")`.
- The returned `Settings` stores `format_binding(...)` of each (e.g. `"Ctrl + Shift + Space"` →
  `"ctrl+shift+space"`), so storage is canonical. Defaults are unchanged and valid.

## Tests (Sol)

| ID | Must assert |
|---|---|
| T-SET-002 | `"ctrl+shift+space"`/`"escape"` accepted; `"Ctrl + Shift + Space"` stored canonically; unknown key, two keys, a bare letter (`"d"`), `"shift+a"` → `VALIDATION` with the field name as `why`; identical dictation and cancel → the pinned conflict `why`; a sentinel inside a bad shortcut never appears in `str(error)` or `error.why`; `settings_to_data` round-trips the canonical form |
