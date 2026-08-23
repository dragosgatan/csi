"""Collect CSI packets from the receiver boards over UDP."""

from collections import deque
from dataclasses import dataclass
import socket
import threading
import time

import numpy as np

if __package__:
    from .collapse import CollapseWatch, link_contrast
    from .intruder import IntruderWatch
    from .filter_pipeline import CSIFilterPipeline
    from .tomography import RadioTomography
else:
    from collapse import CollapseWatch, link_contrast
    from intruder import IntruderWatch
    from filter_pipeline import CSIFilterPipeline
    from tomography import RadioTomography


LISTEN_IP = "0.0.0.0"
LISTEN_PORT = 6767

SC_FIRST = 6
SC_LAST = 58

# these subcarriers are null, DC, or guard tones and do not carry useful CSI.
NULL_SC_LOW = 29
NULL_SC_HIGH = 34

HISTORY_LEN = 150
MAX_LINKS = 32
AMP_VMAX = 60
FILTER_WINDOW_SIZE = 30
FILTER_EMA_ALPHA = 0.15
FILTER_PCA_COMPONENTS = 1
FILTER_VARIANCE_SCALE = 100.0
# keep these IDs in sync with NODE_ID on each mesh board.
NODE_IDS_BY_MAC = {
    "8813BF0DD014": 0,
    "8813BF0BB55C": 1,
    "8813BF0C5840": 2,
    "8813BF0C9DDC": 3,
    "8813BF0BB578": 4,
    "8813BF0C7B28": 5,
}
# positions are keyed by NODE_ID, not MAC address.
NODE_POSITIONS = {
    0: (0.0, 0.0),
    1: (0.0, 3.0),
    2: (5.9, 0.0),
    3: (6.15, 3.05),
    4: (3.8, 0.0),
    5: (3.1, 3.0),
}
ROOM_WIDTH = 6.1
ROOM_HEIGHT = 3.1
GRID_RESOLUTION = 80
ELLIPSE_LAMBDA = 0.5
LINK_SCORE_SCALE = 1.0


@dataclass(frozen=True)
class ParsedPacket:
    """One mesh CSI packet and the identities of its ordered endpoints."""

    rx_mac: str
    tx_mac: str
    rssi: int
    raw_values: list[int]


def parse_packet(data: bytes):
    """Parse self_mac,tx_mac,timestamp,rssi,len, followed by CSI bytes."""
    comma_count = 0
    header_end = None
    for index, byte in enumerate(data):
        if byte == 0x2C:
            comma_count += 1
            if comma_count == 5:
                header_end = index
                break

    if header_end is None:
        return None

    header = data[:header_end].decode("ascii", errors="ignore")
    parts = header.split(",")
    if len(parts) != 5:
        return None

    try:
        rx_mac = _normalize_mac(parts[0])
        tx_mac = _normalize_mac(parts[1])
        int(parts[2])
        rssi = int(parts[3])
        length = int(parts[4])
    except ValueError:
        return None

    if length < 0:
        return None

    raw = data[header_end + 1:header_end + 1 + length]
    if len(raw) != length:
        return None

    signed_values = [value if value < 128 else value - 256 for value in raw]
    return ParsedPacket(rx_mac, tx_mac, rssi, signed_values)


