import copy
import socket
import threading
import time
from dataclasses import replace

import pytest
import yaml

from src.emulators import EmulatorProcess
from src.settings import PROJECT_ROOT, load_settings
from tests.helpers import free_port as _free_port

REAL_CONFIG = yaml.safe_load((PROJECT_ROOT / "config" / "config.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def free_port():
    """Call it to get a port that nothing listens on."""
    return _free_port


@pytest.fixture(scope="session")
def ammeters(tmp_path_factory):
    """The ammeters from config.yaml, running on free ports for the whole session."""
    specs = {name: replace(spec, port=_free_port()) for name, spec in load_settings().ammeters.items()}
    with EmulatorProcess(list(specs.values()), tmp_path_factory.mktemp("emulators") / "emulators.log"):
        yield specs


@pytest.fixture
def windows_loopback(monkeypatch):
    """Refused connections behave as on Windows, which only reports the refusal after about 2 s."""
    real = socket.create_connection

    def slow_refusal(address, timeout=None, **kwargs):
        try:
            return real(address, timeout, **kwargs)
        except ConnectionRefusedError:
            if timeout is not None and timeout < 2.0:
                time.sleep(timeout)
                raise socket.timeout("timed out") from None
            time.sleep(2.0)
            raise

    monkeypatch.setattr(socket, "create_connection", slow_refusal)


@pytest.fixture
def config(tmp_path):
    """A copy of config.yaml as a dict, storing results in a temporary folder. Edit it, then write_config()."""
    raw = copy.deepcopy(REAL_CONFIG)
    raw["result_management"]["results_dir"] = str(tmp_path / "results")
    return raw


@pytest.fixture
def write_config(tmp_path):
    def write(raw: dict) -> str:
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
        return str(path)
    return write


@pytest.fixture
def tcp_server():
    """Starts a local TCP server that handles connection i with handlers[i]; the last handler repeats."""
    servers = []

    def start(*handlers) -> int:
        server = socket.create_server(("127.0.0.1", 0))
        servers.append(server)

        def serve():
            count = 0
            while True:
                try:
                    conn, _ = server.accept()
                except OSError:
                    return
                handler = handlers[min(count, len(handlers) - 1)]
                count += 1
                with conn:
                    try:
                        handler(conn)
                    except OSError:
                        pass

        threading.Thread(target=serve, daemon=True).start()
        return server.getsockname()[1]

    yield start
    for server in servers:
        server.close()
