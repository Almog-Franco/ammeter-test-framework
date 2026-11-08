import math
import re
import socket
import time

from src.errors import AmmeterConnectionError, AmmeterResponseError, AmmeterTimeoutError

MAX_RESPONSE_BYTES = 1024  # a reading is a short number; anything longer is not a valid answer
NUMBER = re.compile(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?")


def parse_reading(data: bytes) -> float:
    text = data.decode("utf-8", errors="replace").strip()
    if not text:
        raise AmmeterResponseError("empty response (unknown command, or the ammeter closed the connection)")
    if not NUMBER.fullmatch(text):
        if text.lower().lstrip("+-") in ("nan", "inf", "infinity"):
            raise AmmeterResponseError(f"not a finite number: {text!r}")
        raise AmmeterResponseError(f"not a number: {text[:40]!r}")
    value = float(text)
    if not math.isfinite(value):
        raise AmmeterResponseError(f"not a finite number: {text!r}")
    return value


class AmmeterClient:
    """Same interface for every ammeter type: one TCP connection per reading, which is how the emulators work.

    `timeout_s` limits the whole reading (connect, send, the complete answer and any retries), not each network
    call, so an ammeter that dribbles its answer byte by byte, or keeps dropping the connection, can't keep the
    client waiting.
    """

    def __init__(self, host: str, port: int, command: bytes, timeout_s: float = 2.0, retries: int = 1):
        self.host = host
        self.port = port
        self.command = command
        self.timeout_s = timeout_s
        self.retries = retries

    @classmethod
    def from_spec(cls, spec, timeout_s: float = 2.0, retries: int = 1) -> "AmmeterClient":
        return cls(spec.host, spec.port, spec.command.encode("utf-8"), timeout_s, retries)

    def measure(self) -> float:
        deadline = time.monotonic() + self.timeout_s  # retries share it, so a reading never takes longer
        for attempt in range(self.retries + 1):
            try:
                return self._request(deadline)
            except AmmeterConnectionError:
                if attempt == self.retries or time.monotonic() + 0.05 >= deadline:
                    raise
                time.sleep(0.05)

    def _request(self, deadline: float) -> float:
        address = f"{self.host}:{self.port}"
        try:
            conn = socket.create_connection((self.host, self.port), timeout=max(deadline - time.monotonic(), 0.01))
        except OSError as e:  # a timeout, too: on Windows a refused connection only fails after about 2 s
            raise AmmeterConnectionError(f"cannot reach {address}: {e.strerror or e}") from None
        data = b""
        try:
            with conn:
                conn.settimeout(_remaining(deadline))
                conn.sendall(self.command)
                while True:
                    conn.settimeout(_remaining(deadline))
                    chunk = conn.recv(1024)
                    if not chunk:
                        break
                    data += chunk
                    if len(data) > MAX_RESPONSE_BYTES:
                        raise AmmeterResponseError(f"answer from {address} is longer than {MAX_RESPONSE_BYTES} bytes")
        except socket.timeout:
            raise AmmeterTimeoutError(f"no complete answer from {address} within {self.timeout_s:g} s") from None
        except OSError as e:
            raise AmmeterConnectionError(f"cannot reach {address}: {e.strerror or e}") from None
        return parse_reading(data)


def _remaining(deadline: float) -> float:
    left = deadline - time.monotonic()
    if left <= 0:
        raise socket.timeout
    return left
