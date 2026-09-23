import json
import tempfile
import unittest
from pathlib import Path

import laspy
import numpy as np

from batiforge.reconstruction.context_ground import (
    _bounds_overlap_ratio,
    build_from_lidars,
    build_ground_grid,
    write_obj,
    write_ply,
)


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

    def test_small_flat_hole_is_filled_from_measured_neighbors(self):
        points = []
        classes = []
        for row in range(3):
            for col in range(3):
                if row == 1 and col == 1:
                    continue
                points.append((col + 0.5, row + 0.5, 100.0))
                classes.append(2)

        vertices, faces, meta = build_ground_grid(
            np.asarray(points, dtype=np.float64),
            np.asarray(classes, dtype=np.uint8),
            crop=(0.0, 0.0, 3.0, 3.0),
            origin_x=0.0,
            origin_y=0.0,
            ground_z=100.0,
            cell_size_m=1.0,
            fill_radius_cells=1,
            fill_min_neighbors=4,
            fill_min_directions=4,
            fill_max_z_span_m=0.1,
        )

        self.assertEqual(meta["grid"]["measured_cell_count"], 8)
        self.assertEqual(meta["grid"]["inferred_cell_count"], 1)
        self.assertEqual(len(vertices), 9)
        self.assertEqual(len(faces), 8)
        self.assertAlmostEqual(meta["grid"]["coverage_ratio"], 1.0)

    def test_fill_refuses_to_bridge_large_height_step(self):
        points = np.asarray(
            [
                (0.5, 1.5, 100.0),
                (1.5, 0.5, 100.0),
                (2.5, 1.5, 102.0),
                (1.5, 2.5, 102.0),
            ],
            dtype=np.float64,
        )
        classes = np.asarray([2, 2, 2, 2], dtype=np.uint8)
        vertices, _faces, meta = build_ground_grid(
            points,
            classes,
            crop=(0.0, 0.0, 3.0, 3.0),
            origin_x=0.0,
            origin_y=0.0,
            ground_z=100.0,
            cell_size_m=1.0,
            fill_radius_cells=1,
            fill_min_neighbors=4,
            fill_min_directions=4,
            fill_max_z_span_m=0.5,
        )

        self.assertEqual(meta["grid"]["inferred_cell_count"], 0)
        self.assertEqual(len(vertices), 4)

    def test_bounds_overlap_ratio_is_crop_relative(self):
        crop = (0.0, 0.0, 10.0, 10.0)
        self.assertAlmostEqual(_bounds_overlap_ratio((0.0, 0.0, 10.0, 10.0), crop), 1.0)
        self.assertAlmostEqual(_bounds_overlap_ratio((0.0, 0.0, 5.0, 10.0), crop), 0.5)
        self.assertAlmostEqual(_bounds_overlap_ratio((20.0, 20.0, 30.0, 30.0), crop), 0.0)

    def test_multiple_partial_lidar_sources_are_fused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            foot = root / "footprint.json"
            foot.write_text(
                json.dumps(
                    {
                        "bounds": {
                            "min_x": 0.0,
                            "min_y": 0.0,
                            "max_x": 4.0,
                            "max_y": 4.0,
                        },
                        "origin_x": 2.0,
                        "origin_y": 2.0,
                        "target_crs": "EPSG:2154",
                    }
                ),
                encoding="utf-8",
            )

            west = root / "west.las"
            east = root / "east.las"
            self._write_ground_las(west, x_values=(0.5, 1.5), y_values=(0.5, 1.5, 2.5, 3.5))
            self._write_ground_las(east, x_values=(2.5, 3.5), y_values=(0.5, 1.5, 2.5, 3.5))

            vertices, faces, meta = build_from_lidars(
                (west, east),
                foot,
                ground_z=100.0,
                margin_m=0.0,
                cell_size_m=1.0,
                ground_classes=(2,),
                min_points_per_cell=1,
                chunk_size=1000,
            )

            self.assertEqual(meta["source"]["overlapping_source_count"], 2)
            self.assertEqual(meta["ground_point_count"], 16)
            self.assertAlmostEqual(meta["grid"]["coverage_ratio"], 1.0)
            self.assertEqual(len(vertices), 16)
            self.assertEqual(len(faces), 18)

    def test_obj_and_ply_writers(self):
        vertices = np.asarray(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        )
        faces = np.asarray([(0, 1, 2)], dtype=np.int64)
        with tempfile.TemporaryDirectory() as tmp:
            obj = Path(tmp) / "context.obj"
            ply = Path(tmp) / "context.ply"
            write_obj(vertices, faces, obj)
            write_ply(vertices, faces, ply)
            self.assertIn("f 1 2 3", obj.read_text(encoding="utf-8"))
            self.assertIn("element face 1", ply.read_text(encoding="utf-8"))

    @staticmethod
    def _write_ground_las(path: Path, *, x_values, y_values) -> None:
        header = laspy.LasHeader(point_format=3, version="1.2")
        header.scales = np.array([0.01, 0.01, 0.01])
        las = laspy.LasData(header)
        points = [(x, y) for y in y_values for x in x_values]
        las.x = np.asarray([p[0] for p in points], dtype=np.float64)
        las.y = np.asarray([p[1] for p in points], dtype=np.float64)
        las.z = np.asarray([100.0 for _ in points], dtype=np.float64)
        las.classification = np.asarray([2 for _ in points], dtype=np.uint8)
        las.write(path)


if __name__ == "__main__":
    unittest.main()
