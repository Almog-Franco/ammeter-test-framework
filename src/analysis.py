import math
import random
import statistics

from src.sampling import Sample, SamplingPlan

MIN_READINGS_MODEL_CHECK = 10
MIN_READINGS_DRIFT_CHECK = 30


def summarize(values: list[float]) -> dict:
    n = len(values)
    if n == 0:
        return {"count": 0}
    mean = statistics.fmean(values)
    std = statistics.stdev(values) if n > 1 else 0.0
    q1, _, q3 = statistics.quantiles(values, n=4, method="inclusive") if n > 1 else (values[0],) * 3
    fence = 1.5 * (q3 - q1)
    return {
        "count": n,
        "mean": mean,
        "median": statistics.median(values),
        "std_dev": std,  # sample standard deviation (n - 1)
        "min": min(values),
        "max": max(values),
        "cv": std / mean if mean else None,
        "cv_ci95": bootstrap_ci(values, _cv) if n > 1 and mean else None,
        "geo_mean": statistics.geometric_mean(values) if min(values) > 0 else None,
        "ci95": bootstrap_ci(values),
        "q1": q1,
        "q3": q3,
        "outliers": sum(1 for v in values if v < q1 - fence or v > q3 + fence),
    }


def bootstrap_ci(values: list[float], statistic=statistics.fmean, resamples: int = 1000) -> list[float]:
    """95% confidence interval of a statistic (default: the mean) by resampling. Unlike mean ± 1.96 SE it
    doesn't assume normal data, which matters for Greenlee's long-tailed readings. Fixed seed, so reports
    are repeatable."""
    if len(values) < 2:
        return [statistic(values), statistic(values)] if values else []
    rng = random.Random(0)
    estimates = sorted(statistic(rng.choices(values, k=len(values))) for _ in range(resamples))
    return [estimates[int(0.025 * resamples)], estimates[int(0.975 * resamples) - 1]]


def _cv(values: list[float]) -> float:
    mean = math.fsum(values) / len(values)
    variance = math.fsum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance) / mean if mean else math.inf


def consistency(samples: list[Sample], plan: SamplingPlan) -> dict:
    """How steady the run was: timing of the requests, and whether the readings drift over time."""
    in_a_row = [(a, b) for a, b in zip(samples, samples[1:]) if b.index == a.index + 1]
    intervals = [b.time_s - a.time_s for a, b in in_a_row]
    latencies = sorted(s.latency_s for s in samples)
    result = {
        "planned": plan.count,
        "taken": len(samples),
        "requested_hz": plan.frequency_hz,
        "achieved_hz": len(samples) / plan.duration_s,
        "interval_jitter_ms": statistics.stdev(intervals) * 1000 if len(intervals) > 1 else 0.0,
        "max_lag_ms": max((s.lag_s for s in samples), default=0.0) * 1000,
        "latency_mean_ms": statistics.fmean(latencies) * 1000 if latencies else None,
        "latency_p95_ms": latencies[math.ceil(0.95 * len(latencies)) - 1] * 1000 if latencies else None,
        "latency_max_ms": latencies[-1] * 1000 if latencies else None,
        "drift_pct": None,
        "drift_t": None,
        "drift_exact": False,
    }

    valid = [(s.time_s, s.value) for s in samples if s.value is not None]
    if len(valid) >= 4 and valid[-1][0] > valid[0][0]:
        t, v = zip(*valid)
        fit = statistics.linear_regression(t, v)
        mean = statistics.fmean(v)
        if mean:
            result["drift_pct"] = 100 * fit.slope * (t[-1] - t[0]) / mean
        # t-statistic of the slope: how sure we can be that the readings really trend
        residual_ss = sum((vi - fit.intercept - fit.slope * ti) ** 2 for ti, vi in zip(t, v))
        t_mean = statistics.fmean(t)
        slope_se = math.sqrt(residual_ss / (len(v) - 2) / sum((ti - t_mean) ** 2 for ti in t))
        if slope_se > 0:
            result["drift_t"] = fit.slope / slope_se
        elif fit.slope != 0:
            result["drift_exact"] = True  # a perfect straight line: no noise at all around the trend
    return result


def count_out_of_range(values: list[float], low: float | None, high: float | None) -> int:
    if low is None or high is None:
        return 0
    return sum(1 for v in values if not low <= v <= high)


def longest_repeat(values: list[float]) -> int:
    """The longest run of identical consecutive readings."""
    longest = current = 1 if values else 0
    for a, b in zip(values, values[1:]):
        current = current + 1 if a == b else 1
        longest = max(longest, current)
    return longest


def model_z(values: list[float], spec) -> float | None:
    """How many standard errors the mean of log(readings) is from what the emulator's physics predicts.

    On a log scale the readings are close to normal, even Greenlee's long-tailed ones, so the limit behaves the
    same for every ammeter (see docs/DESIGN.md for the false-alarm rates).
    """
    if spec.expected_geo_mean is None or spec.expected_log_std is None:
        return None
    logs = [math.log(v) for v in values if v > 0]
    if len(logs) < MIN_READINGS_MODEL_CHECK:
        return None
    standard_error = spec.expected_log_std / math.sqrt(len(logs))
    return (statistics.fmean(logs) - math.log(spec.expected_geo_mean)) / standard_error


