"""Serve a live browser dashboard for the CSI collector."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket

if __package__:
    from .capture import CsiCollector
else:
    from capture import CsiCollector


HTTP_LISTEN_IP = "0.0.0.0"
HTTP_PORT = 8080
PAGE_PATH = Path(__file__).with_name("index.html")
MONITOR_PATH = Path(__file__).with_name("monitor.html")


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

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/":
            self._send_response(200, "text/html; charset=utf-8", load_page())
            return
        if path == "/monitor":
            self._send_response(200, "text/html; charset=utf-8", load_page(MONITOR_PATH))
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
        self._send_response(404, "text/plain; charset=utf-8", b"not found\n")

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

    DashboardHandler.collector = collector
    server = make_server(DashboardHandler)
    print(f"[dashboard] open http://localhost:{HTTP_PORT}          (links + heatmaps)")
    print(f"[dashboard] open http://localhost:{HTTP_PORT}/monitor  (room map + collapse)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[dashboard] stopping")
    finally:
        server.server_close()
        collector.stop()


if __name__ == "__main__":
    main()
