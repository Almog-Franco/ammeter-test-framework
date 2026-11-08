import random
import time

from Ammeters.base_ammeter import AmmeterEmulatorBase

STUCK_READINGS = 5


class FaultyAmmeter(AmmeterEmulatorBase):
    """Wraps a working emulator and makes some answers go wrong, to check that the framework catches them.

    timeout      answers only after the client has given up
    no_response  sends nothing back
    garbage      sends text that is not a number
    spike        sends a reading a million times too big
    stuck        repeats the same reading for the next few requests, like a frozen sensor
    """

    def __init__(self, inner: AmmeterEmulatorBase, rates: dict[str, float], seed=None, delay_s: float = 3.0):
        super().__init__(inner.port)
        self.inner = inner
        self.rates = rates
        self.delay_s = delay_s
        self.rng = random.Random(seed)
        self._stuck_value = None
        self._stuck_left = 0

    @property
    def get_current_command(self) -> bytes:
        return self.inner.get_current_command

    def pick_fault(self) -> str | None:
        roll = self.rng.random()
        for fault, rate in self.rates.items():
            if roll < rate:
                return fault
            roll -= rate
        return None

    def measure_current(self):
        if self._stuck_left:
            self._stuck_left -= 1
            return self._stuck_value
        value = self.inner.measure_current()
        fault = self.pick_fault()
        if fault:
            print(f"FAULT INJECTED: {fault}")
        if fault == "timeout":
            time.sleep(self.delay_s)
        elif fault == "no_response":
            return ""  # the server sends str(value), so nothing goes out
        elif fault == "garbage":
            return "ERR#42"
        elif fault == "spike":
            return value * 1e6
        elif fault == "stuck":
            self._stuck_value, self._stuck_left = value, STUCK_READINGS - 1
        return value
