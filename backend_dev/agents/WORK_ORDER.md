# Work order template

The coordinator fills this in for one feature or integration substep. A role file alone is not an implementation assignment.

```text
Work-order ID:
Role file / requested model:
Pipeline branch or P0/M stage:
Outcome and observable acceptance:
Base revision / worktree / branch:
Relevant spec, codemap, and pipeline sections:
Prerequisites and evidence (including applicable G gates):
Exact writable paths:
Read-only interfaces/callers to inspect:
Frozen contract version and allowed imports:
Test IDs and expected assertions:
Probe IDs / conformance cases / sole impact-fragment owner:
RED owner (GPT-6 Sol) and test revision:
GREEN owner (GPT-6 Luna):
Verification owner and PR opener (GPT-6 Sol):
Shared branch worktree (Sol and Luna take turns):
Required tiers / OS / devices / servers:
Exact check commands (from existing project config):
Existing authorization for commits, installs, downloads, interop, push/PR:
Resource lease (heavy job; GPU runs go through Sol boundary; RAM/VRAM snapshot if applicable):
Shared-file reservations and dependent work orders:
CCRs / unresolved decisions:
Handoff destination and expected evidence:
```

Before dispatch, confirm all writable paths belong to that role and stage. A tests-only order cannot confer production ownership, and an implementation order cannot confer test ownership. Explicit coordinator reservations are required for shared/main-track files.

Example behavior for a history work order: `T-HIS-002` proves that a run created exactly 24 hours ago is unavailable using an injected clock; it also covers just-before/at/after the boundary. Sol supplies the test; Luna implements retention in the assigned files; Sol verifies it without renewing the creation timestamp. The coordinator supplies actual revisions, paths, and commands once the scaffold exists.
