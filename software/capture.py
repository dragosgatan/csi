"""Collect CSI packets from the receiver boards over UDP."""

from collections import deque
import socket
import threading
import time

import numpy as np

if __package__:
    from .filter_pipeline import CSIFilterPipeline
else:
    from filter_pipeline import CSIFilterPipeline


LISTEN_IP = "0.0.0.0"
LISTEN_PORT = 6767

SC_FIRST = 6
SC_LAST = 58

# these subcarriers are null, DC, or guard tones and do not carry useful CSI.
NULL_SC_LOW = 28
NULL_SC_HIGH = 36

HISTORY_LEN = 150
MAX_NODES = 4
AMP_VMAX = 60
FILTER_WINDOW_SIZE = 30
FILTER_EMA_ALPHA = 0.15
FILTER_PCA_COMPONENTS = 1
FILTER_VARIANCE_SCALE = 100.0


def parse_packet(data: bytes):
    """Parse node_id,timestamp,rssi,len, followed by signed CSI bytes."""
    comma_count = 0
    header_end = None
    for index, byte in enumerate(data):
        if byte == 0x2C:
            comma_count += 1
            if comma_count == 4:
                header_end = index
                break

    if header_end is None:
        return None

    header = data[:header_end].decode("ascii", errors="ignore")
    parts = header.split(",")
    if len(parts) != 4:
        return None

    try:
        node_id = int(parts[0])
        rssi = int(parts[2])
        length = int(parts[3])
    except ValueError:
        return None

    if node_id < 0 or length < 0:
        return None

    raw = data[header_end + 1:header_end + 1 + length]
    if len(raw) != length:
        return None

    signed_values = [value if value < 128 else value - 256 for value in raw]
    return node_id, rssi, signed_values


def extract_active_iq(raw_values):
    """Extract the active interleaved I/Q values from one ESP32 CSI frame."""
    required_length = (SC_LAST + 1) * 2
    if len(raw_values) < required_length:
        return None

    active_iq = []
    for subcarrier in range(SC_FIRST, SC_LAST + 1):
        if NULL_SC_LOW <= subcarrier <= NULL_SC_HIGH:
            continue

        active_iq.extend(
            (raw_values[subcarrier * 2], raw_values[subcarrier * 2 + 1])
        )

    return active_iq


def calculate_amplitudes(raw_values):
    """Convert active interleaved CSI I/Q values into amplitudes."""
    active_iq = extract_active_iq(raw_values)
    if active_iq is None:
        return None

    amplitudes = []
    for index in range(0, len(active_iq), 2):
        i_value = active_iq[index]
        q_value = active_iq[index + 1]
        amplitudes.append((i_value * i_value + q_value * q_value) ** 0.5)

    return amplitudes


