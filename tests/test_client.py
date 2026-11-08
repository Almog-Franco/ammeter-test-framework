import gc
import time
import warnings

import pytest

from Ammeters.client import request_current_from_ammeter
from src.client import AmmeterClient, parse_reading
from src.errors import AmmeterConnectionError, AmmeterResponseError, AmmeterTimeoutError
from src.settings import AmmeterSpec
from tests.helpers import answer, dribble, reset


@pytest.mark.parametrize("data, expected", [
    (b"0.5", 0.5),
    (b"  12.75\n", 12.75),
    (b"1e-3", 0.001),
    (b"-3", -3.0),
    (b"+.5", 0.5),
    (b"0.004912345678912", 0.004912345678912),  # full resolution
])
def test_valid_readings(data, expected):
    """Well-formed replies (spaces, signs, exponents) are read as numbers, at full resolution."""
    assert parse_reading(data) == expected


@pytest.mark.parametrize("data, message", [
    (b"", "empty response"),
    (b"   ", "empty response"),
    (b"ERR#42", "not a number: 'ERR#42'"),
    (b".", "not a number"),
    (b"nan", "not a finite number"),
    (b"inf", "not a finite number"),
    (b"\xff\xfe", "not a number"),
    (b"1_000", "not a number"),  # Python's float() would accept this
    (b"0x10", "not a number"),
    (b"12.5 A", "not a number"),
    (b"-Infinity", "not a finite number"),
    (b"1e999", "not a finite number"),
    ("é".encode("utf-8"), "é"),
])
def test_invalid_readings(data, message):
    """Empty, non-numeric, non-finite or oddly formatted replies, including ones Python's float() would accept,
    raise AmmeterResponseError with a message that quotes the reply as it was."""
    with pytest.raises(AmmeterResponseError, match=message):
        parse_reading(data)


def test_long_garbage_is_quoted_briefly():
    """A long garbage reply is quoted in the error message, but cut short."""
    with pytest.raises(AmmeterResponseError) as error:
        parse_reading(b"x" * 200)
    assert "'" + "x" * 30 in str(error.value) and len(str(error.value)) < 80


def test_reads_a_value_and_closes_the_socket(tcp_server, capsys):
    """A normal reply is read, also when it arrives in pieces, by both the new client and the original one, and
    the original one now has a timeout. No sockets are left open."""
    port = tcp_server(answer(b"1.5"))
    assert AmmeterClient("127.0.0.1", port, b"MEASURE").measure() == 1.5
    in_pieces = tcp_server(dribble(b"1.5", every_s=0.05))
    assert AmmeterClient("127.0.0.1", in_pieces, b"MEASURE", timeout_s=1.0).measure() == 1.5
    assert request_current_from_ammeter(tcp_server(answer(b"2.5")), b"MEASURE") == 2.5  # the original client
    with pytest.raises(TimeoutError):
        request_current_from_ammeter(tcp_server(answer(b"2.5", delay_s=2.0)), b"MEASURE", timeout=0.3)

    gc.collect()  # so earlier tests' leftovers can't show up below
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ResourceWarning)
        for _ in range(3):
            AmmeterClient("127.0.0.1", port, b"M").measure()
        gc.collect()
    assert not [w for w in caught if "socket" in str(w.message)]


@pytest.mark.parametrize("slow_refusal", [False, True], ids=["refused at once", "refused slowly, as on Windows"])
def test_unreachable_ammeter(free_port, tcp_server, request, slow_refusal):
    """An ammeter that isn't listening gives AmmeterConnectionError, naming the address and the reason, also when
    the refusal comes too late, as on Windows. The configured host is really used, also through from_spec()."""
    if slow_refusal:
        request.getfixturevalue("windows_loopback")
    client = AmmeterClient("127.0.0.1", free_port(), b"MEASURE", timeout_s=0.5, retries=1)
    with pytest.raises(AmmeterConnectionError, match="cannot reach"):
        client.measure()
    port = free_port()
    with pytest.raises(AmmeterConnectionError, match=rf"cannot reach 127\.0\.0\.1:{port}: \w+"):
        AmmeterClient("127.0.0.1", port, b"M", timeout_s=0.5, retries=0).measure()

    port = tcp_server(answer(b"1.5"))  # listens on 127.0.0.1 only, so the configured host must be used
    with pytest.raises(AmmeterConnectionError):
        AmmeterClient("::1", port, b"M", timeout_s=1.0, retries=0).measure()
    with pytest.raises(AmmeterConnectionError):
        AmmeterClient.from_spec(AmmeterSpec("x", port, "M", host="::1"), timeout_s=1.0, retries=0).measure()


