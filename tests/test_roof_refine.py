from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from batiforge.reconstruction.roof_refine import (
    refine_roof_cleanup,
    write_refined_obj,
    write_refined_ply,
)


class RoofRefineTests(unittest.TestCase):
    def _roof(self):
        return {
            "planes": [
                {"index": 1, "a": 0.0, "b": 0.0, "c": 10.0},
                {"index": 2, "a": 0.1, "b": 0.0, "c": 10.0},
            ]
        }

    def _cleaned(self, unresolved):
        return {
            "georeference": {
                "origin_x": 100.0,
                "origin_y": 200.0,
                "ground_z": 0.0,
                "horizontal_crs": "EPSG:2154",
                "vertical_datum": "IGN69",
            },
            "footprint_area_m2": 100.0,
            "resolved_area_m2": 90.0,
            "resolved_area_ratio": 0.9,
            "high_structure_point_count": 3,
            "regions": [
                {
                    "region_index": 1,
                    "plane_index": 1,
                    "area_xy_m2": 90.0,
                    "provenance": "direct_lidar",
                    "vertices_local_xyz": [
                        [0.0, 0.0, 10.0],
                        [9.0, 0.0, 10.0],
                        [9.0, 10.0, 10.0],
                        [0.0, 10.0, 10.0],
                    ],
                }
            ],
            "unresolved": unresolved,
        }

    def test_medium_gap_with_strict_single_plane_evidence_is_promoted(self):
        cleaned = self._cleaned(
            [
                {
                    "piece_index": 2,
                    "area_m2": 5.5,
                    "reason": "insufficient_support_or_purity",
                    "best_plane_index": 2,
                    "best_plane_support_count": 8,
                    "point_count": 16,
                    "purity": 0.50,
                    "footprint_boundary_shared_m": 1.5,
                    "neighbor_boundary_m_by_plane": {"2": 0.7},
                    "polygon_local_xy": [[9.0, 0.0], [10.0, 0.0], [10.0, 5.5], [9.0, 5.5]],
                }
            ]
        )
        result = refine_roof_cleanup(cleaned, roof=self._roof())
        self.assertEqual(result["promoted_region_count"], 1)
        self.assertAlmostEqual(result["promoted_area_m2"], 5.5)
        self.assertEqual(result["remaining_unresolved_count"], 0)
        self.assertEqual(result["promoted"][0]["plane_index"], 2)
        self.assertEqual(result["promoted"][0]["provenance"], "inferred_medium_gap_strict")

    def test_low_purity_medium_gap_stays_unresolved(self):
        cleaned = self._cleaned(
            [
                {
                    "piece_index": 2,
                    "area_m2": 5.5,
                    "reason": "insufficient_support_or_purity",
                    "best_plane_index": 2,
                    "purity": 0.29,
                    "footprint_boundary_shared_m": 3.0,
                    "neighbor_boundary_m_by_plane": {"2": 2.0},
                    "polygon_local_xy": [[9.0, 0.0], [10.0, 0.0], [10.0, 5.5], [9.0, 5.5]],
                }
            ]
        )
        result = refine_roof_cleanup(cleaned, roof=self._roof())
        self.assertEqual(result["promoted_region_count"], 0)
        self.assertEqual(result["remaining_unresolved_count"], 1)

    def test_multi_plane_neighbor_gap_stays_unresolved(self):
        cleaned = self._cleaned(
            [
                {
                    "piece_index": 2,
                    "area_m2": 3.0,
                    "reason": "insufficient_support_or_purity",
                    "best_plane_index": 2,
                    "purity": 0.60,
                    "footprint_boundary_shared_m": 2.0,
                    "neighbor_boundary_m_by_plane": {"1": 0.7, "2": 1.2},
                    "polygon_local_xy": [[9.0, 0.0], [10.0, 0.0], [10.0, 3.0], [9.0, 3.0]],
                }
            ]
        )
        result = refine_roof_cleanup(cleaned, roof=self._roof())
        self.assertEqual(result["promoted_region_count"], 0)
        self.assertEqual(result["remaining_unresolved_count"], 1)

    def test_obj_and_ply_are_emitted_with_provenance(self):
        cleaned = self._cleaned(
            [
                {
                    "piece_index": 2,
                    "area_m2": 4.0,
                    "reason": "insufficient_support_or_purity",
                    "best_plane_index": 2,
                    "purity": 0.50,
                    "footprint_boundary_shared_m": 2.0,
                    "neighbor_boundary_m_by_plane": {"2": 1.0},
                    "polygon_local_xy": [[9.0, 0.0], [10.0, 0.0], [10.0, 4.0], [9.0, 4.0]],
                }
            ]
        )
        result = refine_roof_cleanup(cleaned, roof=self._roof())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ply = root / "roof.ply"
            obj = root / "roof.obj"
            write_refined_ply(ply, result)
            write_refined_obj(obj, result)
            ply_text = ply.read_text(encoding="utf-8")
            obj_text = obj.read_text(encoding="utf-8")
            self.assertIn("provenance_code", ply_text)
            self.assertIn(" 2\n", ply_text)
            self.assertIn("inferred_medium_gap_strict", obj_text)
            self.assertIn("f ", obj_text)


if __name__ == "__main__":
    unittest.main()
