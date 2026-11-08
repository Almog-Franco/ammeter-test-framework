import json
import os
import random
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from src.errors import EmulatorError
from src.settings import PROJECT_ROOT, AmmeterSpec

EMULATORS = {"greenlee": GreenleeAmmeter, "entes": EntesAmmeter, "circutor": CircutorAmmeter}


def port_is_open(host: str, port: int, timeout_s: float = 0.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def wait_for_port(host: str, port: int, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if port_is_open(host, port):
            return True
        time.sleep(0.05)
    return False


class EmulatorProcess:
    """Runs emulators in a separate process, like a real device, and sends their output to a log file."""

    def __init__(self, ammeters: list[AmmeterSpec], log_path: Path, faults: dict | None = None,
                 seed: int | None = None):
        self.ammeters = ammeters
        self.log_path = Path(log_path)
        self.faults = faults
        self.seed = seed
        self._process = None
        self._log = None

    def start(self) -> "EmulatorProcess":
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log = open(self.log_path, "a", encoding="utf-8")
        args = {
            "ammeters": {a.name: {"emulator": a.emulator, "port": a.port} for a in self.ammeters},
            "faults": self.faults,
            "seed": self.seed,
        }
        # UTF-8 output, otherwise Greenlee's 'Ω' crashes its thread on Windows when output goes to a file
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
        try:
            self._process = subprocess.Popen(
                [sys.executable, "-m", "src.emulators", json.dumps(args)],
                cwd=PROJECT_ROOT, env=env, stdout=self._log, stderr=subprocess.STDOUT,
            )
        except OSError as e:
            self.stop()
            raise EmulatorError(f"could not start the emulator process: {e}") from None
        self._wait_until_ready()
        return self

    def stop(self):
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
        if self._log:
            self._log.close()
        self._process = self._log = None

    __enter__ = start

    def __exit__(self, *exc):
        self.stop()

    def _wait_until_ready(self, timeout_s: float = 10.0):
        pending = list(self.ammeters)
        deadline = time.monotonic() + timeout_s
        while pending and time.monotonic() < deadline and self._process.poll() is None:
            pending = [a for a in pending if not port_is_open(a.host, a.port)]
            if pending:
                time.sleep(0.05)
        if pending:
            self.stop()
            with open(self.log_path, "rb") as f:
                f.seek(max(0, f.seek(0, os.SEEK_END) - 4000))
                tail = f.read().decode("utf-8", errors="replace").strip().splitlines()[-5:]
            names = ", ".join(f"{a.name} (port {a.port})" for a in pending)
            raise EmulatorError(f"emulator did not start: {names}. Last lines of {self.log_path}:\n" + "\n".join(tail))


def serve(ammeters: dict, faults: dict | None = None, seed: int | None = None):
    from src.faults import FaultyAmmeter

    emulators = []
    for name, cfg in ammeters.items():
        emulator = EMULATORS[cfg["emulator"]](cfg["port"])
        if faults:
            fault_seed = None if faults.get("seed") is None else f"{faults['seed']}:{name}"
            emulator = FaultyAmmeter(emulator, faults["rates"], seed=fault_seed, delay_s=faults.get("delay_s", 3.0))
        emulators.append((name, emulator))
    if seed is not None:
        # The emulators share Python's random generator and reseed it with the clock when created,
        # so it is seeded here, after creating them and before the first reading.
        random.seed(seed)
    for name, emulator in emulators:
        threading.Thread(target=emulator.start_server, name=name, daemon=True).start()
    while True:
        time.sleep(1)


if __name__ == "__main__":
    options = json.loads(sys.argv[1])
    serve(options["ammeters"], options.get("faults"), options.get("seed"))