def test_timeout_covers_the_whole_request(tcp_server):
    """The timeout limits the whole request, not each network call, so an ammeter that answers late or byte by
    byte can't keep the client waiting much longer than the timeout."""
    port = tcp_server(answer(b"1.0", delay_s=1.0))
    with pytest.raises(AmmeterTimeoutError, match="within 0.2 s"):
        AmmeterClient("127.0.0.1", port, b"MEASURE", timeout_s=0.2).measure()

    port = tcp_server(dribble(b"12.5000000", every_s=0.15))  # each byte in time, the whole answer not
    start = time.monotonic()
    with pytest.raises(AmmeterTimeoutError, match="no complete answer"):
        AmmeterClient("127.0.0.1", port, b"MEASURE", timeout_s=0.5, retries=0).measure()
    assert time.monotonic() - start < 0.5 + 0.25

    port = tcp_server(dribble(b"1" * 100, every_s=0.1))
    start = time.monotonic()
    with pytest.raises(AmmeterTimeoutError):
        AmmeterClient("127.0.0.1", port, b"MEASURE", timeout_s=1.0, retries=0).measure()
    assert 0.9 <= time.monotonic() - start < 1.3

    fast = tcp_server(dribble(b"1" * 1000, every_s=0.02))  # a byte every 20 ms, never finishing in time
    start = time.monotonic()
    with pytest.raises(AmmeterTimeoutError):
        AmmeterClient("127.0.0.1", fast, b"MEASURE", timeout_s=0.3, retries=0).measure()
    assert time.monotonic() - start < 1.0


def _endless(conn):
    conn.recv(1024)
    while True:
        conn.sendall(b"1" * 512)
        time.sleep(0.01)


def test_oversized_answers_are_rejected(tcp_server):
    """Replies over 1024 bytes are rejected, also endless ones, without waiting for the timeout.
    A reply of exactly 1024 bytes is still accepted."""
    with pytest.raises(AmmeterResponseError, match="longer than 1024 bytes"):
        AmmeterClient("127.0.0.1", tcp_server(answer(b"1" * 5000)), b"MEASURE").measure()
    start = time.monotonic()
    with pytest.raises(AmmeterResponseError, match="longer than 1024 bytes"):
        AmmeterClient("127.0.0.1", tcp_server(_endless), b"MEASURE", timeout_s=2.0, retries=0).measure()
    assert time.monotonic() - start < 1.0
    biggest = b"12.5" + b"0" * 1020
    assert AmmeterClient("127.0.0.1", tcp_server(answer(biggest)), b"MEASURE").measure() == 12.5
    with pytest.raises(AmmeterResponseError, match="longer than"):
        AmmeterClient("127.0.0.1", tcp_server(answer(biggest + b"0")), b"MEASURE").measure()


def _counting(handler, connections):
    def handle(conn):
        connections.append(1)
        handler(conn)
    return handle


def _half_then_reset(conn):
    conn.recv(1024)
    conn.sendall(b"12")
    time.sleep(0.1)
    reset(conn)


def _reset_after(seconds):
    def handle(conn):
        conn.recv(1024)
        time.sleep(seconds)
        reset(conn)
    return handle


def test_only_connection_errors_are_retried(tcp_server):
    """Connection errors are retried as many times as configured, with short pauses, and all within the one
    timeout. Half an answer is never used, and timeouts and bad answers are not retried."""
    assert AmmeterClient("127.0.0.1", tcp_server(reset, answer(b"2.5")), b"MEASURE", retries=1).measure() == 2.5
    with pytest.raises(AmmeterConnectionError):
        AmmeterClient("127.0.0.1", tcp_server(reset), b"MEASURE", retries=0).measure()
    with pytest.raises(AmmeterConnectionError):  # half an answer is not used
        AmmeterClient("127.0.0.1", tcp_server(_half_then_reset), b"M", retries=0).measure()

    for retries in (0, 2):
        connections = []
        port = tcp_server(_counting(reset, connections))
        with pytest.raises(AmmeterConnectionError):
            AmmeterClient("127.0.0.1", port, b"M", retries=retries).measure()
        assert len(connections) == retries + 1
    start = time.monotonic()
    with pytest.raises(AmmeterConnectionError):
        AmmeterClient("127.0.0.1", tcp_server(reset), b"M", timeout_s=2.0, retries=5).measure()
    assert time.monotonic() - start < 1.0  # short pauses between attempts
    start = time.monotonic()
    with pytest.raises((AmmeterConnectionError, AmmeterTimeoutError)):
        AmmeterClient("127.0.0.1", tcp_server(_reset_after(0.3)), b"M", timeout_s=0.5, retries=5).measure()
    assert time.monotonic() - start < 0.5 + 0.25  # the retries share the timeout instead of getting one each

    start = time.monotonic()
    with pytest.raises(AmmeterTimeoutError):
        AmmeterClient("127.0.0.1", tcp_server(answer(b"1.0", delay_s=2.0)), b"M", timeout_s=0.5, retries=1).measure()
    assert time.monotonic() - start < 0.85  # a timeout is not retried
    with pytest.raises(AmmeterResponseError):  # nor is a bad answer
        AmmeterClient("127.0.0.1", tcp_server(answer(b"garbage"), answer(b"1.5")), b"M", retries=1).measure()
