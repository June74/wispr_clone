"""Exact age and count boundaries for the pure retention rules."""

from wispr_clone.config import MAX_RETAINED_RUNS, RUN_RETENTION_SECONDS


def test_T_HIS_002_exact_age_boundary() -> None:
    from wispr_clone.history import retention

    assert retention.MAX_RUNS == MAX_RETAINED_RUNS == 10
    assert retention.RETENTION_SECONDS == RUN_RETENTION_SECONDS == 86_400
    assert retention.expires_at(100.0) == 86_500.0
    assert not retention.is_expired(100.0, 86_499.999)
    assert retention.is_expired(100.0, 86_500.0)
    assert retention.is_expired(100.0, 86_500.001)


def test_T_HIS_001_count_boundary() -> None:
    from wispr_clone.history import retention

    assert retention.runs_to_evict([float(n) for n in range(9)]) == 0
    assert retention.runs_to_evict([float(n) for n in range(10)]) == 1
    assert retention.runs_to_evict([float(n) for n in range(10)], incoming=3) == 3
