# WO-feat-hotkeys — Shortcut contract and global hotkey service

```text
Work-order ID: WO-feat-hotkeys
Role file / requested model: RED + verify: sol-feature-test-author.md (T-KEY) and
                             sol-boundary-test-author.md (P-PYNPUT-001, pynput impact fragment) / gpt-6-sol
                             GREEN: luna-adapter-programmer.md / gpt-6-luna
Pipeline branch or P0/M stage: Wave 1, branch feat/hotkeys
Outcome and observable acceptance:
  A pure shortcut contract (parse / format / validate bindings) that settings can reuse, and a
  hotkey service that turns key down/up events into start/stop/cancel callbacks for hold and toggle
  modes, ignores OS auto-repeat, and immediately discards every non-binding key: it never logs,
  stores or forwards typed keys. A thin pynput adapter feeds it on Windows.
Base revision / worktree / branch: cc29601 / ~/projects/wc-hotkeys / feat/hotkeys
Relevant sections: feature spec "Recording controls"; CODEMAP.md §2 (hotkey listener row: discard
  every other key, post only start/stop/cancel, no blocking work), §3 (hotkeys row; contracts rule;
  callbacks table); dev_pipeline.md §6 Wave 1 row feat/hotkeys, §6 note on contracts/shortcuts.py;
  WO-feat-settings-models (shortcut fields; T-SET-002 deferred to after this order).
Exact writable paths (under backend_dev/):
  Sol:  tests/unit/hotkeys/**, tests/unit/contracts/test_shortcuts.py (new file only),
        tests/probes/pynput/**, tests/_attribution/impact/pynput.toml
  Luna: src/wispr_clone/contracts/shortcuts.py (assigned to this branch by the pipeline),
        src/wispr_clone/hotkeys/__init__.py (docstring only), hotkeys/hotkey_service.py,
        hotkeys/pynput_listener.py
Read-only: everything else (other contracts files are frozen).
Allowed imports: contracts.shortcuts -> contracts.common + stdlib only (it is a contract);
  hotkeys -> contracts + stdlib (threading, dataclasses, enum, typing); pynput only in
  hotkeys/pynput_listener.py and imported LAZILY (Windows-only dependency).
Required tiers: S, U on ubuntu and windows; W for P-PYNPUT-001 (windows only, skipped elsewhere).
Check commands (from backend_dev/, UV_LINK_MODE=copy):
  uv sync --locked; uv run ruff check .; uv run ruff format --check .;
  uv run mypy src scripts tests/_attribution tests/fakes; uv run python scripts/check_imports.py;
  uv run pytest -q -W error
Authorization: edit only writable paths; no git writes; no PRs; no new dependencies; tests never
  install a real global keyboard hook (the probe only starts/stops a listener on Windows CI).
Privacy (core invariant): no key other than the configured bindings is ever logged, buffered,
  counted or passed anywhere.
Handoff: coordinator. Sol: RED command/output. Luna: GREEN outputs. Sol: verification findings.
```

## Pinned API (use these exact names)

`wispr_clone.contracts.shortcuts` (pure, frozen once merged):

```python
MODIFIERS: tuple[str, ...] = ("ctrl", "alt", "shift", "win")     # canonical order
FUNCTION_KEYS: frozenset[str]      # "f1" .. "f24"
NAMED_KEYS: frozenset[str]         # "space", "escape", "tab", "enter", "backspace", "delete",
                                   # "insert", "home", "end", "page_up", "page_down",
                                   # "up", "down", "left", "right", "pause", "scroll_lock"
KEYS: frozenset[str]               # a-z, 0-9, FUNCTION_KEYS, NAMED_KEYS

@dataclass(frozen=True, slots=True)
class KeyBinding:
    modifiers: frozenset[str]      # subset of MODIFIERS
    key: str                       # one of KEYS

def parse_binding(text: str) -> KeyBinding
def format_binding(binding: KeyBinding) -> str        # "ctrl+shift+space" (canonical order)
def validate_bindings(dictation: KeyBinding, cancel: KeyBinding) -> None
```

