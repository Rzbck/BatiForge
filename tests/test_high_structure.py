from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from batiforge.reconstruction.high_structure import (
    detect_high_structures,
    write_high_structure_obj,
    write_high_structure_ply,
)


class HighStructureTests(unittest.TestCase):
    def _payloads(self):
        roof = {
            "georeference": {
                "origin_x": 1000.0,
                "origin_y": 2000.0,
                "ground_z": 100.0,
                "horizontal_crs": "EPSG:2154",
                "vertical_datum": "IGN69",
            },
            "planes": [
                {"index": 1, "a": 0.0, "b": 0.0, "c": 110.0},
            ],
        }
        refined = {
            "georeference": roof["georeference"],
            "footprint_area_m2": 100.0,
            "regions": [
                {
                    "region_index": 1,
                    "plane_index": 1,
                    "area_xy_m2": 100.0,
                    "vertices_local_xyz": [
                        [-5.0, -5.0, 10.0],
                        [5.0, -5.0, 10.0],
                        [5.0, 5.0, 10.0],
                        [-5.0, 5.0, 10.0],
                    ],
                }
            ],
        }
        footprint = {
            "origin_x": 1000.0,
            "origin_y": 2000.0,
            "target_crs": "EPSG:2154",
            "polygons_local_xy": [
                [[-5.0, -5.0], [5.0, -5.0], [5.0, 5.0], [-5.0, 5.0]]
            ],
        }
        return roof, refined, footprint

    def test_detects_roof_relative_component_without_absolute_height_gate(self):
        roof, refined, footprint = self._payloads()
        roof_points = np.asarray(
            [[1000.0 + x, 2000.0 + y, 110.0] for x in (-4, -2, 0, 2, 4) for y in (-4, -2, 0, 2, 4)],
            dtype=np.float64,
        )
        high = np.asarray(
            [
                [1000.00, 2000.00, 111.2],
                [1000.15, 2000.00, 111.8],
                [1000.30, 2000.10, 112.5],
                [1000.05, 2000.25, 113.0],
                [1000.20, 2000.30, 113.8],
                [1000.35, 2000.25, 114.2],
            ],
            dtype=np.float64,
        )
        result = detect_high_structures(
            np.vstack((roof_points, high)),
            roof=roof,
            refined=refined,
            footprint=footprint,
            min_excess_m=0.8,
            cluster_cell_m=0.5,
            min_component_points=4,
        )

        self.assertEqual(result["component_count"], 1)
        self.assertEqual(result["primary_seed_count"], 6)
        component = result["components"][0]
        self.assertEqual(component["point_count"], 6)
        self.assertAlmostEqual(component["height_above_ground_m"]["max"], 14.2, places=4)
        self.assertEqual(component["supporting_plane_indices"], [1])

    def test_separate_clusters_remain_separate(self):
        roof, refined, footprint = self._payloads()
        cluster_a = np.asarray(
            [[999.0 + 0.1 * i, 1999.0 + 0.05 * i, 112.0 + 0.1 * i] for i in range(6)],
            dtype=np.float64,
        )
        cluster_b = np.asarray(
            [[1003.0 + 0.1 * i, 2003.0 + 0.05 * i, 113.0 + 0.1 * i] for i in range(6)],
            dtype=np.float64,
        )
        result = detect_high_structures(
            np.vstack((cluster_a, cluster_b)),
            roof=roof,
            refined=refined,
            footprint=footprint,
            min_excess_m=0.8,
            cluster_cell_m=0.5,
            min_component_points=4,
        )
        self.assertEqual(result["component_count"], 2)
        self.assertEqual(sorted(item["point_count"] for item in result["components"]), [6, 6])

    def test_small_outlier_group_is_rejected(self):
        roof, refined, footprint = self._payloads()
        points = np.asarray(
            [
                [1000.0, 2000.0, 113.0],
                [1000.1, 2000.1, 113.2],
                [1000.2, 2000.1, 113.4],
            ],
            dtype=np.float64,
        )
        result = detect_high_structures(
            points,
            roof=roof,
            refined=refined,
            footprint=footprint,
            min_component_points=4,
        )
        self.assertEqual(result["seed_point_count"], 3)
        self.assertEqual(result["component_count"], 0)

    def test_ply_and_obj_are_diagnostic_and_keep_component_ids(self):
        roof, refined, footprint = self._payloads()
        points = np.asarray(
            [[1000.0 + 0.1 * i, 2000.0, 112.0 + 0.1 * i] for i in range(6)],
            dtype=np.float64,
        )
        result = detect_high_structures(
            points,
            roof=roof,
            refined=refined,
            footprint=footprint,
            min_component_points=4,
        )
        with tempfile.TemporaryDirectory() as tmp:
            ply = Path(tmp) / "high.ply"
            obj = Path(tmp) / "high.obj"
            write_high_structure_ply(ply, result)
            write_high_structure_obj(obj, result)
            ply_text = ply.read_text(encoding="utf-8")
            obj_text = obj.read_text(encoding="utf-8")

        self.assertIn("property int component_id", ply_text)
        self.assertIn("high_structure_candidate_01", obj_text)
        self.assertIn("NOT production reconstruction", obj_text)


if __name__ == "__main__":
    unittest.main()
