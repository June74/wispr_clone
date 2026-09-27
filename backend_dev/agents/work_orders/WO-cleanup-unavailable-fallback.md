# WO-cleanup-unavailable-fallback: paste the original when cleanup is unavailable

```text
User report: no text lands in Notepad.
Evidence (run status and error codes only): 3 runs, each 4–73 s of audio, ended in
  awaiting_cleanup_choice with cleanup_status=failed and reason=cleanup_unavailable. The LM Studio
  cleanup model isn't available, and the choice UI lived in the in-app pill the user never sees.
User decision (2026-09-27): "Paste the original" when cleanup is unavailable.
Branch / worktree: fix/cleanup-unavailable-fallback / ~/projects/wc-clean
Writable: Luna: src/wispr_clone/pipeline/run_controller.py
          Sol:  tests/unit/pipeline/* (new or updated cleanup-fallback tests)
```

## Rules

1. When cleanup fails with ErrorCode.CLEANUP_UNAVAILABLE, or with the generic-exception path that
   currently records "cleanup_unavailable", the run does NOT go to awaiting_cleanup_choice. It:
   - records cleanup_status=FAILED, cleanup_reason="cleanup_unavailable", output_selection="original";
   - inserts the adjusted original text through the same path as the "use_original" recovery
     action, so insertion and history behaviour are identical;
   - publishes run:state events as a normal insert does.
2. Other failures keep today's behaviour and still await a choice:
   - REJECTED (check_cleanup verdict);
   - other WisprError codes such as timeouts or bad output.
3. Cancellation and abort checks around the fallback keep the existing ordering. Cancelling
   during the fallback insert still cancels.
4. Never log or emit transcript text.

## Tests (Sol)

| ID | Assertion |
|---|---|
| T-PIPE-CLN-001 | Cleanup raising WisprError(CLEANUP_UNAVAILABLE) → the run inserts the original text; final status is the normal inserted/done status; cleanup_status failed, reason cleanup_unavailable, output_selection original; no awaiting_cleanup_choice transition |
| T-PIPE-CLN-002 | A generic Exception from cleanup → same as 001 |
| T-PIPE-CLN-003 | A rejected verdict → still awaiting_cleanup_choice (unchanged) |
| T-PIPE-CLN-004 | A cancel flag set before the fallback insert → cancelled; no insert |