- `parse_binding`: case-insensitive, `+`-separated, surrounding whitespace ignored per part;
  aliases accepted: `control`→`ctrl`, `option`→`alt`, `cmd`/`meta`/`super`→`win`, `esc`→`escape`,
  `return`→`enter`, `pgup`/`pgdn`→`page_up`/`page_down`, and the browser forms `KeyD`→`d`,
  `Digit5`→`5`, `Space`→`space`. Exactly one non-modifier key. Errors (all
  `WisprError(ErrorCode.VALIDATION, "shortcuts", <why>)`, why names the rule, never the raw text):
  empty/too long (> 64) → `"empty"`/`"too long"`; unknown key name → `"unknown key"`; no key or two
  keys → `"one key"`; repeated modifier → `"duplicate modifier"`; a letter, digit, `space`,
  `enter`, `tab` or `backspace` WITHOUT `ctrl`/`alt`/`win` → `"needs modifier"` (it would fire while
  typing; `shift` alone does not count).
- `format_binding(parse_binding(x))` round-trips; the settings defaults `ctrl+shift+space` and
  `escape` parse.
- `validate_bindings`: identical bindings → `WisprError(VALIDATION, "shortcuts", "conflict")`.

`wispr_clone.hotkeys.hotkey_service`:

```python
class KeyAction(StrEnum): DOWN = "down"; UP = "up"

class HotkeyService:
    def __init__(self, *, dictation: KeyBinding, cancel: KeyBinding,
                 mode: Literal["hold", "toggle"],
                 on_start: Callable[[], None], on_stop: Callable[[], None],
                 on_cancel: Callable[[], None],
                 post: Callable[[Callable[[], None]], None]) -> None
    def handle(self, action: KeyAction, key: str) -> None     # called on the listener thread
    def reset(self) -> None                                     # forget pressed state (focus loss, restart)
    @property
    def tracked_keys(self) -> frozenset[str]                   # keys currently remembered as pressed
```

Behavior:

1. `key` is a canonical name (a `KEYS` member or a modifier) or `""` for anything the listener
   could not name. A key that is neither a modifier nor the key of a configured binding is dropped
   on the spot: no state change, no callback, no logging (T-KEY-005). `tracked_keys` only ever
   contains modifiers and the two bindings' keys.
2. A binding "fires" on the DOWN of its key while exactly its modifiers are held (extra modifiers →
   no match, so `ctrl+shift+space` does not fire `ctrl+space`).
3. **Hold** (T-KEY-002): dictation fires → `on_start`; the UP of the dictation key (or of one of its
   modifiers) while started → `on_stop`, once.
4. **Toggle** (T-KEY-003): each firing alternates `on_start` / `on_stop`.
5. **Auto-repeat** (T-KEY-006): a DOWN for a key already tracked as pressed is ignored (no second
   start, no toggle flip).
6. **Cancel** (T-KEY-004): the cancel binding firing → `on_cancel`; in hold mode it also ends the
   hold without an `on_stop`.
7. Callbacks are never called on the listener thread: each is passed to `post` (the app wires
   `loop.call_soon_threadsafe`); `handle` does no blocking work.

`wispr_clone.hotkeys.pynput_listener`:

```python
class PynputListener:
    def __init__(self, service: HotkeyService, *, module: ModuleType | None = None) -> None
    def start(self) -> None          # imports pynput.keyboard lazily; Listener(on_press, on_release)
    def stop(self) -> None           # idempotent
def key_name(key: object, module: ModuleType) -> str   # pynput Key/KeyCode -> canonical name or ""
```

`key_name` maps `Key.ctrl/ctrl_l/ctrl_r`→`ctrl`, `alt*`/`alt_gr`→`alt`, `shift*`→`shift`,
`cmd*`→`win`, `Key.space`→`space`, `Key.esc`→`escape`, `Key.f1..f24`, the named keys, and
`KeyCode` with a single printable ASCII letter/digit `char` → lowercase char; everything else →
`""`. It never stores or logs the key.

