import math
import time
from dataclasses import dataclass, field
from typing import Callable

from src.errors import AmmeterError, ConfigError


@dataclass(frozen=True)
class SamplingPlan:
    count: int
    frequency_hz: float

    @property
    def duration_s(self) -> float:
        return self.count / self.frequency_hz

    @classmethod
    def from_config(cls, count=None, duration_s=None, frequency_hz=None) -> "SamplingPlan":
        """Builds a plan from any two of the three values, since count = duration * frequency."""
        given = {
            "measurements_count": count,
            "total_duration_seconds": duration_s,
            "sampling_frequency_hz": frequency_hz,
        }
        given = {key: value for key, value in given.items() if value is not None}
        if len(given) < 2:
            raise ConfigError(
                "sampling: set at least two of measurements_count, total_duration_seconds, sampling_frequency_hz"
            )
        for key, value in given.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ConfigError(f"sampling: {key} must be a positive number, got {value!r}")
        if count is not None and count != int(count):
            raise ConfigError(f"sampling: measurements_count must be a whole number, got {count}")

        if frequency_hz is None:
            frequency_hz = count / duration_s
        elif count is None:
            count = math.floor(duration_s * frequency_hz + 1e-9)
            if count < 1:
                raise ConfigError(f"sampling: {duration_s} s at {frequency_hz} Hz is not even one measurement")
        elif duration_s is not None and not math.isclose(count, duration_s * frequency_hz, rel_tol=0.01):
            raise ConfigError(
                f"sampling: {count} measurements at {frequency_hz} Hz take {count / frequency_hz:g} s, not {duration_s} s"
            )
        return cls(int(count), float(frequency_hz))

    def to_dict(self) -> dict:
        return {
            "measurements_count": self.count,
            "sampling_frequency_hz": self.frequency_hz,
            "total_duration_seconds": self.duration_s,
        }


@dataclass
class Sample:
    index: int  # the time slot it was taken in
    time_s: float  # when the request started, relative to the start of the run
    lag_s: float  # how much later than its slot start it began
    latency_s: float
    value: float | None = None
    error: str | None = None


@dataclass
class SamplingResult:
    samples: list[Sample] = field(default_factory=list)
    missed: int = 0
    stop_reason: str | None = None


class Sampler:
    """Reading i belongs to the time slot [start + i/f, start + (i+1)/f).

    A reading starts when its slot begins, or right after the previous reading if that one ran late. When a slot has
    already passed, it is skipped and counted as missed: there are no catch-up bursts, and no reading starts after
    the planned duration. A reading that is in progress at the end may still finish, within the client's timeout.
    """

    def __init__(self, clock: Callable[[], float] = time.perf_counter, sleep: Callable[[float], None] = time.sleep):
        self._clock = clock
        self._sleep = sleep

    def run(self, plan: SamplingPlan, measure: Callable[[], float],
            max_consecutive_errors: int | None = None) -> SamplingResult:
        result = SamplingResult()
        consecutive_errors = 0
        start = self._clock()
        try:
            for i in range(plan.count):
                slot_start = start + i / plan.frequency_hz
                slot_end = start + (i + 1) / plan.frequency_hz
                now = self._clock()
                if now < slot_start:
                    self._sleep(slot_start - now)
                    now = self._clock()
                if now >= slot_end:
                    result.missed += 1
                    continue

                sample = Sample(index=i, time_s=now - start, lag_s=max(0.0, now - slot_start), latency_s=0.0)
                try:
                    sample.value = measure()
                    consecutive_errors = 0
                except AmmeterError as e:
                    sample.error = f"{type(e).__name__}: {e}"
                    consecutive_errors += 1
                sample.latency_s = self._clock() - now
                result.samples.append(sample)

                if max_consecutive_errors and consecutive_errors >= max_consecutive_errors:
                    result.stop_reason = f"stopped after {consecutive_errors} failed measurements in a row"
                    break
        except KeyboardInterrupt:
            result.stop_reason = "interrupted"
        return result
