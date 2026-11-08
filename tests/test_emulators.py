"""The same contract for every configured ammeter, checked against the real emulators."""
import gc
import io
import math
import random
import socket
import statistics
import sys
import threading
import time
import warnings
from contextlib import redirect_stdout

import pytest

from Ammeters.Entes_Ammeter import EntesAmmeter
from src.client import AmmeterClient
from src.emulators import EMULATORS, EmulatorProcess, port_is_open, wait_for_port
from src.errors import AmmeterError, AmmeterResponseError, EmulatorError
from src.faults import FaultyAmmeter
from src.settings import AmmeterSpec, load_settings
from tests.helpers import reset

pytestmark = pytest.mark.integration
NAMES = list(load_settings().ammeters)
FORMULAS = {  # min, max and mean straight from each emulator's formula and input ranges
    "greenlee": (1 / 100, 10 / 0.1, 5.5 * math.log(100 / 0.1) / 99.9),  # V / R
    "entes": (0.01 * 500, 0.1 * 2000, 0.055 * 1250),  # B * K
    "circutor": (0.001 * 10 * 0.1, 0.01 * 10 * 1.0, 0.0055 * 10 * 0.55),  # time step * sum of 10 voltages
}
AT_INPUT_BOUNDS = {"greenlee": (10.0, 0.1), "entes": (5.0, 200.0), "circutor": (0.001, 0.1)}  # all inputs low / high


@pytest.mark.parametrize("name", NAMES)
def test_each_ammeter_answers_only_its_exact_command(ammeters, name):
    """Contract test for each configured ammeter: its full command gives varied readings in range, at full
    resolution, and a partial command or a trailing newline gets no answer."""
    spec = ammeters[name]
    client = AmmeterClient.from_spec(spec)
    readings = [client.measure() for _ in range(25)]
    assert all(spec.expected_min <= r <= spec.expected_max for r in readings)
    assert len(set(readings)) > 1
    assert all(r != round(r) for r in readings)  # full resolution, not rounded

    for wrong in (spec.command.split()[0].encode(), spec.command.encode() + b"\n"):  # e.g. b"MEASURE_GREENLEE"
        with pytest.raises(AmmeterResponseError, match="empty response"):
            AmmeterClient(spec.host, spec.port, wrong).measure()


def test_readme_circutor_command_is_not_what_the_emulator_accepts(ammeters):
    """The CIRCUTOR command in the README gets no answer. This records the documentation bug that the config
    works around."""
    spec = ammeters["circutor"]
    client = AmmeterClient(spec.host, spec.port, b"MEASURE_CIRCUTOR -get_measurement")
    with pytest.raises(AmmeterResponseError):
        client.measure()


@pytest.mark.parametrize("name", NAMES)
def test_emulator_survives_clients_that_reset_the_connection(free_port, name):
    """A client that resets the connection, before or after sending a command, doesn't stop the emulator
    (fix 14 in the supplied code)."""
    emulator = EMULATORS[name](free_port())
    output = io.StringIO()
    with redirect_stdout(output):
        server = threading.Thread(target=emulator.start_server, daemon=True)
        server.start()
        assert wait_for_port("127.0.0.1", emulator.port)
        for send_first in (False, True):
            conn = socket.create_connection(("127.0.0.1", emulator.port))
            if send_first:
                conn.sendall(emulator.get_current_command)
            reset(conn)
            conn.close()
            time.sleep(0.2)
            assert server.is_alive()
        reading = AmmeterClient("127.0.0.1", emulator.port, emulator.get_current_command).measure()
    assert math.isfinite(reading)
    assert server.is_alive()


class _Broken(EntesAmmeter):
    error = ValueError("a bug in measure_current")

    def measure_current(self):
        raise self.error


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
@pytest.mark.parametrize("error", [ValueError("a bug in measure_current"), OSError(24, "Too many open files")])
@pytest.mark.parametrize("with_faults", [False, True])
def test_emulator_stops_on_its_own_errors(free_port, error, with_faults):
    """A real bug inside an emulator isn't hidden like a dropped client: the emulator stops, also when fault
    injection is wrapped around it."""
    emulator = _Broken(free_port())
    emulator.error = error
    if with_faults:
        emulator = FaultyAmmeter(emulator, {})  # fault injection must not hide it either
    with redirect_stdout(io.StringIO()):
        server = threading.Thread(target=emulator.start_server, daemon=True)
        server.start()
        assert wait_for_port("127.0.0.1", emulator.port)
        with pytest.raises(AmmeterError):
            AmmeterClient("127.0.0.1", emulator.port, emulator.get_current_command).measure()
        server.join(timeout=2)
    assert not server.is_alive()  # real faults must not be hidden like a dropped client


def _readings(port, seed, tmp_path, count=5, faults=None):
    spec = AmmeterSpec("entes", port, "MEASURE_ENTES -get_data", emulator="entes")
    with EmulatorProcess([spec], tmp_path / f"emulators_{port}.log", faults=faults, seed=seed):
        client = AmmeterClient.from_spec(spec)
        return [client.measure() for _ in range(count)]


