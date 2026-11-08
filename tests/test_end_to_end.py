import logging
import os
import platform
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import yaml

from src.__main__ import main as cli
from src.client import AmmeterClient
from src.emulators import port_is_open
from src.errors import ConfigError, EmulatorError
from src.results import ResultStore
from src.sampling import Sampler
from src.settings import PROJECT_ROOT
from src.testing.test_framework import AmmeterTestFramework
from tests.helpers import answer, reset

pytestmark = pytest.mark.integration
FAST = {"measurements_count": 30, "sampling_frequency_hz": 50}
SEEDED = {"measurements_count": 10, "sampling_frequency_hz": 20}
# On a busy machine a 20 ms slot is sometimes missed; the sampling rules have their own exact tests
LOADED_MACHINE = 0.5
ALL_CHECKS = {"values_in_range", "error_rate", "sampling_rate", "not_stuck", "matches_model", "no_drift"}


def same_readings(a, b):
    """A seed fixes the sequence of readings. A slot missed on a busy machine only ends one run a little early."""
    n = min(len(a), len(b))
    return n >= max(len(a), len(b)) - 2 and a[:n] == b[:n]


@pytest.fixture
def running_config(ammeters, config):
    """Config that points at the session's emulators."""
    for name, spec in ammeters.items():
        config["ammeters"][name]["port"] = spec.port
    config["testing"]["sampling"] = FAST
    config["testing"]["acceptance"]["max_frequency_error"] = LOADED_MACHINE
    return config


@pytest.fixture
def own_emulators_config(config, free_port):
    """Config on fresh ports, so the framework starts (and can configure) its own emulators."""
    for name in config["ammeters"]:
        config["ammeters"][name]["port"] = free_port()
    config["testing"]["sampling"] = FAST
    config["testing"]["acceptance"]["max_frequency_error"] = LOADED_MACHINE
    config["analysis"]["visualization"]["enabled"] = False
    return config


def test_run_test_returns_and_archives_a_complete_result(running_config, write_config):
    """run_test() against a real emulator returns a complete PASS result and archives it with its samples,
    report and charts. The archive keeps the effective settings and the full config."""
    path = write_config(running_config)
    with AmmeterTestFramework(path) as framework:
        result = framework.run_test("entes")
        folder = framework.store.run_dir(result["run_id"])

        assert result["status"] == "PASS"
        assert result["statistics"]["count"] == 30
        assert result["missed"] == 0
        for key in ("mean", "median", "std_dev", "min", "max"):
            assert key in result["statistics"]
        assert {c["name"] for c in result["checks"]} == ALL_CHECKS
        assert not any(c["skipped"] for c in result["checks"])
        for name in ("run.json", "samples.csv", "report.md", "plots/timeseries.png", "plots/histogram.png"):
            assert (folder / name).exists(), name
        assert framework.store.load(result["run_id"]) == result
        assert framework.store.list_runs("entes")[-1]["run_id"] == result["run_id"]

    with AmmeterTestFramework(path, profile="smoke") as framework:
        stored = framework.store.load(framework.run_test("circutor")["run_id"])
    assert stored["settings"]["sampling"]["measurements_count"] == 10  # the profile, not the file's sampling
    assert stored["settings"]["timeout_s"] == running_config["testing"]["timeout_seconds"]
    assert stored["settings"]["acceptance"]["stuck_after"] == 3
    assert stored["config"]["content"] == yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    assert stored["config"]["profile"] == "smoke"