class CsiCollector:
    """Receive CSI in the background and expose a safe browser-ready snapshot."""

    def __init__(
        self,
        listen_ip=LISTEN_IP,
        listen_port=LISTEN_PORT,
        history_len=HISTORY_LEN,
        max_nodes=MAX_NODES,
        filter_window_size=FILTER_WINDOW_SIZE,
        filter_ema_alpha=FILTER_EMA_ALPHA,
        filter_pca_components=FILTER_PCA_COMPONENTS,
        filter_variance_scale=FILTER_VARIANCE_SCALE,
    ):
        self.listen_ip = listen_ip
        self.listen_port = listen_port
        self.history_len = history_len
        self.max_nodes = max_nodes
        self.filter_window_size = filter_window_size
        self.filter_ema_alpha = filter_ema_alpha
        self.filter_pca_components = filter_pca_components
        self.filter_variance_scale = filter_variance_scale

        self._nodes = {}
        self._packet_count = 0
        self._last_error = None
        self._socket = None
        self._thread = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def start(self):
        """Start the UDP listener once and return immediately."""
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def stop(self):
        """Ask the listener to stop and wait briefly for its socket to close."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2)

    def _listen(self):
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socket.settimeout(0.5)

        try:
            udp_socket.bind((self.listen_ip, self.listen_port))
        except OSError as error:
            with self._lock:
                self._last_error = str(error)
            udp_socket.close()
            print(f"[capture] could not listen on UDP {self.listen_port}: {error}")
            return

        with self._lock:
            self._socket = udp_socket
            self._last_error = None

        print(f"[capture] listening on UDP {self.listen_ip}:{self.listen_port}")

        try:
            while not self._stop_event.is_set():
                try:
                    data, address = udp_socket.recvfrom(2048)
                except socket.timeout:
                    continue
                except OSError as error:
                    if not self._stop_event.is_set():
                        with self._lock:
                            self._last_error = str(error)
                        print(f"[capture] UDP receive error: {error}")
                    break

                self._handle_packet(data, address[0])
        finally:
            udp_socket.close()
            with self._lock:
                self._socket = None

    def _handle_packet(self, data, sender_ip):
        parsed_packet = parse_packet(data)
        if parsed_packet is None:
            return

        node_id, rssi, raw_values = parsed_packet
        active_iq = extract_active_iq(raw_values)
        if active_iq is None:
            return

        now = time.time()
        with self._lock:
            self._packet_count += 1
            if node_id not in self._nodes:
                if len(self._nodes) >= self.max_nodes:
                    return
                self._nodes[node_id] = {
                    "node_id": node_id,
                    "ip": sender_ip,
                    "history": deque(maxlen=self.history_len),
                    "pipeline": CSIFilterPipeline(
                        window_size=self.filter_window_size,
                        ema_alpha=self.filter_ema_alpha,
                        pca_components=self.filter_pca_components,
                        variance_scale=self.filter_variance_scale,
                    ),
                    "rssi": rssi,
                    "packet_count": 0,
                    "last_seen": now,
                    "motion_score": 0.0,
                    "motion_variance": 0.0,
                }

            node = self._nodes[node_id]
            try:
                motion_score = node["pipeline"].process_frame(active_iq)
            except (TypeError, ValueError, np.linalg.LinAlgError) as error:
                self._last_error = f"CSI filter error for node {node_id}: {error}"
                print(f"[capture] {self._last_error}")
                return

            filtered_amplitudes = node["pipeline"].latest_filtered_amplitudes
            if filtered_amplitudes is None:
                return

            amplitudes = filtered_amplitudes[-1].tolist()
            node["history"].append(amplitudes)
            node["ip"] = sender_ip
            node["rssi"] = rssi
            node["packet_count"] += 1
            node["last_seen"] = now
            node["motion_score"] = motion_score
            node["motion_variance"] = node["pipeline"].latest_motion_variance

    def get_snapshot(self):
        """Return a JSON-serializable copy of the latest collected CSI data."""
        with self._lock:
            nodes = []
            for node_id, node in self._nodes.items():
                history = [list(row) for row in node["history"]]
                nodes.append(
                    {
                        "node_id": node_id,
                        "ip": node["ip"],
                        "rssi": node["rssi"],
                        "packet_count": node["packet_count"],
                        "last_seen": node["last_seen"],
                        "history": history,
                        "amplitudes": history[-1] if history else [],
                        "motion_score": node["motion_score"],
                        "motion_variance": node["motion_variance"],
                    }
                )

            return {
                "listening": self._socket is not None,
                "error": self._last_error,
                "packet_count": self._packet_count,
                "amplitude_max": AMP_VMAX,
                "filter": {
                    "window_size": self.filter_window_size,
                    "ema_alpha": self.filter_ema_alpha,
                    "pca_components": self.filter_pca_components,
                    "variance_scale": self.filter_variance_scale,
                },
                "subcarriers": [
                    subcarrier
                    for subcarrier in range(SC_FIRST, SC_LAST + 1)
                    if not NULL_SC_LOW <= subcarrier <= NULL_SC_HIGH
                ],
                "nodes": nodes,
            }


def main():
    """Run collection without a UI, useful for checking the UDP input."""
    collector = CsiCollector()
    collector.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        collector.stop()


if __name__ == "__main__":
    main()
