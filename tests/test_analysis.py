import math
import random
import statistics

import pytest

from src.analysis import compare, consistency, evaluate, summarize, verdict
from src.sampling import Sample, SamplingPlan
from src.settings import Acceptance, AmmeterSpec
from tests.helpers import ENTES, entes_readings

LIMITS = Acceptance()
CIRCUTOR = AmmeterSpec("circutor", 5003, "X", expected_min=0.001, expected_max=0.1)


def samples_at(values, interval=0.1):
    return [Sample(i, i * interval, 0.0, 0.001, value=v) for i, v in enumerate(values)]


def checks_for(values, spec=ENTES, error_rate=0.0, limits=LIMITS, planned=None):
    samples = samples_at(values)
    timing = consistency(samples, SamplingPlan(planned or len(values), 10))
    return {c["name"]: c for c in evaluate(values, error_rate, timing, spec, limits)}


def test_summary_statistics():
    """Mean, median, standard deviation, min, max, CV, geometric mean, quartiles and outliers, against values worked
    out by hand. The bootstrap intervals are the seeded 2.5th and 97.5th percentiles and stay inside the data."""
    stats = summarize([1, 2, 3, 4, 100])
    assert stats["count"] == 5
    assert stats["mean"] == 22
    assert stats["median"] == 3
    assert stats["std_dev"] == pytest.approx(43.6176, rel=1e-5)  # sqrt(7610 / 4)
    assert (stats["min"], stats["max"]) == (1, 100)
    assert stats["cv"] == pytest.approx(43.6176 / 22, rel=1e-5)
    assert stats["geo_mean"] == pytest.approx(2400 ** 0.2)
    assert stats["outliers"] == 1
    assert summarize([1, 2, 3, 4])["median"] == 2.5
    assert summarize([1, 2, 3, 4, 5, 6, 7, 8, 16])["outliers"] == 1  # 16 is past q3 + 1.5 IQR (13)
    low = summarize([1, 9, 10, 11, 12, 13, 14, 15, 16])
    assert (low["q1"], low["q3"], low["outliers"]) == (10, 14, 1)  # 1 is below q1 - 1.5 IQR (4)

    values = entes_readings(30)
    rng = random.Random(0)
    means = sorted(statistics.fmean(rng.choices(values, k=30)) for _ in range(1000))
    assert summarize(values)["ci95"] == [means[25], means[974]]  # 2.5th and 97.5th of 1000 seeded resamples
    assert summarize(values)["ci95"] == summarize(values)["ci95"]

    stats = summarize([0.02] * 30 + [50.0])  # long tail, like Greenlee
    low, high = stats["ci95"]
    assert 0.02 <= low < high <= 50.0
    cv_low, cv_high = stats["cv_ci95"]
    assert 0 <= cv_low <= stats["cv"] <= cv_high


@pytest.mark.parametrize("values, expected", [
    ([], {"count": 0}),
    ([5.0], {"count": 1, "mean": 5.0, "std_dev": 0.0, "ci95": [5.0, 5.0], "cv_ci95": None}),
    ([0.0, 0.0], {"count": 2, "cv": None, "cv_ci95": None, "geo_mean": None}),
])
def test_summary_edge_cases(values, expected):
    """No readings, one reading, or readings of 0 give sensible values (or None) instead of a crash."""
    stats = summarize(values)
    for key, value in expected.items():
        assert stats[key] == value


