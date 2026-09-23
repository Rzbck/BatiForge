from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from batiforge.reconstruction.roof_planes import analyze_roof_planes
from batiforge.reconstruction.roof_topology import (
    analyze_topology_evidence,
    write_topology_boundary_obj,
)


class RoofTopologyTests(unittest.TestCase):
    def _synthetic_gable(self) -> np.ndarray:
        rng = np.random.default_rng(24680)
        left_xy = np.column_stack(
            (rng.uniform(-10.0, 0.0, 1800), rng.uniform(-8.0, 8.0, 1800))
        )
        right_xy = np.column_stack(
            (rng.uniform(0.0, 10.0, 1800), rng.uniform(-8.0, 8.0, 1800))
        )
        left_z = 110.0 + 0.4 * left_xy[:, 0] + rng.normal(0.0, 0.015, 1800)
        right_z = 110.0 - 0.4 * right_xy[:, 0] + rng.normal(0.0, 0.015, 1800)

        left = np.column_stack((1000.0 + left_xy[:, 0], 2000.0 + left_xy[:, 1], left_z))
        right = np.column_stack((1000.0 + right_xy[:, 0], 2000.0 + right_xy[:, 1], right_z))

        high = np.column_stack(
            (
                rng.uniform(998.0, 1002.0, 40),
                rng.uniform(1998.0, 2002.0, 40),
                rng.uniform(123.0, 126.0, 40),
            )
        )
        return np.vstack((left, right, high))

    def _roof_and_footprint(self, xyz: np.ndarray) -> tuple[dict, dict]:
        analysis = analyze_roof_planes(
            xyz,
            ground_z=100.0,
            min_height_m=2.0,
            residual_threshold_m=0.08,
            min_plane_points=900,
            min_plane_area_m2=50.0,
            max_planes=4,
            max_slope_deg=75.0,
            ransac_iterations=500,
            seed=19,
        )
        roof = json.loads(analysis.to_json())
        ox = float(roof["georeference"]["origin_x"])
        oy = float(roof["georeference"]["origin_y"])
        footprint = {
            "schema_version": 2,
            "rnb_id": "TEST12345678",
            "target_crs": "EPSG:2154",
            "origin_x": ox,
            "origin_y": oy,
            "polygons_abs_xy": [[
                [990.0, 1992.0],
                [1010.0, 1992.0],
                [1010.0, 2008.0],
                [990.0, 2008.0],
            ]],
        }
        return roof, footprint

    def test_gable_support_forms_two_adjacent_regions(self) -> None:
        xyz = self._synthetic_gable()
        roof, footprint = self._roof_and_footprint(xyz)
        topology = analyze_topology_evidence(
            xyz,
            roof=roof,
            footprint=footprint,
            residual_threshold_m=0.08,
            min_height_m=2.0,
            high_structure_min_height_m=22.0,
            cell_size_m=0.5,
            min_cell_points=2,
            min_cell_purity=0.60,
            continuous_gap_m=0.35,
        )

        self.assertEqual(topology["outside_footprint_point_count"], 0)
        self.assertEqual(topology["high_structure_point_count"], 40)
        self.assertGreater(topology["main_roof_assignment_ratio"], 0.97)
        self.assertGreater(topology["resolved_cell_ratio"], 0.80)

        supported = [
            item for item in topology["plane_support"] if item["assigned_point_count"] > 500
        ]
        self.assertEqual(len(supported), 2)
        self.assertGreaterEqual(topology["adjacency_count"], 1)

        strongest = max(
            topology["adjacencies"], key=lambda item: item["boundary_edge_count"]
        )
        self.assertEqual(strongest["relation"], "continuous_intersection_candidate")
        self.assertLess(strongest["median_height_gap_m"], 0.2)
        self.assertLess(
            strongest["median_distance_to_plane_equality_line_m"],
            0.75,
        )

    def test_topology_is_deterministic(self) -> None:
        xyz = self._synthetic_gable()
        roof, footprint = self._roof_and_footprint(xyz)
        first = analyze_topology_evidence(
            xyz,
            roof=roof,
            footprint=footprint,
            residual_threshold_m=0.08,
            min_height_m=2.0,
            cell_size_m=0.5,
            min_cell_points=2,
        )
        second = analyze_topology_evidence(
            xyz,
            roof=roof,
            footprint=footprint,
            residual_threshold_m=0.08,
            min_height_m=2.0,
            cell_size_m=0.5,
            min_cell_points=2,
        )
        self.assertEqual(
            json.dumps(first, sort_keys=True),
            json.dumps(second, sort_keys=True),
        )

    def test_frame_mismatch_is_rejected(self) -> None:
        xyz = self._synthetic_gable()
        roof, footprint = self._roof_and_footprint(xyz)
        footprint["origin_x"] += 1.0
        with self.assertRaisesRegex(ValueError, "origin mismatch"):
            analyze_topology_evidence(xyz, roof=roof, footprint=footprint)

    def test_boundary_obj_is_diagnostic_lines_only(self) -> None:
        xyz = self._synthetic_gable()
        roof, footprint = self._roof_and_footprint(xyz)
        topology = analyze_topology_evidence(
            xyz,
            roof=roof,
            footprint=footprint,
            residual_threshold_m=0.08,
            min_height_m=2.0,
            cell_size_m=0.5,
            min_cell_points=2,
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "topology.obj"
            write_topology_boundary_obj(path, topology, footprint)
            text = path.read_text(encoding="utf-8")

        self.assertIn("line evidence only", text)
        self.assertIn("o footprint_01", text)
        self.assertIn("o boundary_", text)
        self.assertIn("\nl ", text)
        self.assertNotIn("\nf ", text)


if __name__ == "__main__":
    unittest.main()
