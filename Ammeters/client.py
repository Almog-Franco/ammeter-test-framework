from socket import socket, AF_INET, SOCK_STREAM


def request_current_from_ammeter(port: int, command: bytes, timeout: float = 5.0):
    with socket(AF_INET, SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(('localhost', port))
        s.sendall(command)
        data = s.recv(1024)
        if data:
            print(f"Received current measurement from port {port}: {data.decode('utf-8')} A")
            return float(data)
        else:
            print("No data received.")
            return None
