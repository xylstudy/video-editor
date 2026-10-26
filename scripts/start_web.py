"""Windows double-click launcher with durable logs and readiness checks."""
from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
import webbrowser

if __package__:
    from .service_status import PORTS, service_status
else:
    from service_status import PORTS, service_status

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".local"


def refresh_path():
    """Pick up installer PATH changes without CMD's 8191-character expansion."""
    if os.name != "nt":
        return
    import winreg
    entries = [os.environ.get("PATH", "")]
    for hive, key_name in (
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        (winreg.HKEY_CURRENT_USER, "Environment"),
    ):
        try:
            with winreg.OpenKey(hive, key_name) as key:
                entries.append(winreg.QueryValueEx(key, "Path")[0])
        except OSError:
            pass
    paths, seen = [], set()
    for part in os.path.expandvars(";".join(entries)).split(";"):
        part = part.strip().strip('"')
        if part and part.casefold() not in seen:
            paths.append(part)
            seen.add(part.casefold())
    os.environ["PATH"] = ";".join(paths)


def launch(command, cwd, log_path):
    options = {}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    environment = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    with log_path.open("ab") as output:
        output.write(f"\n--- launch {datetime.now().isoformat(timespec='seconds')} ---\n".encode())
        output.flush()
        return subprocess.Popen(command, cwd=str(cwd), env=environment, stdin=subprocess.DEVNULL,
                                stdout=output, stderr=subprocess.STDOUT, **options)


def wait_for_service(name, process=None, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if service_status(name, timeout=.5) == "running":
            return
        if process is not None and process.poll() is not None:
            raise RuntimeError(f"{name} exited with code {process.returncode}; see {STATE / (name + '.log')}")
        time.sleep(.3)
    raise RuntimeError(f"{name} was not ready on port {PORTS[name]} after {timeout}s; see {STATE / (name + '.log')}")


def run(args, log):
    refresh_path()
    log("Checking the runtime environment...")
    checked = subprocess.run([sys.executable, "-u", str(ROOT / "scripts/preflight.py"), "--web"],
                             cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             encoding="utf-8", errors="replace", timeout=90)
    log(checked.stdout.rstrip())
    if checked.returncode:
        raise RuntimeError("Environment check failed. Run setup_windows.ps1 from the project root.")
    if args.check:
        return

    states = {name: service_status(name) for name in PORTS}
    for name, state in states.items():
        if state == "conflict":
            # An existing process may still be starting; give it a short grace
            # period without killing or replacing an unidentified program.
            log(f"Port {PORTS[name]} is occupied; checking whether {name} is still starting...")
            try:
                wait_for_service(name, timeout=5)
            except RuntimeError:
                raise RuntimeError(f"Port {PORTS[name]} is occupied by an unrecognized or unhealthy service. Close that program and retry.") from None
            states[name] = "running"

    commands = {
        "backend": ([sys.executable, "-u", "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"], ROOT / "web/backend"),
        "frontend": ([shutil.which("node") or "node", str(ROOT / "web/frontend/node_modules/vite/bin/vite.js"),
                      "--host", "127.0.0.1", "--port", "5173", "--strictPort"], ROOT / "web/frontend"),
    }
    processes = {}
    for name, state in states.items():
        if state == "running":
            log(f"[OK] {name} is already running on port {PORTS[name]}; reusing it.")
        else:
            command, cwd = commands[name]
            processes[name] = launch(command, cwd, STATE / f"{name}.log")
            log(f"Starting {name}, PID {processes[name].pid}; log: {STATE / (name + '.log')}")
    for name in PORTS:
        wait_for_service(name, processes.get(name))
        log(f"[OK] {name} is ready.")
    log("Frontend: http://127.0.0.1:5173")
    log("Backend API: http://127.0.0.1:8000/docs")
    log("Services run in the background. Closing this launcher does not stop them.")
    if not args.no_browser:
        if not webbrowser.open("http://127.0.0.1:5173", new=2):
            log("Could not open the browser automatically; open the Frontend URL above.")


def main():
    parser = argparse.ArgumentParser(description="Start or reuse local Video Claw services")
    parser.add_argument("--check", action="store_true", help="check dependencies without starting services")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    args = parser.parse_args()
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / "start_web.log").open("a", encoding="utf-8") as stream:
        def log(message):
            print(message, flush=True)
            stream.write(message + "\n")
            stream.flush()
        log(f"\n--- Video Claw startup {datetime.now().isoformat(timespec='seconds')} ---")
        try:
            run(args, log)
            return 0
        except Exception as error:
            log(f"[FAIL] {error}")
            stream.write(traceback.format_exc() + "\n")
            log(f"Startup log: {STATE / 'start_web.log'}")
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