def test_run_all_compares_every_ammeter(running_config, write_config, monkeypatch):
    """run_all() tests every ammeter and compares them, with a comparison chart, honours the configured ranking
    minimum, goes on after a FAIL, and on Ctrl-C stops but still saves the comparison."""
    running_config["analysis"]["visualization"]["enabled"] = False
    with AmmeterTestFramework(write_config(running_config)) as framework:
        result = framework.run_all()
    comparison = result["comparison"]
    assert [run["ammeter"]["name"] for run in result["runs"]] == ["greenlee", "entes", "circutor"]
    assert all(run["status"] == "PASS" for run in result["runs"])
    assert len(comparison["rows"]) == 3
    assert [r["cv"] for r in comparison["rows"]] == sorted(r["cv"] for r in comparison["rows"])  # most precise first
    assert comparison["most_reliable"] in ("entes", "circutor", None)
    assert comparison["most_reliable"] or "insufficient evidence" in comparison["conclusion"]

    running_config["analysis"]["min_readings_to_rank"] = 31
    running_config["analysis"]["visualization"]["enabled"] = True
    with AmmeterTestFramework(write_config(running_config)) as framework:
        result = framework.run_all(["entes", "circutor"])
        comparison, root = result["comparison"], framework.store.root.resolve()
    assert comparison["rows"] == []
    assert [r["reason"] for r in comparison["not_ranked"]] == ["only 30 readings, 31 needed"] * 2
    assert (Path(comparison["folder"]) / "comparison.json").exists()
    assert (Path(comparison["folder"]) / "comparison.png").exists()
    assert all(Path(run["log_file"]).resolve().is_relative_to(root) for run in result["runs"])

    calls = []

    def fake_run_test(name):
        calls.append(name)
        return {"run_id": name, "status": {"greenlee": "FAIL", "entes": "INTERRUPTED"}.get(name, "PASS"),
                "ammeter": {"name": name, "expected_geo_mean": None}, "statistics": {"count": 0}, "error_rate": 0.0}

    running_config["analysis"]["visualization"]["enabled"] = False
    with AmmeterTestFramework(write_config(running_config)) as framework:
        monkeypatch.setattr(framework, "run_test", fake_run_test)
        result = framework.run_all()
    assert calls == ["greenlee", "entes"]  # goes on after a FAIL, stops on Ctrl-C
    assert [r["reason"] for r in result["comparison"]["not_ranked"]] == ["status FAIL", "status INTERRUPTED"]


def test_unknown_names_fail_before_anything_runs(own_emulators_config, write_config, windows_loopback):
    """A misspelled ammeter name fails before any emulator starts or any run is saved. A closed framework starts its
    emulators again, also when refusals are as slow as on Windows, and they stop when the program ends."""
    with AmmeterTestFramework(write_config(own_emulators_config)) as framework:
        with pytest.raises(ConfigError, match="unknown ammeter 'fluke'"):
            framework.run_test("fluke")
        with pytest.raises(ConfigError, match="unknown ammeter 'fluke'"):
            framework.run_all(["entes", "fluke"])
        assert framework.store.list_runs() == []
        assert not any(port_is_open("127.0.0.1", a["port"]) for a in own_emulators_config["ammeters"].values())
    framework.run_test("entes")
    framework.close()
    with framework:  # a closed framework starts its emulators again when it's used
        assert framework.run_test("entes")["error_count"] == 0

    script = (f"from src.testing.test_framework import AmmeterTestFramework\n"
              f"framework = AmmeterTestFramework({write_config(own_emulators_config)!r})\n"
              f"framework.run_test('entes')\n"
              f"print('PID', framework._emulators._process.pid)\n")  # and exits without close()
    output = subprocess.run([sys.executable, "-c", script], cwd=PROJECT_ROOT, capture_output=True, text=True,
                            timeout=60).stdout
    pid = int(next(line.split()[1] for line in output.splitlines() if line.startswith("PID")))
    entes_port = own_emulators_config["ammeters"]["entes"]["port"]
    try:
        assert not port_is_open("127.0.0.1", entes_port)  # the emulators stopped when the program ended
    finally:
        if port_is_open("127.0.0.1", entes_port):
            os.kill(pid, signal.SIGTERM)


