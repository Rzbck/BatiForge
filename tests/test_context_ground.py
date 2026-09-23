import tempfile
import unittest
from pathlib import Path

import numpy as np

from batiforge.reconstruction.context_ground import build_ground_grid, write_obj, write_ply


class ContextGroundTests(unittest.TestCase):
    def test_regular_ground_grid_ignores_building_points(self):
        points = []
        classes = []
        for y in (0.5, 1.5, 2.5, 3.5):
            for x in (0.5, 1.5, 2.5, 3.5):
                points.append((x, y, 100.0 + 0.1 * x))
                classes.append(2)
        points.append((1.5, 1.5, 130.0))
        classes.append(6)

        vertices, faces, meta = build_ground_grid(
            np.asarray(points, dtype=np.float64),
            np.asarray(classes, dtype=np.uint8),
            crop=(0.0, 0.0, 4.0, 4.0),
            origin_x=2.0,
            origin_y=2.0,
            ground_z=100.0,
            cell_size_m=1.0,
        )

        self.assertEqual(len(vertices), 16)
        self.assertEqual(len(faces), 18)
        self.assertEqual(meta["ground_point_count"], 16)
        self.assertAlmostEqual(meta["grid"]["coverage_ratio"], 1.0)
        self.assertLess(float(vertices[:, 2].max()), 1.0)

    def test_sparse_cell_does_not_create_bridge_faces(self):
        points = np.asarray(
            [
                (0.5, 0.5, 10.0),
                (1.5, 0.5, 10.0),
                (0.5, 1.5, 10.0),
            ],
            dtype=np.float64,
        )
        classes = np.asarray([2, 2, 2], dtype=np.uint8)
        vertices, faces, meta = build_ground_grid(
            points,
            classes,
            crop=(0.0, 0.0, 2.0, 2.0),
            origin_x=0.0,
            origin_y=0.0,
            ground_z=10.0,
            cell_size_m=1.0,
        )
        self.assertEqual(len(vertices), 3)
        self.assertEqual(len(faces), 0)
        self.assertAlmostEqual(meta["grid"]["coverage_ratio"], 0.75)

    def test_obj_and_ply_writers(self):
        vertices = np.asarray([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)])
        faces = np.asarray([(0, 1, 2)], dtype=np.int64)
        with tempfile.TemporaryDirectory() as tmp:
            obj = Path(tmp) / "context.obj"
            ply = Path(tmp) / "context.ply"
            write_obj(vertices, faces, obj)
            write_ply(vertices, faces, ply)
            self.assertIn("f 1 2 3", obj.read_text(encoding="utf-8"))
            self.assertIn("element face 1", ply.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
