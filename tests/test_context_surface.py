import unittest

import numpy as np

from batiforge.reconstruction.context_surface import build_continuous_grid


class ContextSurfaceTests(unittest.TestCase):
    def test_full_grid_is_filled_and_meshed(self):
        points = []
        for row in range(5):
            for col in range(5):
                if 1 <= row <= 3 and 1 <= col <= 3:
                    continue
                points.append((col + 0.5, row + 0.5, 100.0 + 0.1 * row))

        vertices, faces, meta = build_continuous_grid(
            np.asarray(points, dtype=np.float64),
            crop=(0.0, 0.0, 5.0, 5.0),
            origin_x=0.0,
            origin_y=0.0,
            ground_z=100.0,
            cell_size_m=1.0,
            relax_iterations=20,
            relax_weight=0.5,
        )

        self.assertEqual(meta["grid"]["cell_count"], 25)
        self.assertEqual(meta["grid"]["measured_cell_count"], 16)
        self.assertEqual(meta["grid"]["inferred_cell_count"], 9)
        self.assertEqual(meta["grid"]["final_coverage_ratio"], 1.0)
        self.assertEqual(len(vertices), 25)
        self.assertEqual(len(faces), 32)
        self.assertTrue(np.isfinite(vertices).all())

    def test_measured_cells_remain_exact(self):
        points = np.asarray(
            [
                (0.5, 0.5, 10.0),
                (1.5, 0.5, 11.0),
                (0.5, 1.5, 12.0),
            ],
            dtype=np.float64,
        )

        vertices, _faces, _meta = build_continuous_grid(
            points,
            crop=(0.0, 0.0, 2.0, 2.0),
            origin_x=0.0,
            origin_y=0.0,
            ground_z=0.0,
            cell_size_m=1.0,
            relax_iterations=50,
            relax_weight=0.8,
        )

        z = vertices[:, 2].reshape(2, 2)
        self.assertAlmostEqual(z[0, 0], 10.0)
        self.assertAlmostEqual(z[0, 1], 11.0)
        self.assertAlmostEqual(z[1, 0], 12.0)
        self.assertTrue(np.isfinite(z[1, 1]))

    def test_invalid_relax_weight_is_rejected(self):
        points = np.asarray([(0.5, 0.5, 10.0)], dtype=np.float64)
        with self.assertRaises(ValueError):
            build_continuous_grid(
                points,
                crop=(0.0, 0.0, 1.0, 1.0),
                origin_x=0.0,
                origin_y=0.0,
                ground_z=0.0,
                relax_weight=1.5,
            )


if __name__ == "__main__":
    unittest.main()