def test_injected_faults_are_detected(own_emulators_config, write_config):
    """Runs with injected garbage, spikes, stuck readings and timeouts fail, each fault shows up where it should, and
    the faults are in the emulator log. A timeout fault lasts 1 s longer than the client waits."""
    own_emulators_config["testing"]["sampling"] = {"measurements_count": 40, "sampling_frequency_hz": 50}
    own_emulators_config["fault_injection"] = {"enabled": True, "seed": 1, "rates": {"garbage": 0.2, "spike": 0.2}}
    with AmmeterTestFramework(write_config(own_emulators_config)) as framework:
        result = framework.run_test("circutor")
    checks = {c["name"]: c["passed"] for c in result["checks"]}
    assert result["status"] == "FAIL"
    assert result["errors"]["AmmeterResponseError"] > 0
    assert not checks["values_in_range"]
    assert not checks["error_rate"]
    assert result["fault_injection"]["delay_s"] == own_emulators_config["testing"]["timeout_seconds"] + 1
    emulator_log = Path(own_emulators_config["result_management"]["results_dir"]) / "logs" / "emulators.log"
    assert "FAULT INJECTED" in emulator_log.read_text(encoding="utf-8")

    own_emulators_config["testing"]["sampling"] = FAST
    own_emulators_config["fault_injection"]["rates"] = {"stuck": 0.3}
    with AmmeterTestFramework(write_config(own_emulators_config)) as framework:
        result = framework.run_test("entes")
    checks = {c["name"]: c["passed"] for c in result["checks"]}
    assert result["error_count"] == 0
    assert not checks["not_stuck"]
    assert result["status"] == "FAIL"

    own_emulators_config["testing"].update(timeout_seconds=0.3,
                                           sampling={"measurements_count": 3, "sampling_frequency_hz": 10})
    own_emulators_config["fault_injection"]["rates"] = {"timeout": 1.0}
    with AmmeterTestFramework(write_config(own_emulators_config)) as framework:
        assert framework.run_test("entes")["errors"] == {"AmmeterTimeoutError": 1}

    own_emulators_config["testing"]["sampling"] = {"measurements_count": 20, "sampling_frequency_hz": 50}
    own_emulators_config["fault_injection"]["rates"] = {"spike": 0.5}
    with AmmeterTestFramework(write_config(own_emulators_config)) as framework:
        assert 0 < framework.run_test("entes")["out_of_range_rate"] <= 1


def test_slow_ammeter_cannot_stretch_the_run(config, write_config, tcp_server):
    """A 1 s run against an ammeter that takes 0.25 s per reading ends on time, with the missed slots counted
    and the sampling_rate check failed."""
    port = tcp_server(answer(b"60.0", delay_s=0.25))
    config["ammeters"]["entes"].update(port=port, emulator=None)
    config["testing"]["start_emulators"] = False
    config["testing"]["sampling"] = {"total_duration_seconds": 1, "sampling_frequency_hz": 10}
    config["analysis"]["visualization"]["enabled"] = False
    with AmmeterTestFramework(write_config(config)) as framework:
        start = time.monotonic()
        result = framework.run_test("entes")
        elapsed = time.monotonic() - start
    assert elapsed < 1 + 0.25 + 0.5  # duration + the last reading + bookkeeping
    assert result["missed"] >= 5
    assert result["statistics"]["count"] + result["missed"] == 10
    assert not {c["name"]: c["passed"] for c in result["checks"]}["sampling_rate"]


def test_seeded_runs_repeat_exactly(own_emulators_config, write_config, ammeters, caplog, tcp_server):
    """Runs with the same seed give identical readings, and another seed gives different ones. A seed that can't be
    applied, because the emulator was already running, is warned about; checking it takes a single reading."""
    own_emulators_config["testing"]["sampling"] = SEEDED  # a missed slot would shorten one run

    def readings(seed):
        own_emulators_config["testing"]["emulator_seed"] = seed
        with AmmeterTestFramework(write_config(own_emulators_config)) as framework:
            run = framework.run_test("entes")
            return [s.value for s in framework.store.load_samples(run["run_id"])], run

    first, run = readings(5)
    assert run["settings"]["emulator_seed"] == 5
    assert same_readings(readings(5)[0], first)
    assert readings(6)[0] != first

    probes = []

    def counted(conn):
        if conn.recv(1024):  # a request, not just a check that the port is open
            probes.append(1)
            conn.sendall(b"1.5")

    own_emulators_config["ammeters"]["circutor"]["port"] = ammeters["circutor"].port  # already running
    own_emulators_config["ammeters"]["greenlee"]["port"] = tcp_server(counted)  # answers like a running emulator
    with caplog.at_level(logging.WARNING, logger="src.testing.test_framework"):
        with AmmeterTestFramework(write_config(own_emulators_config)) as framework:
            framework.run_test("circutor")
    assert "circutor is already running, so its faults and seed can't be set" in caplog.text
    assert len(probes) == 1  # checking a running emulator takes a single reading


