import unittest

import numpy as np

from batiforge.reconstruction.context_surface_refine import (
    refine_surface_grid,
    roughness_stats,
)


class ContextSurfaceRefineTests(unittest.TestCase):
    def test_checkerboard_noise_is_reduced(self):
        yy, xx = np.mgrid[0:9, 0:9]
        plane = 100.0 + 0.03 * xx + 0.02 * yy
        noise = np.where((xx + yy) % 2 == 0, 0.09, -0.09)
        source = plane + noise

        refined, metrics = refine_surface_grid(
            source,
            iterations=14,
            strength=0.7,
            sigma_z_m=0.35,
            max_delta_m=0.25,
        )

        self.assertEqual(refined.shape, source.shape)
        self.assertLess(
            metrics["roughness_after"]["p90_m"],
            metrics["roughness_before"]["p90_m"],
        )
        self.assertLessEqual(metrics["displacement"]["max_abs_m"], 0.2500001)

    def test_large_step_is_preserved(self):
        source = np.zeros((10, 10), dtype=np.float64)
        source[:, 5:] = 1.5

        refined, _metrics = refine_surface_grid(
            source,
            iterations=20,
            strength=0.7,
            sigma_z_m=0.20,
            max_delta_m=0.20,
        )

        self.assertLess(float(refined[:, 4].max()), 0.10)
        self.assertGreater(float(refined[:, 5].min()), 1.40)

    def test_zero_max_delta_keeps_input_exact(self):
        source = np.asarray(
            [[0.0, 0.2, 0.0], [0.1, 0.5, 0.1], [0.0, 0.2, 0.0]],
            dtype=np.float64,
        )
        refined, metrics = refine_surface_grid(
            source,
            iterations=10,
            strength=0.8,
            sigma_z_m=0.3,
            max_delta_m=0.0,
        )
        np.testing.assert_allclose(refined, source)
        self.assertEqual(metrics["displacement"]["max_abs_m"], 0.0)

    def test_roughness_stats_on_plane_is_small(self):
        yy, xx = np.mgrid[0:8, 0:8]
        plane = 10.0 + 0.1 * xx + 0.05 * yy
        stats = roughness_stats(plane)
        self.assertLess(stats["p90_m"], 0.06)

    def test_invalid_parameters_are_rejected(self):
        source = np.zeros((3, 3), dtype=np.float64)
        with self.assertRaises(ValueError):
            refine_surface_grid(source, sigma_z_m=0.0)
        with self.assertRaises(ValueError):
            refine_surface_grid(source, strength=1.2)
        with self.assertRaises(ValueError):
            refine_surface_grid(source, max_delta_m=-0.1)


if __name__ == "__main__":
    unittest.main()