def test_timing_statistics():
    """Achieved rate, interval jitter, delay and response times against samples with known times. A missed slot
    isn't counted as jitter, failed readings count as taken, and p95 is taken at the right rank."""
    steady = consistency(samples_at([1.0, 2.0] * 20), SamplingPlan(40, 10))
    assert steady["achieved_hz"] == pytest.approx(10)
    assert (steady["taken"], steady["planned"]) == (40, 40)
    assert steady["interval_jitter_ms"] == pytest.approx(0, abs=1e-6)
    assert abs(steady["drift_t"]) < 2

    gap = [Sample(i, i * 0.1, 0.0, 0.001, value=1.0 + i % 2) for i in range(10) if i not in (3, 4)]
    timing = consistency(gap, SamplingPlan(10, 10))
    assert timing["achieved_hz"] == pytest.approx(8)
    assert timing["interval_jitter_ms"] == pytest.approx(0, abs=1e-6)  # the gap is not counted as jitter

    samples = [
        Sample(0, 0.00, 0.00, 0.001, value=1.0),
        Sample(1, 0.10, 0.00, 0.002, value=2.0),
        Sample(2, 0.21, 0.01, 0.003, error="AmmeterTimeoutError: slow"),
        Sample(3, 0.30, 0.00, 0.004, value=4.0),
        Sample(5, 0.52, 0.02, 0.010, value=5.0),  # slot 4 was missed
        Sample(6, 0.60, 0.00, 0.005, value=6.0),
    ]
    timing = consistency(samples, SamplingPlan(10, 10))
    assert (timing["taken"], timing["planned"]) == (6, 10)
    assert timing["achieved_hz"] == pytest.approx(6.0)  # failed readings were taken, too
    assert timing["interval_jitter_ms"] == pytest.approx(statistics.stdev([0.10, 0.11, 0.09, 0.08]) * 1000)
    assert timing["max_lag_ms"] == pytest.approx(20)
    assert timing["latency_mean_ms"] == pytest.approx(25 / 6)
    assert timing["latency_p95_ms"] == pytest.approx(10)
    assert timing["latency_max_ms"] == pytest.approx(10)

    three = [Sample(0, 0.0, 0.0, 0.001, value=1.0), Sample(1, 0.1, 0.0, 0.001, value=2.0),
             Sample(2, 0.22, 0.03, 0.001, error="AmmeterTimeoutError: slow")]
    timing = consistency(three, SamplingPlan(3, 10))
    assert timing["interval_jitter_ms"] == pytest.approx(statistics.stdev([0.1, 0.12]) * 1000)
    assert timing["max_lag_ms"] == pytest.approx(30)  # a failed reading's delay counts, too
    twenty = [Sample(i, i * 0.1, 0.0, (i + 1) / 1000, value=1.0) for i in range(20)]
    assert consistency(twenty, SamplingPlan(20, 10))["latency_p95_ms"] == pytest.approx(19)


def test_drift_is_measured_and_any_trend_fails_the_check():
    """The drift figure and its t value match a linear regression worked out in the test, also for short runs.
    Any trend, rising, falling or an exact straight line, fails the no_drift check."""
    values = [10 + 0.1 * i + (0.05 if i % 2 else -0.05) for i in range(40)]
    times = [i * 0.1 for i in range(40)]
    timing = consistency(samples_at(values), SamplingPlan(40, 10))
    fit = statistics.linear_regression(times, values)
    residuals = [v - fit.intercept - fit.slope * t for t, v in zip(times, values)]
    t_mean = statistics.fmean(times)
    slope_se = (sum(r * r for r in residuals) / 38 / sum((t - t_mean) ** 2 for t in times)) ** 0.5
    assert timing["drift_pct"] == pytest.approx(100 * fit.slope * 3.9 / statistics.fmean(values))
    assert timing["drift_t"] == pytest.approx(fit.slope / slope_se)
    mirrored = consistency(samples_at([-v for v in values]), SamplingPlan(40, 10))  # a reversed clamp
    assert mirrored["drift_pct"] == pytest.approx(timing["drift_pct"])  # same relative trend

    short = consistency(samples_at([10.0, 12.0, 11.0, 13.0, 12.0]), SamplingPlan(5, 10))
    assert short["drift_pct"] is not None and short["drift_t"] is not None  # from 4 readings on

    rising = [10 + i * 0.5 + (0.2 if i % 2 else -0.2) for i in range(40)]
    timing = consistency(samples_at(rising), SamplingPlan(40, 10))
    assert timing["drift_pct"] > 50
    assert timing["drift_t"] > 5

    for trend in [
        [2.0 * i + 1 for i in range(40)],  # exact in floating point: no noise at all
        [10 + 0.1 * i for i in range(40)],  # tiny rounding noise
        [100 - 2 * i for i in range(40)],
        [100 - 2 * i + (1 if i % 2 else -1) for i in range(40)],
        [20 + 2 * i + (1 if i % 2 else -1) for i in range(40)],
    ]:
        assert not checks_for(trend)["no_drift"]["passed"]