def _fault_outcomes(tmp_path, free_port):
    specs = [AmmeterSpec("entes", free_port(), "MEASURE_ENTES -get_data", emulator="entes"),
             AmmeterSpec("entes_b", free_port(), "MEASURE_ENTES -get_data", emulator="entes")]
    result = {}
    faults = {"rates": {"garbage": 0.5}, "seed": 3}
    with EmulatorProcess(specs, tmp_path / f"faults_{specs[0].port}.log", faults=faults):
        for spec in specs:
            client, seen = AmmeterClient.from_spec(spec, retries=0), []
            for _ in range(20):
                try:
                    client.measure()
                    seen.append(True)
                except AmmeterResponseError:
                    seen.append(False)
            result[spec.name] = seen
    return result


def test_seeds_make_readings_and_faults_repeatable(tmp_path, free_port):
    """The same seed gives the same readings and faults, and another seed gives other readings. The seed is exactly
    the one given, faults don't change the readings, and each ammeter has its own fault sequence. The configured
    fault delay reaches the emulator process."""
    first = _readings(free_port(), 42, tmp_path)
    assert _readings(free_port(), 42, tmp_path) == first
    assert _readings(free_port(), 43, tmp_path) != first
    assert _readings(free_port(), 44, tmp_path) != first
    assert _readings(free_port(), None, tmp_path) != first
    assert _readings(free_port(), 0, tmp_path) == _readings(free_port(), 0, tmp_path)
    emulator = EntesAmmeter(0)
    random.seed(42)
    with redirect_stdout(io.StringIO()):
        assert [emulator.measure_current() for _ in range(5)] == first  # exactly the seed that was given

    faults = {"rates": {"spike": 0.0}, "seed": 1}
    assert _readings(free_port(), 7, tmp_path, faults=faults) == _readings(free_port(), 7, tmp_path, faults=faults)
    assert _readings(free_port(), 7, tmp_path, faults=faults) == _readings(free_port(), 7, tmp_path)  # faults off
    outcomes = _fault_outcomes(tmp_path, free_port)
    assert outcomes["entes"] != outcomes["entes_b"]  # each ammeter has its own fault sequence
    assert _fault_outcomes(tmp_path, free_port) == outcomes
    delayed = {"rates": {"timeout": 1.0}, "delay_s": 0.2, "seed": 1}  # answers after 0.2 s, within the client's 2 s
    assert len(_readings(free_port(), None, tmp_path, count=1, faults=delayed)) == 1


def test_failed_start_shows_the_emulator_log(tmp_path, free_port):
    """When an emulator can't start, the error names it and shows the last lines of the emulator log.
    Stopping closes the log file, and the emulators are gone as soon as stop() returns."""
    broken = AmmeterSpec("broken", free_port(), "MEASURE", emulator="no_such_emulator")
    gc.collect()  # so earlier tests' leftovers can't show up below
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ResourceWarning)
        with pytest.raises(EmulatorError, match="(?s)did not start: broken.*KeyError"):
            EmulatorProcess([broken], tmp_path / "emulators.log").start()
        gc.collect()
    assert not [w for w in caught if "emulators.log" in str(w.message)]  # the log file was closed

    spec = AmmeterSpec("entes", free_port(), "MEASURE_ENTES -get_data", emulator="entes")
    with EmulatorProcess([spec], tmp_path / "stop.log"):
        assert port_is_open(spec.host, spec.port)
    assert not port_is_open(spec.host, spec.port)


@pytest.mark.parametrize("name, expected_cv, tolerance", [
    ("greenlee", 4.96, 0.25),  # long tail, so its mean and CV settle slowly
    ("entes", 0.608, 0.03),
    ("circutor", 0.500, 0.03),
])
def test_expected_values_in_config_match_the_emulator_physics(capsys, monkeypatch, name, expected_cv, tolerance):
    """The expected values in the config match the emulators: min, max and mean exactly, from the formulas (also with
    every input at its bounds), and CV, geometric mean and log spread from 20,000 readings of measure_current()."""
    spec = load_settings().ammeter(name)
    emulator = EMULATORS[name](0)
    random.seed(1)
    values = [emulator.measure_current() for _ in range(20000)]
    capsys.readouterr()
    logs = [math.log(v) for v in values]
    low, high, mean = FORMULAS[name]
    assert (spec.expected_min, spec.expected_max) == pytest.approx((low, high))
    assert spec.expected_mean == pytest.approx(mean, rel=1e-3)

    assert spec.expected_min <= min(values) and max(values) <= spec.expected_max
    assert statistics.fmean(values) == pytest.approx(spec.expected_mean, rel=tolerance / 2)
    assert statistics.stdev(values) / statistics.fmean(values) == pytest.approx(expected_cv, rel=tolerance)
    assert math.exp(statistics.fmean(logs)) == pytest.approx(spec.expected_geo_mean, rel=0.03)
    assert statistics.stdev(logs) == pytest.approx(spec.expected_log_std, rel=0.03)

    module, (at_low, at_high) = sys.modules[type(emulator).__module__], AT_INPUT_BOUNDS[name]
    monkeypatch.setattr(module, "generate_random_float", lambda low, high: low)
    assert emulator.measure_current() == pytest.approx(at_low)
    monkeypatch.setattr(module, "generate_random_float", lambda low, high: high)
    assert emulator.measure_current() == pytest.approx(at_high)
