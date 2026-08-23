import unittest

import numpy as np

from filter_pipeline import CSIFilterPipeline


class CSIFilterPipelineTests(unittest.TestCase):
    def test_constant_signal_has_no_motion(self):
        pipeline = CSIFilterPipeline(window_size=5)

        scores = [pipeline.process_frame([20, 0] * 4) for _ in range(5)]

        self.assertEqual(scores[-1], 0.0)

    def test_sustained_change_produces_bounded_motion_score(self):
        pipeline = CSIFilterPipeline(window_size=5)
        for _ in range(5):
            pipeline.process_frame([20, 0] * 4)

        pipeline.process_frame([80, 0] * 4)
        score = pipeline.process_frame([80, 0] * 4)

        self.assertGreater(score, 0.0)
        self.assertLessEqual(score, 1.0)
        self.assertEqual(pipeline.latest_pc1.shape, (5,))

    def test_single_packet_spike_is_removed(self):
        pipeline = CSIFilterPipeline(window_size=5)
        for _ in range(5):
            pipeline.process_frame([20, 0] * 4)

        score = pipeline.process_frame([80, 0] * 4)

        self.assertEqual(score, 0.0)

    def test_phase_unwraps_across_frames(self):
        pipeline = CSIFilterPipeline(window_size=3)

        pipeline.process_frame([-99, 14] * 2)
        pipeline.process_frame([-99, -14] * 2)

        self.assertTrue(np.all(pipeline.latest_phase > 3.0))

    def test_configuration_methods_update_pipeline(self):
        pipeline = CSIFilterPipeline()

        pipeline.set_window_size(4)
        pipeline.set_ema_alpha(0.5)
        pipeline.set_pca_components(2)

        self.assertEqual(pipeline.window_size, 4)
        self.assertEqual(pipeline.ema_alpha, 0.5)
        self.assertEqual(pipeline.pca_components, 2)

    def test_invalid_frames_are_rejected(self):
        pipeline = CSIFilterPipeline()

        with self.assertRaises(ValueError):
            pipeline.process_frame([1])
        with self.assertRaises(ValueError):
            pipeline.process_frame([128, 0])
        with self.assertRaises(TypeError):
            pipeline.process_frame([1.5, 0])
        with self.assertRaises(ValueError):
            pipeline.process_frame(np.zeros((2, 2), dtype=np.int8))


if __name__ == "__main__":
    unittest.main()