def test_good_run_passes_every_check():
    """50 readings drawn the way the ENTES emulator draws them pass all six checks, none skipped.
    This guards against false alarms."""
    checks = checks_for(entes_readings(50))
    assert list(checks) == ["values_in_range", "error_rate", "sampling_rate", "not_stuck", "matches_model", "no_drift"]
    assert all(c["passed"] and not c["skipped"] for c in checks.values())


def test_stuck_readings_fail():
    """Identical readings in a row fail not_stuck, even when the stuck value is exactly the expected one.
    Two in a row are allowed and three are not, wherever they are in the run."""
    checks = checks_for([5.0] * 50)
    assert checks["values_in_range"]["passed"]
    assert not checks["not_stuck"]["passed"]
    assert not checks["matches_model"]["passed"]
    assert verdict(list(checks.values()), 50, None) == "FAIL"

    checks = checks_for([55.51] * 50)  # stuck at exactly the expected geometric mean
    assert checks["matches_model"]["passed"]
    assert not checks["not_stuck"]["passed"]

    values = entes_readings(40)
    values[10] = values[11]
    assert checks_for(values)["not_stuck"]["passed"]  # two identical readings in a row are fine...
    values[12] = values[11]
    assert not checks_for(values)["not_stuck"]["passed"]  # ...three are not

    values = entes_readings(40)
    assert not checks_for(values[:-3] + [values[-1]] * 3)["not_stuck"]["passed"]  # frozen at the very end
    assert checks_for([v for v in entes_readings(20) for _ in (0, 1)])["not_stuck"]["passed"]  # pairs only
    assert checks_for([0.0291 + i * 0.0001 for i in range(40)], spec=CIRCUTOR)["not_stuck"]["passed"]
    assert "identical readings: 5" in checks_for(values[:30] + [values[0]] * 5)["not_stuck"]["detail"]


def test_calibration_errors_fail_the_model_check():
    """Readings scaled by 0.5 or by 1.8 fail matches_model, so the check works in both directions, and the
    detail shows the geometric mean. Zero readings, which have no log, are left out of the z value."""
    values = entes_readings(50)
    low = checks_for([v * 0.5 for v in values])["matches_model"]
    assert not low["passed"]
    assert "z = -" in low["detail"]
    assert not checks_for([v * 1.8 for v in values])["matches_model"]["passed"]
    detail = checks_for(values)["matches_model"]["detail"]
    assert f"geometric mean {statistics.geometric_mean(values):.4g} A" in detail

    logs = [math.log(v) for v in values[:40]]
    z = (statistics.fmean(logs) - math.log(ENTES.expected_geo_mean)) / (ENTES.expected_log_std / math.sqrt(40))
    with_zeros = checks_for(values[:40] + [0.0] * 10)["matches_model"]["detail"]
    assert f"z = {z:+.2f}," in with_zeros  # zero readings have no log, so they don't count


def test_limits_are_exact():
    """Every acceptance limit is exact at its edge: value range, error rate, sampling rate and the minimum
    readings for the model and drift checks. The limits set in the config are the ones used."""
    values = entes_readings(30)
    for bad in (4.99, 200.01):
        assert not checks_for([bad] + values[1:])["values_in_range"]["passed"]
    assert checks_for([5.0, 200.0] + values[2:])["values_in_range"]["passed"]
    assert "3 of 30 outside" in checks_for([1.0, 2.0, 300.0] + values[3:])["values_in_range"]["detail"]
    assert "1 of 30 outside" in checks_for(values[:5] + [5000.0] + values[6:])["values_in_range"]["detail"]

    assert checks_for(values, error_rate=0.05)["error_rate"]["passed"]
    assert not checks_for(values, error_rate=0.0501)["error_rate"]["passed"]
    assert not checks_for(values, error_rate=0.07)["error_rate"]["passed"]
    assert not checks_for(values, error_rate=0.2)["error_rate"]["passed"]

    for taken, planned, passed in ((50, 50, True), (45, 50, True), (44, 50, False), (90, 100, True), (89, 100, False)):
        check = checks_for(entes_readings(taken), planned=planned)["sampling_rate"]
        assert check["passed"] is passed
        assert f"{taken} of {planned} planned readings taken" in check["detail"]
    timing = consistency([], SamplingPlan(50, 10))
    assert not {c["name"]: c for c in evaluate([], 0.0, timing, ENTES, LIMITS)}["sampling_rate"]["passed"]

    for n, model_skipped, drift_skipped in ((5, True, True), (9, True, True), (10, False, True), (20, False, True),
                                            (29, False, True), (30, False, False)):
        checks = checks_for(entes_readings(n))
        assert checks["matches_model"]["skipped"] is model_skipped
        assert checks["no_drift"]["skipped"] is drift_skipped

    t = abs(consistency(samples_at(values), SamplingPlan(30, 10))["drift_t"])  # the configured limits are used
    assert not checks_for(values, limits=Acceptance(max_drift_t=t * 0.9))["no_drift"]["passed"]
    assert checks_for(values, limits=Acceptance(max_drift_t=t * 1.1))["no_drift"]["passed"]
    four = values[:10] + [values[10]] * 4 + values[14:]
    assert not checks_for(four)["not_stuck"]["passed"]
    assert checks_for(four, limits=Acceptance(stuck_after=5))["not_stuck"]["passed"]


