"""Identify an existing local Video Claw service before launching another one."""
from __future__ import annotations

import argparse
import json
import re
import socket
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener


PORTS = {"backend": 8000, "frontend": 5173}
EXIT_CODES = {"available": 0, "running": 10, "conflict": 20}


def service_status(service: str, port: int | None = None, timeout: float = 2) -> str:
    """Return available, running (our healthy service), or conflict."""
    port = PORTS[service] if port is None else port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            pass
        else:
            return "available"

    # Local health checks must not pass through a configured external proxy.
    opener = build_opener(ProxyHandler({}))

    def read(path: str) -> str:
        with opener.open(f"http://127.0.0.1:{port}{path}", timeout=timeout) as response:
            if response.status != 200:
                raise ValueError("Service did not return HTTP 200")
            return response.read(1024 * 1024).decode("utf-8")

    try:
        if service == "backend":
            health = json.loads(read("/api/health"))
            api = json.loads(read("/openapi.json"))
            matches = isinstance(health, dict) and isinstance(api, dict)
            matches = matches and health.get("status") == "ok" and isinstance(api.get("info"), dict)
            matches = matches and api["info"].get("title") == "Video Claw Web API"
        else:
            page = read("/")
            matches = bool(re.search(r"<title>\s*Video Claw\s*</title>", page, re.IGNORECASE))
            matches = matches and "/src/main.jsx" in page
    except (OSError, URLError, ValueError):
        return "conflict"
    return "running" if matches else "conflict"


def main() -> int:
    parser = argparse.ArgumentParser(description="Check existing Video Claw services")
    parser.add_argument("service", choices=PORTS)
    args = parser.parse_args()
    state = service_status(args.service)
    port = PORTS[args.service]
    if state == "running":
        print(f"[OK] {args.service}: Video Claw is already running on port {port}; reusing it.")
    elif state == "available":
        print(f"[OK] {args.service}: port {port} is available.")
    else:
        print(f"[FAIL] Port {port} is occupied or unavailable, and a healthy Video Claw {args.service} was not identified.")
        print("Close the program using this port, or wait for the existing service to finish starting, then retry.")
    return EXIT_CODES[state]


if __name__ == "__main__":
    raise SystemExit(main())