def _normalize_mac(mac: str) -> str:
    """Normalize a MAC address and reject malformed packet identities."""
    normalized = mac.replace(":", "").replace("-", "").upper()
    if len(normalized) != 12:
        raise ValueError("MAC address must contain 12 hexadecimal characters")
    int(normalized, 16)
    return normalized


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
        max_links=MAX_LINKS,
        filter_window_size=FILTER_WINDOW_SIZE,
        filter_ema_alpha=FILTER_EMA_ALPHA,
        filter_pca_components=FILTER_PCA_COMPONENTS,
        filter_variance_scale=FILTER_VARIANCE_SCALE,
        node_ids_by_mac=NODE_IDS_BY_MAC,
        node_positions=NODE_POSITIONS,
        room_width=ROOM_WIDTH,
        room_height=ROOM_HEIGHT,
        grid_resolution=GRID_RESOLUTION,
        ellipse_lambda=ELLIPSE_LAMBDA,
        link_score_scale=LINK_SCORE_SCALE,
    ):
        self.listen_ip = listen_ip
        self.listen_port = listen_port
        self.history_len = history_len
        self.max_links = max_links
        self.filter_window_size = filter_window_size
        self.filter_ema_alpha = filter_ema_alpha
        self.filter_pca_components = filter_pca_components
        self.filter_variance_scale = filter_variance_scale
        self.node_ids_by_mac = {
            _normalize_mac(mac): int(node_id)
            for mac, node_id in node_ids_by_mac.items()
        }
        self.tomography = RadioTomography(
            node_positions=node_positions,
            room_width=room_width,
            room_height=room_height,
            grid_resolution=grid_resolution,
            ellipse_lambda=ellipse_lambda,
            score_scale=link_score_scale,
        )

        self.collapse = CollapseWatch()
        self.intruder = IntruderWatch()

        self._links = {}
        self._packet_count = 0
        self._last_error = None
        self._calibrated_at = None
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

    def calibrate(self):
        """Reset every link filter and the tomography scores without losing totals."""
        with self._lock:
            for link in self._links.values():
                link["pipeline"].calibrate()
                link["history"].clear()
                link["motion_score"] = 0.0
                link["motion_variance"] = 0.0
            self.tomography.calibrate()
            self.collapse.reset()
            self._calibrated_at = time.time()
            self._last_error = None

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

        rx_mac = parsed_packet.rx_mac
        tx_mac = parsed_packet.tx_mac
        rx_node_id = self.node_ids_by_mac.get(rx_mac)
        tx_node_id = self.node_ids_by_mac.get(tx_mac)
        rssi = parsed_packet.rssi
        active_iq = extract_active_iq(parsed_packet.raw_values)
        if active_iq is None:
            return

        now = time.time()
        link_key = (rx_mac, tx_mac)
        with self._lock:
            self._packet_count += 1
            if link_key not in self._links:
                if len(self._links) >= self.max_links:
                    return
                self._links[link_key] = {
                    "rx_mac": rx_mac,
                    "tx_mac": tx_mac,
                    "rx_node_id": rx_node_id,
                    "tx_node_id": tx_node_id,
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

            link = self._links[link_key]
            try:
                motion_score = link["pipeline"].process_frame(active_iq)
            except (TypeError, ValueError, np.linalg.LinAlgError) as error:
                self._last_error = f"CSI filter error for link {rx_mac}->{tx_mac}: {error}"
                print(f"[capture] {self._last_error}")
                return

            filtered_amplitudes = link["pipeline"].latest_filtered_amplitudes
            if filtered_amplitudes is None:
                return

            amplitudes = filtered_amplitudes[-1].tolist()
            link["history"].append(amplitudes)
            link["ip"] = sender_ip
            link["rx_node_id"] = rx_node_id
            link["tx_node_id"] = tx_node_id
            link["rssi"] = rssi
            link["packet_count"] += 1
            link["last_seen"] = now
            link["motion_score"] = motion_score
            link["motion_variance"] = link["pipeline"].latest_motion_variance
            if rx_node_id is not None and tx_node_id is not None:
                self.tomography.update_link(
                    rx_node_id,
                    tx_node_id,
                    link_contrast(motion_score),
                )
            # the room is as active as its liveliest link, but only our own mesh
            # counts: strangers' wifi on the same channel scores near 1.0 and would
            # trip the alarm with nobody in the room
            mesh_scores = [
                item["motion_score"]
                for item in self._links.values()
                if item["rx_node_id"] is not None and item["tx_node_id"] is not None
            ]
            room_activity = max(mesh_scores) if mesh_scores else 0.0
            self.collapse.update(room_activity, now)
            self.intruder.update(room_activity, now)

    def get_snapshot(self, include_history=True):
        """Return a JSON-serializable copy of the latest collected CSI data.

        The per-link history is by far the largest part of the payload; a viewer
        that only needs scores and the room grid should ask for it without.
        """
        with self._lock:
            links = []
            for link in self._links.values():
                history = [list(row) for row in link["history"]] if include_history else []
                links.append(
                    {
                        "rx_mac": link["rx_mac"],
                        "tx_mac": link["tx_mac"],
                        "rx_node_id": link["rx_node_id"],
                        "tx_node_id": link["tx_node_id"],
                        "ip": link["ip"],
                        "rssi": link["rssi"],
                        "packet_count": link["packet_count"],
                        "last_seen": link["last_seen"],
                        "history": history,
                        "amplitudes": history[-1] if history else [],
                        "motion_score": link["motion_score"],
                        "motion_variance": link["motion_variance"],
                    }
                )

            return {
                "listening": self._socket is not None,
                "error": self._last_error,
                "packet_count": self._packet_count,
                "calibrated_at": self._calibrated_at,
                "amplitude_max": AMP_VMAX,
                "filter": {
                    "window_size": self.filter_window_size,
                    "ema_alpha": self.filter_ema_alpha,
                    "pca_components": self.filter_pca_components,
                    "variance_scale": self.filter_variance_scale,
                },
                "node_ids_by_mac": self.node_ids_by_mac,
                "subcarriers": [
                    subcarrier
                    for subcarrier in range(SC_FIRST, SC_LAST + 1)
                    if not NULL_SC_LOW <= subcarrier <= NULL_SC_HIGH
                ],
                "links": links,
                "tomography": self.tomography.get_snapshot(),
                "collapse": self.collapse.snapshot(),
                "intruder": self.intruder.snapshot(),
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