def test_verdict_rules():
    """PASS only if every check passes: any single failed check, or a stop after repeated failures, is FAIL.
    No valid reading at all is ERROR, and Ctrl-C is INTERRUPTED."""
    passing = [{"name": "error_rate", "passed": True, "skipped": False, "detail": ""}]
    assert verdict(passing, 10, "stopped after 5 failed measurements in a row") == "FAIL"
    assert verdict(passing, 0, None) == "ERROR"
    assert verdict(passing, 0, "interrupted") == "INTERRUPTED"
    assert verdict([], 0, "stopped after 5 failed measurements in a row") == "ERROR"
    assert verdict([], 10, "interrupted") == "INTERRUPTED"

    names = ["values_in_range", "error_rate", "sampling_rate", "not_stuck", "matches_model", "no_drift"]
    assert verdict([{"name": n, "passed": True, "skipped": False, "detail": ""} for n in names], 10, None) == "PASS"
    for failing in names:  # any one failed check fails the run
        checks = [{"name": n, "passed": n != failing, "skipped": False, "detail": ""} for n in names]
        assert verdict(checks, 10, None) == "FAIL"


def _interval_run(name, cv, low, high, error_rate=0.0):
    return {"run_id": name, "status": "PASS", "ammeter": {"name": name, "expected_geo_mean": None},
            "statistics": {"count": 30, "cv": cv, "cv_ci95": [low, high]}, "error_rate": error_rate}


def _run(name, values, status="PASS", error_rate=0.0):
    return {
        "run_id": f"run_{name}",
        "status": status,
        "ammeter": {"name": name, "expected_geo_mean": None},
        "statistics": summarize(values),
        "error_rate": error_rate,
    }


def test_clearly_most_precise_run_wins():
    """A run with a clearly lower CV wins. Bias is relative to the expected geometric mean, CVs and error rates are
    compared exactly, and runs with the same CV are listed with the fewest errors first."""
    steady = _run("steady", [99, 100, 101] * 20)
    noisy = _run("noisy", [50, 100, 150] * 20)
    result = compare([noisy, steady])
    assert [row["ammeter"] for row in result["rows"]] == ["steady", "noisy"]
    assert result["most_reliable"] == "steady"
    assert result["conclusion"] is None

    base = entes_readings(50)
    high, exact = _run("high", [v * 1.02 for v in base]), _run("exact", base, error_rate=0.03)
    for run in (high, exact):
        run["ammeter"]["expected_geo_mean"] = statistics.geometric_mean(base)
    rows = {r["ammeter"]: r for r in compare([high, exact])["rows"]}
    assert rows["high"]["bias"] == pytest.approx(0.02)
    assert rows["exact"]["bias"] == pytest.approx(0, abs=1e-12)

    fewer, more = _run("fewer", base, error_rate=0.01), _run("more", base, error_rate=0.03)
    assert [r["ammeter"] for r in compare([more, fewer])["rows"]] == ["fewer", "more"]  # same CV: fewer errors first
    close = compare([_interval_run("a", 0.5014, 0.4, 0.6), _interval_run("b", 0.5012, 0.4, 0.6, error_rate=0.03)])
    assert [r["ammeter"] for r in close["rows"]] == ["b", "a"]  # CVs are compared exactly, not rounded
    same_cv = compare([_interval_run("x", 0.3, 0.2, 0.4, error_rate=0.014),
                       _interval_run("y", 0.3, 0.2, 0.4, error_rate=0.012)])
    assert [r["error_rate"] for r in same_cv["rows"]] == [0.012, 0.014]  # and so are error rates


