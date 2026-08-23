"""Radio-tomography reconstruction from disturbed CSI links."""

from typing import Mapping, Optional, Tuple

import numpy as np


Position = Tuple[float, float]
Link = Tuple[str, str]


class RadioTomography:
    """Project link motion scores onto an ellipse-weighted room grid."""

    def __init__(
        self,
        node_positions: Mapping[str, Position],
        room_width: float = 5.0,
        room_height: float = 5.0,
        grid_resolution: int = 80,
        ellipse_lambda: float = 0.5,
        score_scale: float = 0.5,
    ):
        self._validate_dimensions(room_width, room_height, grid_resolution)
        self._validate_positive_number("ellipse_lambda", ellipse_lambda)
        self._validate_positive_number("score_scale", score_scale)

        self.room_width = room_width
        self.room_height = room_height
        self.grid_resolution = grid_resolution
        self.ellipse_lambda = ellipse_lambda
        self.score_scale = score_scale
        self.node_positions = {
            self._normalize_mac(mac): (float(position[0]), float(position[1]))
            for mac, position in node_positions.items()
        }

        x_values = np.linspace(0.0, room_width, grid_resolution)
        y_values = np.linspace(0.0, room_height, grid_resolution)
        self.grid_x, self.grid_y = np.meshgrid(x_values, y_values)
        self._link_weights = {}
        self._link_scores = {}

    def update_link(self, rx_mac: str, tx_mac: str, score: float) -> None:
        """Store the latest bounded motion score for one ordered link."""
        link = (self._normalize_mac(rx_mac), self._normalize_mac(tx_mac))
        if link[0] == link[1] or link[0] not in self.node_positions or link[1] not in self.node_positions:
            return

        self._link_scores[link] = max(0.0, min(1.0, float(score)))
        if link not in self._link_weights:
            self._link_weights[link] = self._build_link_weight(link)

    def calibrate(self) -> None:
        """Clear all link scores so the reconstructed grid returns to zero."""
        self._link_scores.clear()

    def get_snapshot(self):
        """Return grid metadata, reconstructed values, and active link scores."""
        heat = self._reconstruct()
        links = [
            {"rx_mac": rx_mac, "tx_mac": tx_mac, "score": score}
            for (rx_mac, tx_mac), score in self._link_scores.items()
        ]
        return {
            "width": self.room_width,
            "height": self.room_height,
            "resolution": self.grid_resolution,
            "values": heat.tolist(),
            "links": links,
            "node_positions": {
                mac: [position[0], position[1]]
                for mac, position in self.node_positions.items()
            },
        }

    def _reconstruct(self) -> np.ndarray:
        heat = np.zeros_like(self.grid_x)
        weight_sum = np.zeros_like(self.grid_x)

        for link, score in self._link_scores.items():
            weight = self._link_weights[link]
            heat += weight * min(1.0, score / self.score_scale)
            weight_sum += weight

        valid_weights = weight_sum > 0.0
        heat[valid_weights] /= weight_sum[valid_weights]
        return heat

    def _build_link_weight(self, link: Link) -> np.ndarray:
        rx_x, rx_y = self.node_positions[link[0]]
        tx_x, tx_y = self.node_positions[link[1]]
        link_length = ((rx_x - tx_x) ** 2 + (rx_y - tx_y) ** 2) ** 0.5
        if link_length < 0.05:
            return np.zeros_like(self.grid_x)

        distance_tx = np.hypot(self.grid_x - tx_x, self.grid_y - tx_y)
        distance_rx = np.hypot(self.grid_x - rx_x, self.grid_y - rx_y)
        excess_distance = distance_tx + distance_rx - link_length
        weight = np.clip(1.0 - excess_distance / self.ellipse_lambda, 0.0, 1.0)
        return weight / link_length

    @staticmethod
    def _normalize_mac(mac: str) -> str:
        normalized = mac.replace(":", "").replace("-", "").upper()
        if len(normalized) != 12 or any(character not in "0123456789ABCDEF" for character in normalized):
            raise ValueError(f"invalid MAC address: {mac}")
        return normalized

    @staticmethod
    def _validate_dimensions(room_width: float, room_height: float, grid_resolution: int) -> None:
        if room_width <= 0.0 or room_height <= 0.0:
            raise ValueError("room dimensions must be positive")
        if isinstance(grid_resolution, bool) or not isinstance(grid_resolution, int) or grid_resolution < 2:
            raise ValueError("grid_resolution must be an integer greater than one")

    @staticmethod
    def _validate_positive_number(name: str, value: float) -> None:
        if not np.isfinite(value) or value <= 0.0:
            raise ValueError(f"{name} must be positive")
