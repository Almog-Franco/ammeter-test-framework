import os
import random
import socket
import struct
import time

from src.settings import AmmeterSpec

ENTES = AmmeterSpec("entes", 5002, "MEASURE_ENTES -get_data", expected_min=5, expected_max=200, expected_mean=68.75,
                    expected_geo_mean=55.51, expected_log_std=0.7012)


def entes_readings(n, seed=1):
    """Readings drawn the way the ENTES emulator draws them: B * K with uniform inputs."""
    rng = random.Random(seed)
    return [rng.uniform(0.01, 0.1) * rng.uniform(500, 2000) for _ in range(n)]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def answer(data: bytes, delay_s: float = 0.0):
    def handle(conn):
        conn.recv(1024)
        time.sleep(delay_s)
        conn.sendall(data)
    return handle


def dribble(data: bytes, every_s: float):
    """Sends the answer one byte at a time."""
    def handle(conn):
        conn.recv(1024)
        for byte in data:
            conn.sendall(bytes([byte]))
            time.sleep(every_s)
    return handle


def reset(conn):
    """Drops a connection with a TCP reset (RST) instead of a normal close."""
    linger = struct.pack("HH" if os.name == "nt" else "ii", 1, 0)
    conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, linger)
