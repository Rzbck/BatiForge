from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from batiforge.reconstruction.roof_regions import (
    build_roof_regions,
    write_region_obj,
    write_region_ply,
)


class RoofRegionTests(unittest.TestCase):
    def _evidence(self) -> tuple[np.ndarray, dict, dict, dict, dict]:
        origin_x = 1000.0
        origin_y = 2000.0
        ground_z = 100.0

        xs_left, ys_left = np.meshgrid(np.linspace(-9.5, -0.25, 24), np.linspace(-7.5, 7.5, 20))
        xs_right, ys_right = np.meshgrid(np.linspace(0.25, 9.5, 24), np.linspace(-7.5, 7.5, 20))
        left_x = xs_left.ravel()
        left_y = ys_left.ravel()
        right_x = xs_right.ravel()
        right_y = ys_right.ravel()
        left_z = 110.0 + 0.4 * left_x
        right_z = 110.0 - 0.4 * right_x
        xyz = np.vstack(
            (
                np.column_stack((origin_x + left_x, origin_y + left_y, left_z)),
                np.column_stack((origin_x + right_x, origin_y + right_y, right_z)),
            )
        )

        roof = {
            "georeference": {
                "origin_x": origin_x,
                "origin_y": origin_y,
                "ground_z": ground_z,
                "horizontal_crs": "EPSG:2154",
                "vertical_datum": "IGN69",
            },
            "planes": [
                {"index": 1, "a": 0.4, "b": 0.0, "c": 110.0},
                {"index": 2, "a": -0.4, "b": 0.0, "c": 110.0},
            ],
        }
        footprint = {
            "origin_x": origin_x,
            "origin_y": origin_y,
            "target_crs": "EPSG:2154",
            "polygons_local_xy": [[[-10.0, -8.0], [10.0, -8.0], [10.0, 8.0], [-10.0, 8.0]]],
        }
        topology = {
            "georeference": roof["georeference"],
            "adjacencies": [
                {
                    "plane_a": 1,
                    "plane_b": 2,
                    "approx_boundary_length_m": 16.0,
                    "median_height_gap_m": 0.0,
                    "relation": "continuous_intersection_candidate",
                }
            ],
            "boundary_segments": [],
        }
        vectors = {
            "georeference": roof["georeference"],
            "vector_edges": [
                {
                    "plane_a": 1,
                    "plane_b": 2,
                    "measured_boundary_length_m": 16.0,
                    "equality_line_local": {"a": 1.0, "b": 0.0, "c": 0.0},
                }
            ],
        }
        return xyz, roof, footprint, topology, vectors

    def test_gable_becomes_two_supported_plane_regions(self) -> None:
        xyz, roof, footprint, topology, vectors = self._evidence()
        result = build_roof_regions(
            xyz,
            roof=roof,
            footprint=footprint,
            topology=topology,
            vectors=vectors,
            min_region_points=3,
            min_region_purity=0.55,
        )

        self.assertEqual(result["continuous_divider_count"], 1)
        self.assertEqual(result["height_step_divider_count"], 0)
        self.assertGreaterEqual(result["region_count"], 2)
        self.assertGreater(result["resolved_area_ratio"], 0.95)
        self.assertEqual({region["plane_index"] for region in result["regions"]}, {1, 2})

        # Every emitted vertex lies exactly on its assigned analytic roof plane.
        planes = {1: (0.4, 0.0, 110.0), 2: (-0.4, 0.0, 110.0)}
        for region in result["regions"]:
            a, b, c = planes[region["plane_index"]]
            for x, y, z_local in region["vertices_local_xyz"]:
                self.assertAlmostEqual(z_local + 100.0, a * x + b * y + c, places=4)

    def test_result_is_deterministic(self) -> None:
        xyz, roof, footprint, topology, vectors = self._evidence()
        first = build_roof_regions(
            xyz,
            roof=roof,
            footprint=footprint,
            topology=topology,
            vectors=vectors,
        )
        second = build_roof_regions(
            xyz,
            roof=roof,
            footprint=footprint,
            topology=topology,
            vectors=vectors,
        )
        self.assertEqual(
            json.dumps(first, sort_keys=True),
            json.dumps(second, sort_keys=True),
        )

    def test_obj_and_ply_emit_faces_and_preserve_z_up_metadata(self) -> None:
        xyz, roof, footprint, topology, vectors = self._evidence()
        result = build_roof_regions(
            xyz,
            roof=roof,
            footprint=footprint,
            topology=topology,
            vectors=vectors,
        )
        with tempfile.TemporaryDirectory() as tmp:
            obj = Path(tmp) / "roof.obj"
            ply = Path(tmp) / "roof.ply"
            write_region_obj(obj, result)
            write_region_ply(ply, result)
            obj_text = obj.read_text(encoding="utf-8")
            ply_text = ply.read_text(encoding="utf-8")

        self.assertIn("# axes: X east / Y north / Z up", obj_text)
        self.assertIn("\nf ", obj_text)
        self.assertIn("comment BatiForge local metric roof regions; X east, Y north, Z up", ply_text)
        self.assertIn("element face ", ply_text)

    def test_height_step_boundary_becomes_straight_partition_divider(self) -> None:
        xyz, roof, footprint, topology, vectors = self._evidence()
        topology = dict(topology)
        topology["adjacencies"] = [
            {
                "plane_a": 1,
                "plane_b": 2,
                "approx_boundary_length_m": 10.0,
                "median_height_gap_m": 4.0,
                "relation": "height_step_or_overlap_candidate",
            }
        ]
        topology["boundary_segments"] = [
            {"plane_a": 1, "plane_b": 2, "x0": -0.1, "y0": -5.0, "x1": 0.1, "y1": -5.0},
            {"plane_a": 1, "plane_b": 2, "x0": -0.1, "y0": 0.0, "x1": 0.1, "y1": 0.0},
            {"plane_a": 1, "plane_b": 2, "x0": -0.1, "y0": 5.0, "x1": 0.1, "y1": 5.0},
        ]
        vectors = dict(vectors)
        vectors["vector_edges"] = []

        result = build_roof_regions(
            xyz,
            roof=roof,
            footprint=footprint,
            topology=topology,
            vectors=vectors,
        )
        self.assertEqual(result["continuous_divider_count"], 0)
        self.assertEqual(result["height_step_divider_count"], 1)
        self.assertGreater(result["resolved_area_ratio"], 0.95)


if __name__ == "__main__":
    unittest.main()
