import random

import pytest

from src.errors import AmmeterConnectionError, AmmeterResponseError, AmmeterTimeoutError, ConfigError
from src.sampling import Sampler, SamplingPlan


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def run_with_latencies(latencies, plan, error=None, **kwargs):
    """Runs the sampler on a fake clock where each reading takes the next latency from the list."""
    clock = FakeClock()
    latencies = iter(latencies)

    def measure():
        clock.now += next(latencies)
        if error:
            raise error
        return 1.0

    return Sampler(clock.time, clock.sleep).run(plan, measure, **kwargs), clock


def run_with_outcomes(outcomes, plan, **kwargs):
    """Runs the sampler on a fake clock; each reading returns the next value or raises the next error."""
    clock = FakeClock()
    outcomes = iter(outcomes)

    def measure():
        outcome = next(outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return Sampler(clock.time, clock.sleep).run(plan, measure, **kwargs)


def test_plan_from_any_two_values():
    """A plan can be given as any two of count, duration and frequency, and the third is worked out.
    With a duration, the count uses all of it but never runs past it, and the stored plan keeps the exact values."""
    for count, duration, frequency, expected in [
        (10, None, 5, (10, 5.0)),
        (None, 2, 5, (10, 5.0)),
        (10, 2, None, (10, 5.0)),
        (10, 2, 5, (10, 5.0)),
        (None, 2.3, 10, (23, 10.0)),  # 2.3 * 10 is 22.999... in floating point
        (10, 3, None, (10, 10 / 3)),
    ]:
        plan = SamplingPlan.from_config(count, duration, frequency)
        assert (plan.count, plan.frequency_hz) == expected

    for step in range(1, 101):
        duration = step * 0.05
        for frequency in (1, 3, 7, 10, 33, 50):
            if duration * frequency < 1:
                continue
            plan = SamplingPlan.from_config(None, duration, frequency)
            assert plan.duration_s <= duration + 1e-9  # never past the duration...
            assert (plan.count + 1) / frequency > duration + 1e-9  # ...while using all of it
            assert plan.to_dict()["total_duration_seconds"] == plan.duration_s
    assert SamplingPlan.from_config(5, 2, None).to_dict()["sampling_frequency_hz"] == 2.5


@pytest.mark.parametrize("count, duration, frequency, message", [
    (10, None, None, "at least two"),
    (None, None, None, "at least two"),
    (10, 2, 10, "take 1 s, not 2 s"),
    (10, 1.15, 10, "take 1 s, not 1.15 s"),  # 15% off
    (10, 1.05, 10, "take 1 s, not 1.05 s"),
    (10, 1, True, "positive number"),
    (-1, None, 5, "positive number"),
    ("ten", None, 5, "positive number"),
    (True, None, 5, "positive number"),
    (10, None, True, "positive number"),
    (10, None, 0, "positive number"),
    (2.5, None, 5, "whole number"),
    (None, 0.1, 5, "not even one"),
    (None, float("inf"), 10, "positive number"),
    (10, None, float("nan"), "positive number"),
    (float("inf"), None, 5, "positive number"),
])
def test_invalid_plans(count, duration, frequency, message):
    """Plans that can't work are rejected with a clear ConfigError: missing, negative, infinite, NaN, text or true
    values, fractional counts, durations too short for one reading, and a count that doesn't fit the duration
    and frequency."""
    with pytest.raises(ConfigError, match=message):
        SamplingPlan.from_config(count, duration, frequency)


def test_readings_follow_the_schedule():
    """With a fast ammeter every reading starts exactly when its slot opens, with no delay.
    Failed readings keep their response time and don't add any wait."""
    result, _ = run_with_latencies([0.01] * 5, SamplingPlan(5, 10))
    assert [round(s.time_s, 9) for s in result.samples] == [0, 0.1, 0.2, 0.3, 0.4]
    assert all(s.lag_s == pytest.approx(0, abs=1e-9) for s in result.samples)
    assert all(s.latency_s == pytest.approx(0.01) for s in result.samples)
    assert result.missed == 0

    result, _ = run_with_latencies([0.05] * 4, SamplingPlan(4, 10), error=AmmeterTimeoutError("slow"))
    assert [round(s.latency_s, 9) for s in result.samples] == [0.05] * 4  # failed readings keep their time
    assert [round(s.time_s, 9) for s in result.samples] == [0, 0.1, 0.2, 0.3]  # and cost no extra wait


def test_late_readings_skip_the_slots_they_ran_over():
    """A reading that runs past the next slot makes the sampler skip that slot and count it as missed, instead of
    firing readings back to back to catch up. A slot that is still open, even by half a millisecond, is used."""
    result, _ = run_with_latencies([0.17] * 4, SamplingPlan(4, 10))
    assert [s.index for s in result.samples] == [0, 1, 3]
    assert [round(s.time_s, 9) for s in result.samples] == [0, 0.17, 0.34]
    assert [round(s.lag_s, 9) for s in result.samples] == [0, 0.07, 0.04]
    assert [round(s.latency_s, 9) for s in result.samples] == [0.17] * 3
    assert result.missed == 1

    result, _ = run_with_latencies([0.01, 0.35, 0.01, 0.01, 0.01], SamplingPlan(5, 10))  # one long stall
    assert [s.index for s in result.samples] == [0, 1, 4]
    assert [round(s.time_s, 9) for s in result.samples] == [0, 0.1, 0.45]
    assert result.missed == 2

    result, _ = run_with_latencies([0.1995, 0.01, 0.01, 0.01], SamplingPlan(4, 10))  # late, but its slot is still open
    assert [s.index for s in result.samples] == [0, 1, 2, 3]


def test_duration_is_a_hard_deadline():
    """1 s at 10 Hz against an ammeter that takes 1 s per reading: one reading, nine missed slots, and the run
    ends after 1 s instead of 10."""
    result, clock = run_with_latencies([1.0] * 10, SamplingPlan.from_config(None, 1, 10))
    assert len(result.samples) == 1
    assert result.missed == 9
    assert clock.now == pytest.approx(1.0)


@pytest.mark.parametrize("seed", range(20))
def test_every_reading_stays_in_its_own_slot(seed):
    """Property test over 20 seeded runs with random response times: each slot is used at most once, no reading
    starts outside its slot, and a slot is only skipped when the reading before it really ran past it."""
    rng = random.Random(seed)
    plan = SamplingPlan(40, 10)
    result, _ = run_with_latencies([rng.choice([0.001, 0.05, 0.15, 0.4, 1.3]) for _ in range(40)], plan)
    samples = result.samples

    indices = [s.index for s in samples]
    assert indices == sorted(set(indices))
    assert len(samples) + result.missed == plan.count
    for s in samples:
        assert s.index / 10 - 1e-9 <= s.time_s < (s.index + 1) / 10
    # a slot is only skipped when the reading before it was still running when the slot ended
    for slot in set(range(plan.count)) - set(indices):
        before = [s for s in samples if s.index < slot]
        assert before and before[-1].time_s + before[-1].latency_s >= (slot + 1) / 10 - 1e-9


def test_failed_readings_are_kept_but_bugs_are_not_hidden():
    """A reading that fails with an ammeter error is kept, with its error, and the run goes on.
    A bug in the code (ValueError, TypeError) is raised instead of being recorded as a failed reading."""
    samples = run_with_outcomes([1.0, AmmeterTimeoutError("too slow"), 3.0], SamplingPlan(3, 10)).samples
    assert [s.value for s in samples] == [1.0, None, 3.0]
    assert samples[1].error == "AmmeterTimeoutError: too slow"

    for bug in (ValueError("a bug in the client"), TypeError("another bug")):
        with pytest.raises(type(bug)):
            run_with_outcomes([bug] * 3, SamplingPlan(3, 10))


def test_stops_after_too_many_failures_in_a_row():
    """The run stops after exactly N failures in a row, of any ammeter error type.
    Failures that aren't in a row, or a limit of 0, never stop it."""
    for limit in (1, 2, 3, 4):
        for error in (AmmeterConnectionError, AmmeterTimeoutError, AmmeterResponseError):
            result = run_with_outcomes([error("bad")] * 50, SamplingPlan(50, 10), max_consecutive_errors=limit)
            assert len(result.samples) == limit
            assert result.stop_reason == f"stopped after {limit} failed measurements in a row"
            assert result.missed == 0

    scattered = run_with_outcomes([AmmeterTimeoutError("slow"), 1.0] * 10, SamplingPlan(20, 10),
                                  max_consecutive_errors=2)
    assert (len(scattered.samples), scattered.stop_reason) == (20, None)
    pairs = run_with_outcomes([AmmeterTimeoutError("slow"), AmmeterTimeoutError("slow"), 1.0] * 7, SamplingPlan(21, 10),
                              max_consecutive_errors=3)
    assert (len(pairs.samples), pairs.stop_reason) == (21, None)
    never = run_with_outcomes([AmmeterConnectionError("refused")] * 20, SamplingPlan(20, 10), max_consecutive_errors=0)
    assert (len(never.samples), never.stop_reason) == (20, None)


def test_ctrl_c_keeps_what_was_collected():
    """Ctrl-C ends the run as 'interrupted' and keeps the readings taken so far."""
    result = run_with_outcomes([1.0, 1.0, KeyboardInterrupt()] + [1.0] * 7, SamplingPlan(10, 10))
    assert len(result.samples) == 2
    assert result.stop_reason == "interrupted"
