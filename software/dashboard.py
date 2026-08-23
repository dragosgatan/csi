"""Serve a live browser dashboard for the CSI collector."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket

if __package__:
    from .capture import CsiCollector
    from . import push
else:
    from capture import CsiCollector
    import push


HTTP_LISTEN_IP = "0.0.0.0"
HTTP_PORT = 8080
PAGE_PATH = Path(__file__).with_name("index.html")
MONITOR_PATH = Path(__file__).with_name("monitor.html")
MOBILE_PATH = Path(__file__).with_name("mobile.html")
# the service worker must be served from the root to control the whole origin.
WORKER_PATH = Path(__file__).with_name("sw.js")
MANIFEST_PATH = Path(__file__).with_name("manifest.webmanifest")
ICON_PATH = Path(__file__).with_name("icon.svg")
ICON_PNG_PATHS = {
    "/icon-192.png": Path(__file__).with_name("icon-192.png"),
    "/icon-512.png": Path(__file__).with_name("icon-512.png"),
}


def load_page(path=PAGE_PATH):
    """Read a browser UI from the files next to this script."""
    return path.read_bytes()


class DualStackServer(ThreadingHTTPServer):
    """Accept IPv4 and IPv6 on one socket.

    On Windows "localhost" resolves to ::1 first; against an IPv4-only socket
    every request then pays a ~2 s connect retry, which makes the dashboard
    look frozen.
    """

    address_family = socket.AF_INET6
    daemon_threads = True

    def server_bind(self):
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except OSError:
            pass
        return super().server_bind()


def make_server(handler, port=None):
    """Dual-stack where the OS allows it, IPv4-only where it does not."""
    port = HTTP_PORT if port is None else port
    try:
        return DualStackServer(("::", port), handler)
    except OSError:
        return ThreadingHTTPServer((HTTP_LISTEN_IP, port), handler)


class DashboardHandler(BaseHTTPRequestHandler):
    collector = None
    vapid_public_key = ""

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/":
            self._send_response(200, "text/html; charset=utf-8", load_page())
            return
        if path == "/monitor":
            self._send_response(200, "text/html; charset=utf-8", load_page(MONITOR_PATH))
            return
        if path == "/mobile":
            self._send_response(200, "text/html; charset=utf-8", load_page(MOBILE_PATH))
            return
        if path == "/sw.js":
            self._send_response(200, "text/javascript; charset=utf-8", load_page(WORKER_PATH))
            return
        if path == "/manifest.webmanifest":
            self._send_response(200, "application/manifest+json", load_page(MANIFEST_PATH))
            return
        if path in ICON_PNG_PATHS:
            self._send_response(200, "image/png", load_page(ICON_PNG_PATHS[path]))
            return
        if path == "/icon.svg":
            self._send_response(200, "image/svg+xml", load_page(ICON_PATH))
            return
        if path == "/api/vapid":
            payload = json.dumps({"key": self.vapid_public_key}).encode("utf-8")
            self._send_response(200, "application/json; charset=utf-8", payload)
            return
        if path == "/api/data":
            light = "light=1" in query
            snapshot = self.collector.get_snapshot(include_history=not light)
            payload = json.dumps(snapshot).encode("utf-8")
            self._send_response(200, "application/json; charset=utf-8", payload)
            return
        self._send_response(404, "text/plain; charset=utf-8", b"not found\n")

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path.split("?", 1)[0] == "/api/calibrate":
            self.collector.calibrate()
            payload = json.dumps(
                {
                    "ok": True,
                    "calibrated_at": self.collector.get_snapshot()["calibrated_at"],
                }
            ).encode("utf-8")
            self._send_response(200, "application/json; charset=utf-8", payload)
            return
        if path == "/api/subscribe":
            body = self._read_json()
            if body is None:
                return
            push.add_subscription(body)
            self._send_json({"ok": True})
            return
        if path == "/api/arm":
            body = self._read_json()
            if body is None:
                return
            if body.get("active"):
                self.collector.intruder.arm()
            else:
                self.collector.intruder.disarm()
            self._send_json(self.collector.intruder.snapshot())
            return
        if path == "/api/test-alarm":
            self.collector.intruder.trip_now()
            self._send_json(self.collector.intruder.snapshot())
            return
        self._send_response(404, "text/plain; charset=utf-8", b"not found\n")

    def _read_json(self):
        """Parse a JSON request body, answering 400 itself if it cannot."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length))
        except (TypeError, ValueError) as error:
            print(f"[dashboard] bad request body: {error}")
            self._send_json({"ok": False, "error": "bad json"}, status=400)
            return None

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self._send_response(status, "application/json; charset=utf-8", body)

    def _send_response(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format_string, *args):
        print(f"[dashboard] {self.address_string()} - {format_string % args}")


def main():
    """Start CSI collection and serve the dashboard until interrupted."""
    collector = CsiCollector()
    collector.start()

    # every intruder alarm pushes once, on the rising edge
    vapid_key = push.load_or_create_key()
    collector.intruder.on_alarm = lambda snapshot: push.send(
        {
            "title": "Intruder detected",
            "body": "Movement in a room that should be empty.",
            "state": snapshot,
        }
    )

    DashboardHandler.collector = collector
    DashboardHandler.vapid_public_key = push.public_key_b64(vapid_key)
    server = make_server(DashboardHandler)
    print(f"[dashboard] open http://localhost:{HTTP_PORT}          (links + heatmaps)")
    print(f"[dashboard] open http://localhost:{HTTP_PORT}/monitor  (room map + collapse)")
    print(f"[dashboard] open http://localhost:{HTTP_PORT}/mobile   (phone: arm + alarm)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[dashboard] stopping")
    finally:
        server.server_close()
        collector.stop()


if __name__ == "__main__":
    main()