def test_unreachable_ammeter_ends_in_error(config, write_config, tcp_server, monkeypatch):
    """An ammeter that drops every connection ends in ERROR, using the configured retries and failure limit, with
    the failures in the samples, the log and the report. A bug in the code is raised, not hidden as an ERROR run."""
    config["ammeters"]["entes"].update(port=tcp_server(reset), emulator=None)  # refuses at once on every platform
    config["testing"]["start_emulators"] = False
    config["testing"]["sampling"] = FAST
    with AmmeterTestFramework(write_config(config)) as framework:
        result = framework.run_test("entes")
    assert result["status"] == "ERROR"
    assert "in a row" in result["stop_reason"]
    assert result["errors"] == {"AmmeterConnectionError": 5}

    connections = []

    def resetting(conn):
        connections.append(1)
        reset(conn)

    config["ammeters"]["entes"].update(port=tcp_server(resetting), emulator=None)
    config["testing"].update(retries=0, max_consecutive_errors=2,
                             sampling={"measurements_count": 10, "sampling_frequency_hz": 20})
    config["analysis"]["visualization"]["enabled"] = False
    with AmmeterTestFramework(write_config(config)) as framework:
        result = framework.run_test("entes")
        samples = framework.store.load_samples(result["run_id"])
        report_text = (framework.store.run_dir(result["run_id"]) / "report.md").read_text(encoding="utf-8")
    assert len(connections) == 2  # retries: 0, and the run stops after max_consecutive_errors: 2
    assert result["errors"] == {"AmmeterConnectionError": 2}
    assert result["error_rate"] == 1.0
    assert [s.error is not None for s in samples] == [True, True]
    assert "reading 1 failed" in Path(result["log_file"]).read_text(encoding="utf-8")
    assert "## entes: ERROR" in report_text
    assert result["started_at"] < result["finished_at"]
    assert result["environment"]["python"] == platform.python_version()

    monkeypatch.setattr(AmmeterClient, "measure", lambda self: 1 / 0)  # a bug in the code, not an ammeter error
    with AmmeterTestFramework(write_config(config)) as framework:
        with pytest.raises(ZeroDivisionError):
            framework.run_test("entes")


def test_port_taken_by_another_program(config, write_config, free_port, windows_loopback):
    """A port held by another program is reported clearly and quickly, for every configured port, also when free
    ports refuse as slowly as on Windows, and is checked again on the next run. The AirPlay hint is only for 5000."""
    other, silent, held = socket.create_server(("127.0.0.1", 0)), socket.create_server(("127.0.0.1", 0)), []
    port = other.getsockname()[1]

    def answer_like_a_web_server():
        while True:
            try:
                conn, _ = other.accept()
            except OSError:
                return
            with conn:
                conn.recv(1024)
                conn.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")

    def accept_and_never_answer():
        while True:
            try:
                held.append(silent.accept()[0])
            except OSError:
                return

    threading.Thread(target=answer_like_a_web_server, daemon=True).start()
    threading.Thread(target=accept_and_never_answer, daemon=True).start()
    try:
        config["ammeters"]["greenlee"]["port"] = port
        with AmmeterTestFramework(write_config(config)) as framework:
            for _ in range(2):  # checked again on the next run, not only once
                with pytest.raises(EmulatorError, match=f"port {port} for greenlee is used by another") as error:
                    framework.run_test("greenlee")
        assert "AirPlay" not in str(error.value)  # that hint is only for port 5000 on macOS

        config["ammeters"]["greenlee"]["port"] = free_port()
        config["ammeters"]["entes"]["port"] = free_port()
        config["ammeters"]["circutor"]["port"] = silent.getsockname()[1]
        start = time.monotonic()
        with AmmeterTestFramework(write_config(config)) as framework:
            with pytest.raises(EmulatorError, match="for circutor is used by another program"):
                framework.run_test("entes")  # every port is checked, not only the one being tested
        assert time.monotonic() - start < 3
    finally:
        other.close()
        silent.close()
        for conn in held:
            conn.close()


