import os
import re
from dataclasses import replace
from pathlib import Path

from src.analysis import compare, consistency, evaluate, summarize, verdict
from src.report import comparison_report, run_report, runs_table
from src.sampling import Sample, SamplingPlan
from src.settings import METRICS, Acceptance, AmmeterSpec
from tests.helpers import ENTES, entes_readings

GOLDEN = Path(__file__).parent / "golden"


def _run(values, planned=None, missed=0, spec=ENTES, interval=0.1):
    planned = planned or len(values)
    samples = [Sample(i, i * interval, 0.0, 0.001, value=v) for i, v in enumerate(values)]
    timing = consistency(samples, SamplingPlan(planned, 1 / interval))
    checks = evaluate(values, 0.0, timing, spec, Acceptance())
    return {
        "run_id": "20261026T120000Z_entes_abc123",
        "status": verdict(checks, len(values), None),
        "ammeter": {"name": spec.name, "host": spec.host, "port": spec.port, "expected_geo_mean": spec.expected_geo_mean},
        "sampling": {"measurements_count": planned},
        "started_at": "2026-10-26T12:00:00+00:00",
        "stop_reason": None,
        "missed": missed,
        "statistics": summarize(values),
        "error_count": 0,
        "error_rate": 0.0,
        "errors": {},
        "consistency": timing,
        "checks": checks,
        "fault_injection": None,
    }


def test_run_report():
    """The run report shows missed readings, skipped checks, the stop reason, errors, fault injection and drift,
    and calls an exact straight line drift, not noise."""
    text = run_report(_run(entes_readings(20), planned=22, missed=2), list(METRICS))
    assert "20 valid readings of 22 planned, 0 failed, 2 missed" in text
    assert "| no_drift | SKIP | skipped: needs at least 30 readings |" in text
    assert "| matches_model | PASS |" in text
    assert "| Geometric mean |" in text

    run = _run(entes_readings(20))
    run.update(stop_reason="stopped after 5 failed measurements in a row", errors={"AmmeterTimeoutError": 5},
               error_count=5, fault_injection={"rates": {"timeout": 0.1}})
    text = run_report(run, list(METRICS))
    assert "stopped after 5 failed measurements in a row" in text
    assert "Errors: AmmeterTimeoutError x5" in text
    assert "Fault injection was on" in text

    text = run_report(_run([10.0 + i for i in range(40)]), list(METRICS))  # an exact line is drift, not noise
    assert "not significant" not in text
    assert "| no_drift | FAIL |" in text
    assert "## entes: FAIL" in text
    falling = run_report(_run([100.0 - 2 * i for i in range(40)], interval=1.0), list(METRICS))
    assert "| Drift over the run | -" in falling
    assert "exact straight line" in falling


def test_comparison_report():
    """The comparison report names the winner and its limits, or says why there is none, shows intervals and
    bias, and lists the runs that weren't ranked."""
    first, second = AmmeterSpec("first", 1, "X"), AmmeterSpec("second", 2, "X")
    tie = comparison_report(compare([_run(entes_readings(50, seed=1), spec=first),
                                     _run(entes_readings(50, seed=2), spec=second)]))
    assert "No winner, insufficient evidence" in tie
    assert "Most reliable" not in tie
    assert "doesn't show" in tie and "more accurate" in tie
    assert re.search(r"(first, second|second, first) are equally precise", tie)
    assert re.search(r"\| \d\.\d+ \(\d\.\d+ to \d\.\d+\) \|", tie)

    narrow = _run([99.0, 100.0, 101.0] * 15, spec=AmmeterSpec("narrow", 1, "X", expected_geo_mean=101.0))
    wide = _run([50.0, 100.0, 150.0] * 15, spec=AmmeterSpec("wide", 2, "X", expected_geo_mean=99.0))
    narrow["error_rate"], wide["error_rate"] = 0.01, 0.04
    text = comparison_report(compare([narrow, wide]))
    assert "Most reliable in this test: **narrow**" in text
    assert "It doesn't show" in text
    assert text.index("| 1 | narrow |") < text.index("| 2 | wide |")
    assert "| -1.0% | 1.0% |" in text and "| -8.2% | 4.0% |" in text

    assert "Not ranked: entes (status FAIL)" in comparison_report(compare([_run([5.0] * 50), _run(entes_readings(50))]))
    stuck_a, stuck_b = _run([5.0] * 50, spec=first), _run([6.0] * 50, spec=second)
    assert "Not ranked: first (status FAIL); second (status FAIL)" in comparison_report(compare([stuck_a, stuck_b]))


def test_reports_match_the_saved_copies():
    """The run report, the comparison report and the run list, word for word, against copies saved in tests/golden/,
    so wording, units, signs and columns can't change unnoticed. After an intended change, rerun with
    UPDATE_GOLDEN=1 to save new copies."""
    high = _run(entes_readings(50, seed=1) + [190.0], spec=replace(ENTES, name="high", expected_geo_mean=50.0),
                interval=0.125)  # exact in floating point, so the timing figures are exact too
    low = _run(entes_readings(50, seed=2), spec=replace(ENTES, name="low", expected_geo_mean=70.0), interval=0.125)
    stored = ("count", "mean", "std_dev", "cv")
    entries = [{"run_id": run["run_id"], "ammeter": run["ammeter"]["name"], "status": run["status"],
                "error_rate": run["error_rate"], **{k: run["statistics"][k] for k in stored}}
               for run in (high, low)]  # what the archive index stores
    reports = {"run_report.md": run_report(high, list(METRICS)),
               "comparison_report.md": comparison_report(compare([high, low])),
               "runs_table.md": runs_table(entries)}
    for name, text in reports.items():
        if os.environ.get("UPDATE_GOLDEN"):
            (GOLDEN / name).write_text(text, encoding="utf-8")
        assert text == (GOLDEN / name).read_text(encoding="utf-8"), f"{name} changed (if intended: UPDATE_GOLDEN=1)"
