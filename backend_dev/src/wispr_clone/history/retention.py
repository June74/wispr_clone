"""Pure run-history retention rules."""

from collections.abc import Sequence

from wispr_clone.config import MAX_RETAINED_RUNS, RUN_RETENTION_SECONDS

MAX_RUNS: int = MAX_RETAINED_RUNS
RETENTION_SECONDS: int = RUN_RETENTION_SECONDS


def is_expired(created_at: float, now: float) -> bool:
    """Return whether a run reached its inclusive age limit."""
    return created_at <= now - RETENTION_SECONDS


def expires_at(created_at: float) -> float:
    """Return the exact instant at which a run expires."""
    return created_at + RETENTION_SECONDS


def runs_to_evict(created_ats_oldest_first: Sequence[float], incoming: int = 1) -> int:
    """Return how many oldest runs must leave room for incoming runs."""
    if incoming < 0:
        raise ValueError("incoming must not be negative")
    return max(0, len(created_ats_oldest_first) + incoming - MAX_RUNS)