def test_command_line(own_emulators_config, write_config, free_port, capsys, tmp_path, monkeypatch):
    """The command line: run (with --profile, --seed, --duration and --faults), list, show, compare and history, with
    exit codes 0, 1 and 2. An interrupted run's report is still printed."""
    own_emulators_config["fault_injection"]["rates"] = {"garbage": 0.3}  # only used with --faults
    path, other = write_config(own_emulators_config), str(tmp_path / "other_results")
    assert cli(["--config", path, "run", "circutor", "--profile", "smoke", "--no-plots"]) == 0
    out = capsys.readouterr().out
    assert "## circutor: PASS" in out
    assert "10 valid readings of 10 planned" in out
    assert cli(["--config", path, "list", "--ammeter", "circutor"]) == 0
    listing = capsys.readouterr().out
    run_id = next(line.split("|")[1].strip() for line in listing.splitlines() if "_circutor_" in line)
    assert cli(["--config", path, "show", run_id]) == 0
    assert run_id in capsys.readouterr().out
    assert cli(["--config", path, "show", "no-such-run"]) == 2

    for _ in range(2):
        assert cli(["--config", path, "--results-dir", other, "run", "entes", "--seed", "4", "--count", "10",
                    "--frequency", "20", "--no-plots"]) == 0
        assert "## Comparison" not in capsys.readouterr().out
    store = ResultStore(Path(other))
    first, second = [e["run_id"] for e in store.list_runs()]
    assert same_readings([s.value for s in store.load_samples(first)], [s.value for s in store.load_samples(second)])
    assert cli(["--config", path, "--results-dir", other, "list", "--status", "FAIL"]) == 0
    assert "No runs found" in capsys.readouterr().out
    assert cli(["--config", path, "--results-dir", other, "show", first]) == 0
    assert "| Median |" in capsys.readouterr().out

    own_emulators_config["ammeters"]["circutor"].update(emulator=None, port=free_port())  # nothing there
    path = write_config(own_emulators_config)
    assert cli(["--config", path, "--results-dir", other, "run", "entes", "circutor", "--no-plots"]) == 1
    capsys.readouterr()
    assert cli(["--config", path, "--results-dir", other, "compare", *[e["run_id"] for e in store.list_runs()]]) == 0
    assert "circutor (status ERROR)" in capsys.readouterr().out  # every run given is compared
    assert cli(["--config", path, "--results-dir", other, "history", "entes"]) == 0
    history = capsys.readouterr().out
    assert "_entes_" in history and "_circutor_" not in history
    assert cli(["--config", path, "--results-dir", other, "list", "--ammeter", "entes"]) == 0
    listing = capsys.readouterr().out
    assert "_entes_" in listing and "_circutor_" not in listing
    cli(["--config", path, "--results-dir", other, "run", "entes", "--duration", "0.5", "--frequency", "20", "--faults",
         "--no-plots"])
    out = capsys.readouterr().out
    assert "of 10 planned" in out and "Fault injection was on" in out

    real_run = Sampler.run

    def ctrl_c_on_the_third_reading(self, plan, measure, *args, **kwargs):
        calls = []

        def measure_or_stop():
            calls.append(1)
            if len(calls) == 3:
                raise KeyboardInterrupt
            return measure()

        return real_run(self, plan, measure_or_stop, *args, **kwargs)

    monkeypatch.setattr(Sampler, "run", ctrl_c_on_the_third_reading)
    assert cli(["--config", path, "--results-dir", other, "run", "entes", "--no-plots"]) == 1
    assert "## entes: INTERRUPTED" in capsys.readouterr().out  # the report of an interrupted run is shown


def test_main_py_gets_a_reading_from_every_ammeter(config, write_config, free_port, tcp_server):
    """main.py gets a reading from every ammeter, from emulators or a real device, also on an old Windows
    console that can't print 'Ω'."""
    for name in config["ammeters"]:
        config["ammeters"][name]["port"] = free_port()
    output = subprocess.run(
        [sys.executable, "main.py", write_config(config)],
        cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
    ).stdout
    assert output.count("Received current measurement") == 3
    assert "No data received" not in output

    config["ammeters"]["greenlee"]["port"] = free_port()
    config["ammeters"]["circutor"]["port"] = free_port()
    config["ammeters"]["entes"].update(port=tcp_server(answer(b"60.5")), emulator=None)  # a real device
    proc = subprocess.run(
        [sys.executable, "main.py", write_config(config)], cwd=PROJECT_ROOT, capture_output=True, timeout=30,
        env={**os.environ, "PYTHONIOENCODING": "cp1252"}, encoding="cp1252", errors="replace",
    )
    assert proc.stdout.count("Received current measurement") == 3  # Greenlee prints 'Ω', which cp1252 lacks
    assert "Traceback" not in proc.stderr
