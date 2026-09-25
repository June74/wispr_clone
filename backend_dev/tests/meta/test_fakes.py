"""T-FAKE contracts for Luna's shared, deterministic test doubles."""

import json
from pathlib import Path

import pytest


def test_T_FAKE_001_clock_orders_callbacks_and_never_goes_backwards() -> None:
    from fakes.clock import FakeClock

    clock = FakeClock(start=10.0)
    fired: list[tuple[str, float]] = []
    assert clock.now() == 10.0
    clock.call_at(12.0, lambda: fired.append(("first", clock.now())))
    clock.call_later(2.0, lambda: fired.append(("second", clock.now())))
    cancelled = clock.call_at(11.0, lambda: fired.append(("cancelled", clock.now())))
    cancelled.cancel()

    def nested() -> None:
        fired.append(("nested-parent", clock.now()))
        clock.call_later(0.0, lambda: fired.append(("nested-child", clock.now())))
        clock.call_later(0.5, lambda: fired.append(("later-child", clock.now())))

    clock.call_at(12.0, nested)
    clock.advance(2.5)
    assert fired == [
        ("first", 12.0),
        ("second", 12.0),
        ("nested-parent", 12.0),
        ("nested-child", 12.0),
        ("later-child", 12.5),
    ]
    assert clock.now() == 12.5
    with pytest.raises(ValueError):
        clock.advance(-0.1)
    assert clock.now() == 12.5


def test_T_FAKE_001_clock_past_due_zero_advance_and_callback_cancellation() -> None:
    from fakes.clock import FakeClock

    clock = FakeClock(start=10.0)
    fired: list[tuple[str, float]] = []
    later = clock.call_at(11.0, lambda: fired.append(("cancelled", clock.now())))

    def cancel_later() -> None:
        fired.append(("canceller", clock.now()))
        later.cancel()
        clock.call_at(9.0, lambda: fired.append(("nested-past", clock.now())))

    clock.call_at(9.0, cancel_later)
    clock.call_at(10.0, lambda: fired.append(("due-now", clock.now())))
    clock.advance(0)
    assert fired == [
        ("canceller", 10.0),
        ("nested-past", 10.0),
        ("due-now", 10.0),
    ]
    assert clock.now() == 10.0
    clock.advance(1.0)
    assert clock.now() == 11.0
    assert len(fired) == 3


def test_T_FAKE_002_event_sink_records_json_data_in_order() -> None:
    from fakes.events import FakeEventSink

    sink = FakeEventSink()
    first = {
        "name": "run:state",
        "run_id": "run-1",
        "version": 1,
        "status": "recording",
    }
    second = {"name": "history:changed", "run_ids": ["run-1"], "reason": "updated"}
    third = {"name": "run:state", "run_id": "run-1", "version": 2, "status": "done"}
    for event in (first, second, third):
        sink.publish(event)
    assert sink.events == [first, second, third]
    assert sink.by_name("run:state") == [first, third]
    assert sink.by_name("missing") == []
    assert json.loads(json.dumps(sink.events, allow_nan=False)) == sink.events

    invalid = [
        {"name": "run:state", "extra": ("tuple",)},
        {"name": "run:state", "extra": {1: "integer key"}},
        {"name": "audio:level", "bands": [float("nan")]},
        {"name": "run:state", "extra": object()},
    ]
    for event in invalid:
        with pytest.raises((TypeError, ValueError)):
            sink.publish(event)
    assert sink.events == [first, second, third]


@pytest.mark.parametrize("payload", [[], "run:state", 3, None])
def test_T_FAKE_002_event_sink_rejects_non_event_json_values(payload: object) -> None:
    from fakes.events import FakeEventSink

    sink = FakeEventSink()
    with pytest.raises((TypeError, ValueError)):
        sink.publish(payload)  # type: ignore[arg-type]
    assert sink.events == []


def test_T_FAKE_003_ids_are_readable_per_prefix_and_per_instance() -> None:
    from fakes.ids import FakeIdFactory

    first = FakeIdFactory()
    second = FakeIdFactory()
    assert [first.new("run"), first.new("req"), first.new("run"), first.new("req")] == [
        "run-1",
        "req-1",
        "run-2",
        "req-2",
    ]
    assert second.new("run") == "run-1"
    assert second.new("req") == "req-1"
    assert first.new("run") == "run-3"


def test_T_FAKE_004_harness_runs_both_and_skips_unavailable_real(
    pytester: pytest.Pytester,
) -> None:
    tests_dir = Path(__file__).resolve().parents[1]
    pytester.makeini(
        """[pytest]
addopts = --strict-markers
markers =
    adapter(dist): project adapter
"""
    )
    pytester.makeconftest(f"import sys\nsys.path.insert(0, {str(tests_dir)!r})\n")
    pytester.makepyfile(sample_real="def make_real():\n    return 'real'\n")
    pytester.makepyfile(
        test_sample="""
import pytest
from conformance.harness import implementation_params

@pytest.mark.parametrize("make", implementation_params(
    "sample", lambda: "fake", "sample_real", "make_real", "pytest"))
def test_same_case(make):
    assert make() in {"fake", "real"}

@pytest.mark.parametrize("make", implementation_params(
    "missing", lambda: "fake", "nonexistent_synthetic_adapter_71",
    "make_real", "pytest"))
def test_unavailable_case(make):
    assert make() == "fake"
"""
    )
    result = pytester.runpytest_subprocess("-v", "test_sample.py", "-rs")
    result.assert_outcomes(passed=3, skipped=1)
    output = result.stdout.str()
    for case_id in ("sample[fake]", "sample[real]", "missing[fake]", "missing[real]"):
        assert case_id in output
    assert "nonexistent_synthetic_adapter_71" in output
