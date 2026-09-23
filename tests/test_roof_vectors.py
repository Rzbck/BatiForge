from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from batiforge.reconstruction.roof_vectors import (
    build_vector_intersections,
    write_vector_obj,
)


class RoofVectorTests(unittest.TestCase):
    def _roof(self) -> dict:
        return {
            "georeference": {
                "origin_x": 1000.0,
                "origin_y": 2000.0,
                "ground_z": 100.0,
                "horizontal_crs": "EPSG:2154",
                "vertical_datum": "IGN69",
            },
            "planes": [
                {"index": 1, "a": 0.4, "b": 0.0, "c": 110.0},
                {"index": 2, "a": -0.4, "b": 0.0, "c": 110.0},
                {"index": 3, "a": 0.0, "b": 0.0, "c": 104.0},
            ],
        }

    def _footprint(self) -> dict:
        return {
            "origin_x": 1000.0,
            "origin_y": 2000.0,
            "target_crs": "EPSG:2154",
            "polygons_local_xy": [
                [[-5.0, -5.0], [5.0, -5.0], [5.0, 5.0], [-5.0, 5.0]]
            ],
        }

    def _topology(self) -> dict:
        segments = []
        for y in (-4.0, -2.0, 0.0, 2.0, 4.0):
            segments.append(
                {
                    "plane_a": 1,
                    "plane_b": 2,
                    "x0": -0.25,
                    "y0": y,
                    "x1": 0.25,
                    "y1": y,
                    "z_abs": 110.0,
                    "height_gap_m": 0.1,
                }
            )
        return {
            "georeference": {
                "origin_x": 1000.0,
                "origin_y": 2000.0,
                "ground_z": 100.0,
                "horizontal_crs": "EPSG:2154",
                "vertical_datum": "IGN69",
            },
            "high_structure_point_count": 12,
            "adjacencies": [
                {
                    "plane_a": 1,
                    "plane_b": 2,
                    "approx_boundary_length_m": 8.0,
                    "median_height_gap_m": 0.1,
                    "p95_height_gap_m": 0.2,
                    "median_distance_to_plane_equality_line_m": 0.1,
                    "relation": "continuous_intersection_candidate",
                },
                {
                    "plane_a": 1,
                    "plane_b": 3,
                    "approx_boundary_length_m": 4.0,
                    "median_height_gap_m": 6.0,
                    "p95_height_gap_m": 6.2,
                    "median_distance_to_plane_equality_line_m": 5.0,
                    "relation": "height_step_or_overlap_candidate",
                },
            ],
            "boundary_segments": segments,
        }

    def test_continuous_intersection_becomes_analytic_vector(self) -> None:
        result = build_vector_intersections(
            topology=self._topology(),
            roof=self._roof(),
            footprint=self._footprint(),
            min_boundary_length_m=1.0,
            support_margin_m=0.5,
        )

        self.assertEqual(result["continuous_candidate_count"], 1)
        self.assertEqual(result["vector_edge_count"], 1)
        self.assertEqual(result["height_step_pair_count"], 1)

        edge = result["vector_edges"][0]
        self.assertEqual((edge["plane_a"], edge["plane_b"]), (1, 2))
        self.assertAlmostEqual(edge["vector_length_m"], 9.0, places=4)
        self.assertAlmostEqual(edge["start_local_xyz"][0], 0.0, places=5)
        self.assertAlmostEqual(edge["end_local_xyz"][0], 0.0, places=5)
        self.assertAlmostEqual(edge["start_local_xyz"][2], 10.0, places=5)
        self.assertAlmostEqual(edge["end_local_xyz"][2], 10.0, places=5)

    def test_support_extent_is_clipped_to_authoritative_footprint(self) -> None:
        topology = self._topology()
        for segment, y in zip(topology["boundary_segments"], (-6.0, -3.0, 0.0, 3.0, 6.0)):
            segment["y0"] = y
            segment["y1"] = y

        result = build_vector_intersections(
            topology=topology,
            roof=self._roof(),
            footprint=self._footprint(),
            support_margin_m=1.0,
        )
        edge = result["vector_edges"][0]
        self.assertAlmostEqual(edge["vector_length_m"], 10.0, places=4)
        self.assertTrue(edge["start_touches_footprint"])
        self.assertTrue(edge["end_touches_footprint"])

    def test_short_continuous_support_is_not_promoted(self) -> None:
        topology = self._topology()
        topology["adjacencies"][0]["approx_boundary_length_m"] = 0.5
        result = build_vector_intersections(
            topology=topology,
            roof=self._roof(),
            footprint=self._footprint(),
            min_boundary_length_m=1.0,
        )
        self.assertEqual(result["vector_edge_count"], 0)
        self.assertEqual(result["skipped"]["short_support"], 1)

    def test_obj_contains_lines_only(self) -> None:
        result = build_vector_intersections(
            topology=self._topology(),
            roof=self._roof(),
            footprint=self._footprint(),
            support_margin_m=0.5,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vectors.obj"
            write_vector_obj(path, result, self._footprint())
            text = path.read_text(encoding="utf-8")

        self.assertIn("o roof_vector_01_p01_p02", text)
        self.assertIn("\nl ", text)
        self.assertNotIn("\nf ", text)


if __name__ == "__main__":
    unittest.main()
