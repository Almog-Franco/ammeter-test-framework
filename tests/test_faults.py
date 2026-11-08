import threading
from collections import Counter

import pytest

from Ammeters.Entes_Ammeter import EntesAmmeter
from src import plots
from src.client import AmmeterClient
from src.emulators import wait_for_port
from src.errors import AmmeterResponseError, AmmeterTimeoutError
from src.faults import STUCK_READINGS, FaultyAmmeter

pytestmark = pytest.mark.integration


def _start(emulator) -> AmmeterClient:
    threading.Thread(target=emulator.start_server, daemon=True).start()
    assert wait_for_port("127.0.0.1", emulator.port)
    return AmmeterClient("127.0.0.1", emulator.port, emulator.get_current_command, timeout_s=0.2, retries=0)


@pytest.mark.parametrize("fault, error, message", [
    ("timeout", AmmeterTimeoutError, "no complete answer"),
    ("no_response", AmmeterResponseError, "empty response"),
    ("garbage", AmmeterResponseError, "not a number"),
])
def test_each_fault_is_caught(free_port, fault, error, message):
    """Each fault that breaks the reply (timeout, no response, garbage) reaches the client as the right error."""
    client = _start(FaultyAmmeter(EntesAmmeter(free_port()), {fault: 1.0}, delay_s=0.5))
    with pytest.raises(error, match=message):
        client.measure()


def test_spike_and_stuck_faults_give_bad_readings(free_port):
    """A spike is far outside the expected range, wide enough for the charts to switch to a log scale, and a stuck
    fault repeats the same reading 5 times before the next real one."""
    spike = _start(FaultyAmmeter(EntesAmmeter(free_port()), {"spike": 1.0})).measure()
    assert spike > 200 * 1000
    assert plots._spans_decades([60.0, spike])  # so the charts switch to a log scale

    client = _start(FaultyAmmeter(EntesAmmeter(free_port()), {"stuck": 1.0}))
    readings = [client.measure() for _ in range(STUCK_READINGS + 1)]
    assert len(set(readings[:STUCK_READINGS])) == 1
    assert readings[STUCK_READINGS] != readings[0]


def test_faults_are_logged_delayed_and_then_over(free_port, capsys):
    """Every fault is logged by name, and a timeout fault lasts the configured delay and then sends the real reading.
    The emulator works normally once the fault is over."""
    FaultyAmmeter(EntesAmmeter(0), {"spike": 1.0}).measure_current()
    assert "FAULT INJECTED: spike" in capsys.readouterr().out

    client = _start(FaultyAmmeter(EntesAmmeter(free_port()), {"timeout": 1.0}, delay_s=1.6))
    client.timeout_s = 1.3
    with pytest.raises(AmmeterTimeoutError):  # the delay is the configured one, not a fixed one
        client.measure()
    assert "FAULT INJECTED: timeout" in capsys.readouterr().out

    emulator = FaultyAmmeter(EntesAmmeter(free_port()), {"timeout": 1.0}, delay_s=0.3)
    client = _start(emulator)
    with pytest.raises(AmmeterTimeoutError):
        client.measure()
    client.timeout_s = 2.0
    assert 5 <= client.measure() <= 200  # a client that waits long enough gets the real reading
    emulator.rates = {}
    assert 5 <= client.measure() <= 200  # the emulator keeps working after a fault


def _picks(seed, n):
    emulator = FaultyAmmeter(EntesAmmeter(0), {"timeout": 0.1, "garbage": 0.2}, seed=seed)
    return [emulator.pick_fault() for _ in range(n)]


def test_fault_rates_and_seeds():
    """Faults happen at the configured rates, the same seed gives the same sequence, and other seeds give
    other sequences."""
    picks = Counter(_picks(seed=3, n=10000))
    assert picks["timeout"] == pytest.approx(1000, rel=0.1)
    assert picks["garbage"] == pytest.approx(2000, rel=0.1)
    assert picks[None] == pytest.approx(7000, rel=0.05)

    assert _picks(seed=3, n=50) == _picks(seed=3, n=50)
    assert _picks(seed=3, n=50) != _picks(seed=4, n=50)
    assert _picks(seed=3, n=50) != _picks(seed=5, n=50)
    assert _picks(seed="7:entes", n=50) == _picks(seed="7:entes", n=50)
    assert _picks(seed="7:entes", n=50) != _picks(seed="7:greenlee", n=50)
