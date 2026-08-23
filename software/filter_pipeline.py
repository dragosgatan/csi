from collections import deque
from typing import Optional, Sequence

import numpy as np


class CSIFilterPipeline:

    DEFAULT_WINDOW_SIZE = 30
    #Exponetial moving avrage
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
        self._validate_window_size(window_size)
        self._validate_ema_alpha(ema_alpha)
        self._validate_pca_components(pca_components)
        self._validate_variance_scale(variance_scale)

        self._window_size = window_size
        self._ema_alpha = ema_alpha
        self._pca_components = pca_components
        self._variance_scale = variance_scale

        self._amplitude_history = deque(maxlen=window_size)
        self._phase_history = deque(maxlen=window_size)
        self._subcarrier_count: Optional[int] = None
        self._last_raw_phase: Optional[np.ndarray] = None
        self._last_unwrapped_phase: Optional[np.ndarray] = None

        self._ema_score: Optional[float] = None
        self._latest_amplitudes: Optional[np.ndarray] = None
        self._latest_phase: Optional[np.ndarray] = None
        self._latest_filtered_amplitudes: Optional[np.ndarray] = None
        self._latest_pc1: Optional[np.ndarray] = None
        self._latest_motion_variance = 0.0
    #larp
    @property
    def window_size(self) -> int:
        """Number of frames retained for filtering and PCA."""
        return self._window_size

    @property
    def ema_alpha(self) -> float:
        """Weight given to the newest normalized variance measurement."""
        return self._ema_alpha

    @property
    def pca_components(self) -> int:
        """Maximum number of PCA components calculated for each window."""
        return self._pca_components

    @property
    def variance_scale(self) -> float:
        """Variance value at which normalized motion reaches 0.5."""
        return self._variance_scale

    @property
    def subcarrier_count(self) -> Optional[int]:
        """Number of active subcarriers seen in the current stream."""
        return self._subcarrier_count

    @property
    def latest_amplitudes(self) -> Optional[np.ndarray]:
        """Copy of the latest raw amplitude vector, or None before processing."""
        return self._copy_or_none(self._latest_amplitudes)

    @property
    def latest_phase(self) -> Optional[np.ndarray]:
        """Copy of the latest phase vector after temporal unwrapping."""
        return self._copy_or_none(self._latest_phase)

    @property
    def latest_filtered_amplitudes(self) -> Optional[np.ndarray]:
        """Copy of the latest 2D-median-filtered amplitude matrix."""
        return self._copy_or_none(self._latest_filtered_amplitudes)

    @property
    def latest_pc1(self) -> Optional[np.ndarray]:
        """Copy of the PC1 time series from the latest rolling window."""
        return self._copy_or_none(self._latest_pc1)

    @property
    def latest_motion_variance(self) -> float:
        """Rolling variance of PC1 before normalization and EMA smoothing."""
        return self._latest_motion_variance

    def set_window_size(self, window_size: int) -> None:
        """Change the rolling frame count while retaining the newest frames."""
        self._validate_window_size(window_size)
        if window_size == self._window_size:
            return

        self._window_size = window_size
        self._amplitude_history = deque(
            list(self._amplitude_history)[-window_size:], maxlen=window_size
        )
        self._phase_history = deque(
            list(self._phase_history)[-window_size:], maxlen=window_size
        )

    def set_ema_alpha(self, ema_alpha: float) -> None:
        """Change EMA responsiveness without clearing the current score."""
        self._validate_ema_alpha(ema_alpha)
        self._ema_alpha = ema_alpha

    def set_pca_components(self, pca_components: int) -> None:
        """Change how many PCA components are calculated for future windows."""
        self._validate_pca_components(pca_components)
        self._pca_components = pca_components

    def set_variance_scale(self, variance_scale: float) -> None:
        """Change the half-saturation scale used to normalize PC1 variance."""
        self._validate_variance_scale(variance_scale)
        self._variance_scale = variance_scale

    def reset(self) -> None:
        """Clear collected frames, phase state, and the EMA score."""
        self._amplitude_history.clear()
        self._phase_history.clear()
        self._subcarrier_count = None
        self._last_raw_phase = None
        self._last_unwrapped_phase = None
        self._ema_score = None
        self._latest_amplitudes = None
        self._latest_phase = None
        self._latest_filtered_amplitudes = None
        self._latest_pc1 = None
        self._latest_motion_variance = 0.0

    def process_frame(self, raw_iq: Sequence[int] | np.ndarray) -> float:
        """Process one I/Q frame and return a normalized score in the range 0..1."""
        iq_values = self._validate_and_convert_frame(raw_iq)
        i_values = iq_values[0::2]
        q_values = iq_values[1::2]

        self._set_or_validate_subcarrier_count(i_values.size)
        amplitudes = np.hypot(i_values, q_values)
        unwrapped_phase = self._unwrap_phase(np.arctan2(q_values, i_values))

        self._amplitude_history.append(amplitudes)
        self._phase_history.append(unwrapped_phase)
        self._latest_amplitudes = amplitudes.copy()
        self._latest_phase = unwrapped_phase.copy()

        amplitude_matrix = np.asarray(self._amplitude_history, dtype=np.float64)
        filtered_matrix = self._median_filter_2d(amplitude_matrix)
        pc1 = self._calculate_pc1(filtered_matrix)
        motion_variance = float(np.var(pc1))
        normalized_variance = self._normalize_variance(motion_variance)

        self._latest_filtered_amplitudes = filtered_matrix.copy()
        self._latest_pc1 = pc1.copy()
        self._latest_motion_variance = motion_variance
        self._ema_score = self._update_ema(normalized_variance)
        return self._ema_score

    def _unwrap_phase(self, raw_phase: np.ndarray) -> np.ndarray:
        """Unwrap the first frame spatially and subsequent frames over time."""
        if self._last_raw_phase is None:
            unwrapped_phase = np.unwrap(raw_phase)
        else:
            phase_delta = np.angle(np.exp(1j * (raw_phase - self._last_raw_phase)))
            unwrapped_phase = self._last_unwrapped_phase + phase_delta

        self._last_raw_phase = raw_phase.copy()
        self._last_unwrapped_phase = unwrapped_phase.copy()
        return unwrapped_phase

    def _calculate_pc1(self, filtered_matrix: np.ndarray) -> np.ndarray:
        """Center subcarrier dimensions and return the rolling PC1 time series."""
        centered_matrix = filtered_matrix - np.mean(filtered_matrix, axis=0)
        if centered_matrix.shape[0] == 1:
            return np.zeros(1, dtype=np.float64)

        left_vectors, singular_values, _ = np.linalg.svd(
            centered_matrix, full_matrices=False
        )
        component_count = min(
            self._pca_components,
            left_vectors.shape[1],
            singular_values.size,
        )
        if component_count == 0:
            return np.zeros(centered_matrix.shape[0], dtype=np.float64)

        # PC1 is the first score vector; its sign is arbitrary but variance is not.
        scores = left_vectors[:, :component_count] * singular_values[:component_count]
        return scores[:, 0]

    def _median_filter_2d(self, matrix: np.ndarray) -> np.ndarray:
        """Apply a 3x3 edge-preserving median over time and subcarrier axes."""
        padding = self.MEDIAN_KERNEL_SIZE // 2
        padded_matrix = np.pad(
            matrix,
            # causal time padding keeps the online filter from using future frames.
            ((self.MEDIAN_KERNEL_SIZE - 1, 0), (padding, padding)),
            mode="edge",
        )
        windows = np.lib.stride_tricks.sliding_window_view(
            padded_matrix,
            (self.MEDIAN_KERNEL_SIZE, self.MEDIAN_KERNEL_SIZE),
        )
        return np.median(windows, axis=(-2, -1))

    def _normalize_variance(self, motion_variance: float) -> float:
        """Map non-negative variance to 0..1 with a tunable saturating curve."""
        return motion_variance / (motion_variance + self._variance_scale)

    def _update_ema(self, new_value: float) -> float:
        if self._ema_score is None:
            return new_value
        return self._ema_alpha * new_value + (1.0 - self._ema_alpha) * self._ema_score

    def _set_or_validate_subcarrier_count(self, count: int) -> None:
        if self._subcarrier_count is None:
            self._subcarrier_count = count
            return
        if count != self._subcarrier_count:
            raise ValueError(
                "subcarrier count changed during the stream; call reset() first"
            )

    @staticmethod
    def _validate_and_convert_frame(raw_iq: Sequence[int] | np.ndarray) -> np.ndarray:
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

    @staticmethod
    def _validate_window_size(window_size: int) -> None:
        if isinstance(window_size, bool) or not isinstance(window_size, (int, np.integer)):
            raise TypeError("window_size must be a positive integer")
        if window_size < 1:
            raise ValueError("window_size must be a positive integer")

    @staticmethod
    def _validate_ema_alpha(ema_alpha: float) -> None:
        if not isinstance(ema_alpha, (float, int, np.floating, np.integer)):
            raise TypeError("ema_alpha must be a number in the range (0, 1]")
        if not np.isfinite(ema_alpha) or not 0.0 < ema_alpha <= 1.0:
            raise ValueError("ema_alpha must be a number in the range (0, 1]")

    @staticmethod
    def _validate_pca_components(pca_components: int) -> None:
        if isinstance(pca_components, bool) or not isinstance(
            pca_components, (int, np.integer)
        ):
            raise TypeError("pca_components must be a positive integer")
        if pca_components < 1:
            raise ValueError("pca_components must be a positive integer")

    @staticmethod
    def _validate_variance_scale(variance_scale: float) -> None:
        if not isinstance(variance_scale, (float, int, np.floating, np.integer)):
            raise TypeError("variance_scale must be a positive number")
        if not np.isfinite(variance_scale) or variance_scale <= 0.0:
            raise ValueError("variance_scale must be a positive number")

    @staticmethod
    def _copy_or_none(value: Optional[np.ndarray]) -> Optional[np.ndarray]:
        return None if value is None else value.copy()
