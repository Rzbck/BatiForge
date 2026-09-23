from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from batiforge.reconstruction.clean_export import build_clean_export, write_obj


class CleanExportTests(unittest.TestCase):
    def _payloads(self):
        refined = {
            "georeference": {
                "origin_x": 0.0,
                "origin_y": 0.0,
                "ground_z": 0.0,
                "horizontal_crs": "EPSG:2154",
                "vertical_datum": "IGN69",
            },
            "resolved_area_m2": 75.0,
            "resolved_area_ratio": 0.75,
            "remaining_unresolved_area_m2": 25.0,
            "regions": [
                {
                    "region_index": 1,
                    "plane_index": 1,
                    "area_xy_m2": 75.0,
                    "vertices_local_xyz": [
                        [0.0, 0.0, 10.0],
                        [10.0, 0.0, 10.0],
                        [10.0, 4.0, 10.0],
                        [4.0, 4.0, 10.0],
                        [4.0, 10.0, 10.0],
                        [0.0, 10.0, 10.0],
                    ],
                }
            ],
        }
        roof = {
            "planes": [{"index": 1, "a": 0.0, "b": 0.0, "c": 10.0}],
        }
        footprint = {
            "polygons_local_xy": [
                [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]
            ]
        }
        topology = {"adjacencies": [], "boundary_segments": []}
        return refined, roof, footprint, topology

    def test_clean_export_closes_missing_perimeter_provisionally(self):
        refined, roof, footprint, topology = self._payloads()
        result = build_clean_export(
            refined=refined,
            roof=roof,
            footprint=footprint,
            topology=topology,
        )
        self.assertAlmostEqual(result["exported_perimeter_ratio"], 1.0, places=6)
        self.assertGreater(result["provisional_wall_count"], 0)
        self.assertGreater(result["provisional_closed_perimeter_m"], 0.0)
        self.assertFalse(result["watertight_claim"])

    def test_obj_keeps_concave_roof_as_polygon_not_first_vertex_fan(self):
        refined, roof, footprint, topology = self._payloads()
        result = build_clean_export(
            refined=refined,
            roof=roof,
            footprint=footprint,
            topology=topology,
            close_perimeter=False,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clean.obj"
            write_obj(path, result)
            lines = path.read_text(encoding="utf-8").splitlines()
        roof_object_index = lines.index("o roof_r001_p01")
        first_face = next(line for line in lines[roof_object_index + 1 :] if line.startswith("f "))
        self.assertEqual(len(first_face.split()) - 1, 6)
        self.assertIn("s off", lines)


if __name__ == "__main__":
    unittest.main()
