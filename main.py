import sys
import threading

from Ammeters.client import request_current_from_ammeter
from src.emulators import EMULATORS, wait_for_port
from src.settings import load_settings


def run_emulator(emulator_type: str, port: int):
    EMULATORS[emulator_type](port).start_server()


if __name__ == "__main__":
    # Greenlee prints 'Ω', which Windows can't encode when the output is redirected to a file
    sys.stdout.reconfigure(errors="replace")
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config/config.yaml"
    ammeters = load_settings(config_path).ammeters.values()

    # Start each ammeter in a separate thread, on the port and with the command from config.yaml
    for spec in ammeters:
        if spec.emulator:
            threading.Thread(target=run_emulator, args=(spec.emulator, spec.port), daemon=True).start()

    for spec in ammeters:
        if not wait_for_port(spec.host, spec.port):
            print(f"{spec.name}: nothing is listening on port {spec.port}")
            continue
        request_current_from_ammeter(spec.port, spec.command.encode())
