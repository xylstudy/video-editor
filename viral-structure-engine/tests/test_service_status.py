from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
from threading import Thread

from scripts.service_status import service_status


@contextmanager
def serving(routes):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = routes.get(self.path)
            self.send_response(200 if body is not None else 404)
            self.end_headers()
            self.wfile.write((body or "not found").encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_unused_port_can_be_started():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    assert service_status("backend", port) == "available"


def test_existing_backend_is_reused_without_external_proxy(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    routes = {
        "/api/health": json.dumps({"status": "ok"}),
        "/openapi.json": json.dumps({"info": {"title": "Video Claw Web API"}, "description": "x" * 70000}),
    }
    with serving(routes) as port:
        assert service_status("backend", port) == "running"


def test_other_application_is_not_reused_as_backend():
    routes = {
        "/api/health": json.dumps({"status": "ok"}),
        "/openapi.json": json.dumps({"info": {"title": "Another API"}}),
    }
    with serving(routes) as port:
        assert service_status("backend", port) == "conflict"


def test_existing_frontend_is_reused_and_other_frontend_is_rejected():
    page = '<title>Video Claw</title><script src="/src/main.jsx"></script>'
    with serving({"/": page}) as port:
        assert service_status("frontend", port) == "running"
    with serving({"/": page.replace("Video Claw", "Another app")}) as port:
        assert service_status("frontend", port) == "conflict"


def test_listener_that_does_not_serve_http_is_not_treated_as_available():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        assert service_status("backend", listener.getsockname()[1], timeout=0.1) == "conflict"