def evaluate(values, error_rate, timing, spec, acceptance) -> list[dict]:
    checks = []
    if spec.expected_min is not None and spec.expected_max is not None and values:
        bad = count_out_of_range(values, spec.expected_min, spec.expected_max)
        checks.append(_check("values_in_range", bad == 0,
                             f"{bad} of {len(values)} outside [{spec.expected_min:g}, {spec.expected_max:g}] A"))

    checks.append(_check("error_rate", error_rate <= acceptance.max_error_rate,
                         f"{error_rate:.1%} failed (limit {acceptance.max_error_rate:.0%})"))

    off = 1 - timing["achieved_hz"] / timing["requested_hz"]
    checks.append(_check("sampling_rate", off <= acceptance.max_frequency_error + 1e-9,
                         f"{timing['taken']} of {timing['planned']} planned readings taken, {timing['achieved_hz']:.3g} Hz "
                         f"for {timing['requested_hz']:g} Hz requested ({off:.1%} short, limit "
                         f"{acceptance.max_frequency_error:.0%})"))

    if values:
        longest = longest_repeat(values)
        checks.append(_check("not_stuck", longest < acceptance.stuck_after,
                             f"longest run of identical readings: {longest} (stuck from {acceptance.stuck_after})"))

    if spec.expected_geo_mean is not None:
        z = model_z(values, spec)
        if z is None:
            checks.append(_skip("matches_model", f"needs at least {MIN_READINGS_MODEL_CHECK} positive readings"))
        else:
            geo_mean = math.exp(statistics.fmean(math.log(v) for v in values if v > 0))
            checks.append(_check("matches_model", abs(z) <= acceptance.max_model_z,
                                 f"geometric mean {geo_mean:.4g} A, model {spec.expected_geo_mean:g} A "
                                 f"(z = {z:+.2f}, limit ±{acceptance.max_model_z:g})"))

    if len(values) < MIN_READINGS_DRIFT_CHECK:
        checks.append(_skip("no_drift", f"needs at least {MIN_READINGS_DRIFT_CHECK} readings"))
    elif timing["drift_exact"]:
        checks.append(_check("no_drift", False, "readings lie exactly on a sloped straight line"))
    elif timing["drift_t"] is not None:
        t = timing["drift_t"]
        checks.append(_check("no_drift", abs(t) < acceptance.max_drift_t,
                             f"{timing['drift_pct']:+.3g} % over the run (t = {t:+.2f}, limit ±{acceptance.max_drift_t:g})"))
    return checks


def verdict(checks: list[dict], valid_count: int, stop_reason: str | None) -> str:
    if stop_reason == "interrupted":
        return "INTERRUPTED"
    if valid_count == 0:
        return "ERROR"
    return "PASS" if all(c["passed"] for c in checks) and not stop_reason else "FAIL"


def compare(runs: list[dict], min_readings: int = 30) -> dict:
    """Finds the most precise ammeter (lowest CV) among runs that passed every check with enough readings.

    Range, errors, agreement with the model and drift are already pass/fail checks, so precision is what's left
    to compare. CV is relative, so ammeters whose currents differ by about 1000x can be compared. A winner is
    named only if its 95% interval of the CV doesn't overlap the others'; otherwise the evidence isn't enough.
    """
    rows, not_ranked = [], []
    for run in runs:
        stats = run["statistics"]
        geo_mean, expected = stats.get("geo_mean"), run["ammeter"].get("expected_geo_mean")
        row = {
            "ammeter": run["ammeter"]["name"],
            "run_id": run["run_id"],
            "status": run["status"],
            "count": stats["count"],
            "mean": stats.get("mean"),
            "median": stats.get("median"),
            "cv": stats.get("cv"),
            "cv_ci95": stats.get("cv_ci95"),
            "bias": geo_mean / expected - 1 if geo_mean is not None and expected else None,
            "error_rate": run["error_rate"],
        }
        if run["status"] != "PASS":
            not_ranked.append({**row, "reason": f"status {run['status']}"})
        elif stats["count"] < min_readings:
            not_ranked.append({**row, "reason": f"only {stats['count']} readings, {min_readings} needed"})
        elif row["cv"] is None or not row["cv_ci95"]:
            not_ranked.append({**row, "reason": "precision can't be computed"})
        else:
            rows.append(row)

    rows.sort(key=lambda r: (r["cv"], r["error_rate"]))
    result = {"rows": rows, "not_ranked": not_ranked, "min_readings": min_readings,
              "most_reliable": None, "tied": [], "conclusion": None}
    if len(rows) < 2:
        result["conclusion"] = (f"insufficient evidence: fewer than two runs passed every check with at least "
                                f"{min_readings} readings")
        return result
    best = rows[0]
    tied = [r["ammeter"] for r in rows if r["cv_ci95"][0] <= best["cv_ci95"][1]]
    if len(tied) == 1:
        result["most_reliable"] = best["ammeter"]
    else:
        result["tied"] = tied
        result["conclusion"] = (f"insufficient evidence: {', '.join(tied)} are equally precise within the "
                                f"uncertainty of their readings; more readings are needed to separate them")
    return result


def _check(name: str, passed: bool, detail: str) -> dict:
    return {"name": name, "passed": bool(passed), "skipped": False, "detail": detail}


def _skip(name: str, detail: str) -> dict:
    return {"name": name, "passed": True, "skipped": True, "detail": f"skipped: {detail}"}
