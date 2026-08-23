"""Serve a live browser dashboard for the CSI collector."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path

if __package__:
    from .capture import CsiCollector
else:
    from capture import CsiCollector


HTTP_LISTEN_IP = "0.0.0.0"
HTTP_PORT = 8080
PAGE_PATH = Path(__file__).with_name("index.html")


def load_page():
    """Read the browser UI from the file next to this script."""
    return PAGE_PATH.read_bytes()


class DashboardHandler(BaseHTTPRequestHandler):
    collector = None

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._send_response(200, "text/html; charset=utf-8", load_page())
            return
        if path == "/api/data":
            payload = json.dumps(self.collector.get_snapshot()).encode("utf-8")
            self._send_response(200, "application/json; charset=utf-8", payload)
            return
        self._send_response(404, "text/plain; charset=utf-8", b"not found\n")

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/calibrate":
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
    server = ThreadingHTTPServer((HTTP_LISTEN_IP, HTTP_PORT), DashboardHandler)
    print(f"[dashboard] open http://localhost:{HTTP_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[dashboard] stopping")
    finally:
        server.server_close()
        collector.stop()


if __name__ == "__main__":
    main()
