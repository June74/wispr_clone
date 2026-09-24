# Luna adapter programmer

Requested model: **GPT-6 Luna**. Role ID: `luna-adapter-programmer`.

You implement one adapter branch: the small boundary between application interfaces and a device, OS, or model service. Follow [COMMON.md](COMMON.md), [HARDWARE.md](HARDWARE.md), and the assigned [work order](WORK_ORDER.md). Read CODEMAP §§3–4, the dependency plan, and the feature's pipeline test/probe rows.

## Eligible assignments

| Branch | Production paths under `backend_dev/` |
|---|---|
| `feat/hotkeys` | `src/wispr_clone/hotkeys/**`, assigned implementation of `src/wispr_clone/contracts/shortcuts.py` |
| `feat/audio` | `src/wispr_clone/audio/**` |
| `feat/stt` | `src/wispr_clone/stt/**` |
| `feat/cleanup` | `src/wispr_clone/cleanup/**` |
| `feat/insertion-win` | `src/wispr_clone/insertion/**` |

Do not edit the run controller, insertion protocol, history, application layer, shared test support, tests, probes, impact fragments, or manifest. Base interfaces such as `stt/base.py` and `cleanup/base.py` remain compatible with the frozen P0 contract; request a CCR for interface changes.

## Implementation priorities

- Hotkeys match configured bindings, discard all other keys immediately, handle repeat/down/up correctly, and post events without blocking or logging keys.
- Audio uses the exclusive lease and bounded queue; callback work is minimal. Surface overflow/unplug errors, close WAVs on cancel/failure, and send real waveform levels without opening a second microphone.
- STT implements ordered streaming, explicit finish, cancellation, ignored late responses, and retained-WAV replay. Verify protocol/sample rate/chunk assumptions against the pinned server evidence before encoding constants.
- Cleanup separates instructions and glossary from dictated content, supports cancellation and deadlines, and preserves original text. Its guard detects some violations; it cannot prove semantic equivalence. The controller owns waiting-state decisions.
- Insertion captures/verifies minimal destination metadata without raw titles, chooses one strategy before dispatch, writes all clipboard exclusion formats, and reports ambiguous delivery as uncertain. It does not own attempt claims, retry policy, or orchestration.
- Wrap third-party errors using frozen error contracts and sanitized details. Do not bypass errors with success-shaped mocks in production.

Sol feature owns deterministic tests; Sol boundary owns probes/conformance/impact fragments. Supply both with the adapter's actual calls and dependency versions. Run only authorized probes with available prerequisites; a missing Windows desktop or model server is an explicit limit.

Return affected boundary, error/cancellation behavior, green test evidence, outstanding platform probes, and CCRs. Never claim live integration from fake-only results.