## Tests (Sol; IDs in function names; no real keyboard hook in unit tests)

| ID | Must assert |
|---|---|
| T-KEY-001 | `parse_binding` accepts the defaults and aliases (`Ctrl+Shift+Space`, `ctrl + alt + KeyD`, `F9`, `esc`) with canonical `format_binding`; rejects each pinned error with its `why`; the raw text (a sentinel) never appears in the error; `validate_bindings` rejects identical dictation/cancel bindings |
| T-KEY-002 | hold mode: down(ctrl), down(shift), down(space) → one `on_start`; up(space) → one `on_stop`; releasing a modifier first also stops; extra modifier (ctrl+alt+shift+space) does not start |
| T-KEY-003 | toggle mode: fire, release, fire → start then stop; a third firing starts again |
| T-KEY-004 | cancel binding → `on_cancel`; in hold mode during a hold → `on_cancel` and no `on_stop` afterwards |
| **T-KEY-005** (invariant) | typing a sentence of letters, digits and punctuation (`""` keys) between and during bindings causes no callback, leaves `tracked_keys` ⊆ {modifiers, binding keys}, emits no log record at any level (`caplog`), and the service object holds no other key (check `vars()`/slots for sequences containing the typed letters) |
| T-KEY-006 | repeated DOWN of the dictation key (auto-repeat) in both modes causes no second start and no toggle flip; after UP a new press works |
| T-KEY-007 | every callback is delivered via `post` (a recording `post` that does not run them immediately shows zero direct calls from `handle`); `reset()` clears pressed state |
| T-KEY-008 | `key_name` with a fake pynput-like module maps modifiers (left/right variants), space, esc, F-keys, letters/digits (case-folded) and returns `""` for everything else; `PynputListener` imports pynput only in `start()` (importing the module works without pynput) and `stop()` is idempotent |

Probe (Sol boundary), tests/probes/pynput/, `@pytest.mark.probe("pynput")` and `@pytest.mark.windows`,
skipped with a reason when pynput is not importable:

- P-PYNPUT-001 `pynput.__version__` is 1.8.2 (via `importlib.metadata`); a
  `pynput.keyboard.Listener` with no-op callbacks starts and stops without an exception; the names
  the adapter uses exist (`Key.ctrl_l`, `Key.ctrl_r`, `Key.alt_gr`, `Key.cmd`, `Key.space`,
  `Key.esc`, `Key.f24`, `KeyCode.char`). Synthetic key events are NOT sent (hosted runner).

Impact fragment `tests/_attribution/impact/pynput.toml`: dependency `pynput`, kind library, modules
`["hotkeys.pynput_listener"]`, features global dictation shortcut / cancel shortcut, error_codes
`["validation"]` (no dedicated code exists; the listener failing to start is reported through
setup), action = check the pynput pin in uv.lock and that the app runs on the interactive desktop.

## Coordinator decisions after RED review

1. `reset()` during an active hold (hold mode, started, not yet stopped) posts exactly one
   `on_stop` and clears pressed state: a lost key-up (focus change, hook restart) must never leave
   recording running. In toggle mode `reset()` only clears pressed state (no callback).

## Coordinator review of GREEN (binding)

2. Thread ownership: ALL service state (`_pressed`, hold/toggle flags) is read and written only on
   the listener thread inside `handle`/`reset`. Posted callables are exactly the user callbacks
   (`on_start`, `on_stop`, `on_cancel`), never closures that touch service state (the GREEN code's
   deferred `start()` closure reads `_pressed` on the loop thread: a data race). Order is preserved
   by `post` (call_soon_threadsafe is FIFO), so press+release before the loop runs still yields
   start then stop.
3. A cancel binding WITHOUT modifiers (e.g. `escape`) fires regardless of held modifiers, so Esc
   cancels while `ctrl+shift+space` is held in hold mode. A cancel binding WITH modifiers needs an
   exact modifier match like any other binding.
