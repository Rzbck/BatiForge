from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from batiforge.reconstruction.roof_cleanup import clean_roof_regions, write_clean_ply


class RoofCleanupTests(unittest.TestCase):
    def _roof(self) -> dict:
        return {
            "planes": [
                {"index": 1, "a": 0.1, "b": 0.0, "c": 10.0},
                {"index": 2, "a": -0.1, "b": 0.0, "c": 10.3},
            ]
        }

    def _georef(self) -> dict:
        return {
            "origin_x": 0.0,
            "origin_y": 0.0,
            "ground_z": 0.0,
            "horizontal_crs": "EPSG:2154",
            "vertical_datum": "IGN69",
            "local_axes": "X east / Y north / Z up",
        }

    def _region(self, index: int, plane: int, poly: list[list[float]]) -> dict:
        return {
            "region_index": index,
            "source_piece_index": index,
            "plane_index": plane,
            "area_xy_m2": 1.0,
            "point_count": 10,
            "support_count": 10,
            "purity": 1.0,
            "vertices_local_xyz": [[x, y, 10.0] for x, y in poly],
        }

    def test_small_eave_gap_with_single_neighbor_is_inferred(self) -> None:
        regions = {
            "georeference": self._georef(),
            "footprint_area_m2": 2.0,
            "regions": [self._region(1, 1, [[0, 0], [1, 0], [1, 1], [0, 1]])],
            "unresolved": [
                {
                    "piece_index": 2,
                    "area_m2": 1.0,
                    "point_count": 0,
                    "reason": "no_supported_plane",
                    "polygon_local_xy": [[1, 0], [2, 0], [2, 1], [1, 1]],
                }
            ],
        }
        footprint = {"polygons_local_xy": [[[0, 0], [2, 0], [2, 1], [0, 1]]]}
        result = clean_roof_regions(regions, roof=self._roof(), footprint=footprint)
        self.assertEqual(result["inferred_region_count"], 1)
        self.assertEqual(result["remaining_unresolved_count"], 0)
        self.assertAlmostEqual(result["resolved_area_ratio"], 1.0)
        self.assertEqual(result["inferred"][0]["plane_index"], 1)
        self.assertEqual(result["inferred"][0]["provenance"], "inferred_single_neighbor_eave_extension")

    def test_gap_between_two_planes_remains_unresolved(self) -> None:
        regions = {
            "georeference": self._georef(),
            "footprint_area_m2": 3.0,
            "regions": [
                self._region(1, 1, [[0, 0], [1, 0], [1, 1], [0, 1]]),
                self._region(2, 2, [[2, 0], [3, 0], [3, 1], [2, 1]]),
            ],
            "unresolved": [
                {
                    "piece_index": 3,
                    "area_m2": 1.0,
                    "point_count": 0,
                    "reason": "no_supported_plane",
                    "polygon_local_xy": [[1, 0], [2, 0], [2, 1], [1, 1]],
                }
            ],
        }
        footprint = {"polygons_local_xy": [[[0, 0], [3, 0], [3, 1], [0, 1]]]}
        result = clean_roof_regions(regions, roof=self._roof(), footprint=footprint)
        self.assertEqual(result["inferred_region_count"], 0)
        self.assertEqual(result["remaining_unresolved_count"], 1)
        neighbors = result["unresolved"][0]["neighbor_boundary_m_by_plane"]
        self.assertIn("1", neighbors)
        self.assertIn("2", neighbors)

    def test_weak_lidar_gap_requires_matching_single_neighbor(self) -> None:
        regions = {
            "georeference": self._georef(),
            "footprint_area_m2": 2.0,
            "regions": [self._region(1, 1, [[0, 0], [1, 0], [1, 1], [0, 1]])],
            "unresolved": [
                {
                    "piece_index": 2,
                    "area_m2": 1.0,
                    "point_count": 5,
                    "best_plane_index": 1,
                    "best_plane_support_count": 2,
                    "purity": 0.4,
                    "reason": "insufficient_support_or_purity",
                    "polygon_local_xy": [[1, 0], [2, 0], [2, 1], [1, 1]],
                }
            ],
        }
        footprint = {"polygons_local_xy": [[[0, 0], [2, 0], [2, 1], [0, 1]]]}
        result = clean_roof_regions(regions, roof=self._roof(), footprint=footprint)
        self.assertEqual(result["inferred_region_count"], 1)
        self.assertEqual(result["inferred"][0]["provenance"], "inferred_single_neighbor_weak_lidar")

    def test_ply_records_inference_provenance(self) -> None:
        regions = {
            "georeference": self._georef(),
            "footprint_area_m2": 1.0,
            "regions": [self._region(1, 1, [[0, 0], [1, 0], [1, 1], [0, 1]])],
            "unresolved": [],
        }
        footprint = {"polygons_local_xy": [[[0, 0], [1, 0], [1, 1], [0, 1]]]}
        result = clean_roof_regions(regions, roof=self._roof(), footprint=footprint)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clean.ply"
            write_clean_ply(path, result)
            text = path.read_text(encoding="utf-8")
        self.assertIn("provenance_code", text)
        self.assertIn("X east, Y north, Z up", text)


if __name__ == "__main__":
    unittest.main()
