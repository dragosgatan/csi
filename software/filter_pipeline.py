from __future__ import annotations

from collections import deque
from typing import Optional, Sequence, Union

import numpy as np

FrameInput = Union[Sequence[int], np.ndarray]


class CSIFilterPipeline:
    DEFAULT_WINDOW_SIZE = 30
    DEFAULT_EMA_ALPHA = 0.15
    DEFAULT_PCA_COMPONENTS = 1
    DEFAULT_VARIANCE_SCALE = 100.0
    MEDIAN_KERNEL_SIZE = 3

    def __init__(
        self,
        window_size: int = DEFAULT_WINDOW_SIZE,
        ema_alpha: float = DEFAULT_EMA_ALPHA,
        pca_components: int = DEFAULT_PCA_COMPONENTS,
        variance_scale: float = DEFAULT_VARIANCE_SCALE,
    ):
        self._window_size = window_size
        self._ema_alpha = ema_alpha
        self._pca_components = pca_components
        self._variance_scale = variance_scale

        self._amplitude_history: deque = deque(maxlen=window_size)
        self._phase_history: deque = deque(maxlen=window_size)
        self.reset()

    @property
    def window_size(self) -> int:
        return self._window_size

    @property
    def ema_alpha(self) -> float:
        return self._ema_alpha

    @property
    def pca_components(self) -> int:
        return self._pca_components

    @property
    def variance_scale(self) -> float:
        return self._variance_scale

    @property
    def subcarrier_count(self) -> Optional[int]:
        return self._subcarrier_count

    @property
    def frames_processed(self) -> int:
        return self._frames_processed

    @property
    def is_ready(self) -> bool:
        return self._frames_processed >= self._window_size

    @property
    def latest_amplitudes(self) -> Optional[np.ndarray]:
        return self._latest_amplitudes

    @property
    def latest_phase(self) -> Optional[np.ndarray]:
        return self._latest_phase

    @property
    def latest_filtered_amplitudes(self) -> Optional[np.ndarray]:
        return self._latest_filtered_amplitudes

    @property
    def latest_pc_scores(self) -> Optional[np.ndarray]:
        return self._latest_pc_scores

    @property
    def latest_pc1(self) -> Optional[np.ndarray]:
        return None if self._latest_pc_scores is None else self._latest_pc_scores[:, 0]

    @property
    def latest_motion_variance(self) -> float:
        return self._latest_motion_variance

    @property
    def latest_score(self) -> Optional[float]:
        return self._ema_score

    def set_window_size(self, window_size: int) -> None:
        self._window_size = window_size
        self._amplitude_history = deque(list(self._amplitude_history)[-window_size:], maxlen=window_size)
        self._phase_history = deque(list(self._phase_history)[-window_size:], maxlen=window_size)

    def set_ema_alpha(self, ema_alpha: float) -> None:
        self._ema_alpha = ema_alpha

    def set_pca_components(self, pca_components: int) -> None:
        self._pca_components = pca_components

    def set_variance_scale(self, variance_scale: float) -> None:
        self._variance_scale = variance_scale

    def reset(self) -> None:
        self._amplitude_history.clear()
        self._phase_history.clear()
        self._subcarrier_count = None
        self._last_raw_phase = None
        self._last_unwrapped_phase = None
        self._frames_processed = 0
        self._ema_score = None
        self._latest_amplitudes = None
        self._latest_phase = None
        self._latest_filtered_amplitudes = None
        self._latest_pc_scores = None
        self._latest_motion_variance = 0.0

    def calibrate(self) -> None:
        self.reset()

    def process_frame(self, raw_iq: FrameInput) -> float:
        iq_values = self._validate_and_convert_frame(raw_iq)
        i_values = iq_values[0::2]
        q_values = iq_values[1::2]

        if self._subcarrier_count is None:
            self._subcarrier_count = i_values.size
        elif i_values.size != self._subcarrier_count:
            raise ValueError("subcarrier count changed; call calibrate() first")
        amplitudes = np.hypot(i_values, q_values)
        unwrapped_phase = self._unwrap_phase(np.arctan2(q_values, i_values))

        self._amplitude_history.append(amplitudes)
        self._phase_history.append(unwrapped_phase)
        self._frames_processed += 1
        self._latest_amplitudes = amplitudes
        self._latest_phase = unwrapped_phase

        amplitude_matrix = np.asarray(self._amplitude_history, dtype=np.float64)
        filtered_matrix = self._median_filter_2d(amplitude_matrix)
        pc_scores = self._calculate_pc_scores(filtered_matrix)

        motion_variance = float(np.sum(np.var(pc_scores, axis=0)))
        normalized_variance = motion_variance / (motion_variance + self._variance_scale)

        self._latest_filtered_amplitudes = filtered_matrix
        self._latest_pc_scores = pc_scores
        self._latest_motion_variance = motion_variance
        self._ema_score = self._update_ema(normalized_variance)
        return self._ema_score

    def process_batch(self, frames: Sequence[FrameInput]) -> np.ndarray:
        scores = np.empty(len(frames), dtype=np.float64)
        for idx, frame in enumerate(frames):
            scores[idx] = self.process_frame(frame)
        return scores

    def _unwrap_phase(self, raw_phase: np.ndarray) -> np.ndarray:
        if self._last_raw_phase is None:
            unwrapped_phase = np.unwrap(raw_phase)
        else:
            phase_delta = np.angle(np.exp(1j * (raw_phase - self._last_raw_phase)))
            unwrapped_phase = self._last_unwrapped_phase + phase_delta

        self._last_raw_phase = raw_phase
        self._last_unwrapped_phase = unwrapped_phase
        return unwrapped_phase

    def _calculate_pc_scores(self, filtered_matrix: np.ndarray) -> np.ndarray:
        centered_matrix = filtered_matrix - np.mean(filtered_matrix, axis=0)
        if centered_matrix.shape[0] == 1:
            return np.zeros((1, 1), dtype=np.float64)

        left_vectors, singular_values, _ = np.linalg.svd(centered_matrix, full_matrices=False)
        component_count = min(self._pca_components, left_vectors.shape[1], singular_values.size)
        if component_count == 0:
            return np.zeros((centered_matrix.shape[0], 1), dtype=np.float64)

        return left_vectors[:, :component_count] * singular_values[:component_count]

    def _median_filter_2d(self, matrix: np.ndarray) -> np.ndarray:
        padding = self.MEDIAN_KERNEL_SIZE // 2
        padded_matrix = np.pad(
            matrix,
            ((self.MEDIAN_KERNEL_SIZE - 1, 0), (padding, padding)),
            mode="edge",
        )
        windows = np.lib.stride_tricks.sliding_window_view(
            padded_matrix, (self.MEDIAN_KERNEL_SIZE, self.MEDIAN_KERNEL_SIZE)
        )
        return np.median(windows, axis=(-2, -1))

    def _update_ema(self, new_value: float) -> float:
        if self._ema_score is None:
            return new_value
        return self._ema_alpha * new_value + (1.0 - self._ema_alpha) * self._ema_score

    @staticmethod
    def _validate_and_convert_frame(raw_iq: FrameInput) -> np.ndarray:
        try:
            values = np.asarray(raw_iq)
        except (TypeError, ValueError) as error:
            raise TypeError("raw_iq must be a one-dimensional integer sequence") from error

        if values.ndim != 1:
            raise ValueError("raw_iq must be a one-dimensional array")
        if values.size == 0 or values.size % 2 != 0:
            raise ValueError("raw_iq must contain a non-empty I/Q pair for every subcarrier")
        if not np.issubdtype(values.dtype, np.integer):
            raise TypeError("raw_iq must contain signed integer values")
        if np.any(values < -128) or np.any(values > 127):
            raise ValueError("raw_iq values must fit in signed 8-bit range [-128, 127]")

        return np.ascontiguousarray(values, dtype=np.float64)