def test_only_passing_runs_with_enough_readings_are_ranked():
    """Runs that didn't PASS, have fewer than the minimum readings, or have no CV are listed as not ranked, with
    the reason. A failed run with one reading and 90% errors used to win, because its CV was 0."""
    result = compare([_run("failed", [100.0], status="FAIL", error_rate=0.9), _run("good", [90, 100, 110] * 10)])
    assert result["most_reliable"] is None
    assert [row["ammeter"] for row in result["rows"]] == ["good"]
    assert result["not_ranked"][0]["reason"] == "status FAIL"
    assert "insufficient evidence" in result["conclusion"]

    for status in ("FAIL", "ERROR", "INTERRUPTED"):
        result = compare([_run("x", [99, 100, 101] * 15, status=status), _run("a", [90, 100, 110] * 15),
                          _run("b", [50, 100, 150] * 15)])
        assert [r["reason"] for r in result["not_ranked"]] == [f"status {status}"]
        assert result["most_reliable"] == "a"

    result = compare([_run("x", [], status="ERROR", error_rate=1.0), _run("y", [], status="ERROR", error_rate=1.0)])
    assert result["most_reliable"] is None
    assert result["rows"] == []
    assert len(result["not_ranked"]) == 2

    result = compare([_run("short", [99, 100, 101] * 3), _run("a", [90, 100, 110] * 10),
                      _run("b", [50, 100, 150] * 10)])
    assert [r["ammeter"] for r in result["not_ranked"]] == ["short"]
    assert "only 9 readings, 30 needed" in result["not_ranked"][0]["reason"]
    assert result["most_reliable"] == "a"

    r29, r30 = _run("r29", ([90, 100, 110] * 10)[:29]), _run("r30", [50, 100, 150] * 10)
    result = compare([r29, r30])
    assert [r["ammeter"] for r in result["not_ranked"]] == ["r29"]
    assert [r["ammeter"] for r in result["rows"]] == ["r30"]
    result = compare([r29, r30], min_readings=40)
    assert [r["reason"] for r in result["not_ranked"]] == ["only 29 readings, 40 needed", "only 30 readings, 40 needed"]

    result = compare([_run("zero", [0.0] * 30), _run("a", [90, 100, 110] * 10), _run("b", [50, 100, 150] * 10)])
    assert [r["reason"] for r in result["not_ranked"]] == ["precision can't be computed"]  # a mean of 0 has no CV
    assert result["most_reliable"] == "a"


def test_overlapping_precision_is_not_a_win():
    """When the CV intervals overlap, even just touching, there is no winner: the result is 'insufficient
    evidence' and names the tied runs. The size of the current alone can't decide."""
    result = compare([_run("first", entes_readings(50, seed=1)), _run("second", entes_readings(50, seed=2))])
    assert result["most_reliable"] is None
    assert set(result["tied"]) == {"first", "second"}
    assert "equally precise" in result["conclusion"]

    best = _run("best", [99, 100, 101] * 20)
    separate = _run("separate", [80, 100, 120] * 20)
    wide = _run("wide", [100.0] * 58 + [1000.0, 1000.0])  # high CV, but an interval reaching down to 0
    result = compare([best, separate, wide])
    assert [r["ammeter"] for r in result["rows"]] == ["best", "separate", "wide"]
    assert result["most_reliable"] is None
    assert result["tied"] == ["best", "wide"]

    small = _run("small", [0.009, 0.010, 0.011] * 10)  # same relative spread, currents 1000x apart
    large = _run("large", [9, 10, 11] * 10)
    rows = compare([small, large])["rows"]
    assert rows[0]["cv"] == pytest.approx(rows[1]["cv"])
    assert compare([small, large])["most_reliable"] is None

    touching = compare([_interval_run("low", 0.1, 0.05, 0.15), _interval_run("high", 0.2, 0.15, 0.25)])
    assert touching["most_reliable"] is None
