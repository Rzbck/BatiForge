from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from batiforge.reconstruction.shell_preview import (
    build_shell_preview,
    write_shell_obj,
    write_shell_ply,
)


class ShellPreviewTests(unittest.TestCase):
    def _fixture(self):
        roof = {
            "georeference": {
                "origin_x": 0.0,
                "origin_y": 0.0,
                "ground_z": 100.0,
                "horizontal_crs": "EPSG:2154",
                "vertical_datum": "IGN69",
            },
            "planes": [
                {"index": 1, "a": 0.0, "b": 0.0, "c": 105.0},
                {"index": 2, "a": 0.0, "b": 0.0, "c": 108.0},
            ],
        }
        footprint = {
            "origin_x": 0.0,
            "origin_y": 0.0,
            "target_crs": "EPSG:2154",
            "polygons_local_xy": [[[0, 0], [10, 0], [10, 10], [0, 10]]],
        }
        refined = {
            "georeference": roof["georeference"],
            "resolved_area_m2": 100.0,
            "resolved_area_ratio": 1.0,
            "remaining_unresolved_area_m2": 0.0,
            "regions": [
                {
                    "region_index": 1,
                    "plane_index": 1,
                    "area_xy_m2": 50.0,
                    "provenance": "direct_lidar",
                    "vertices_local_xyz": [[0, 0, 5], [5, 0, 5], [5, 10, 5], [0, 10, 5]],
                },
                {
                    "region_index": 2,
                    "plane_index": 2,
                    "area_xy_m2": 50.0,
                    "provenance": "direct_lidar",
                    "vertices_local_xyz": [[5, 0, 8], [10, 0, 8], [10, 10, 8], [5, 10, 8]],
                },
            ],
        }
        topology = {
            "adjacencies": [
                {
                    "plane_a": 1,
                    "plane_b": 2,
                    "approx_boundary_length_m": 10.0,
                    "relation": "height_step_or_overlap_candidate",
                }
            ],
            "boundary_segments": [
                {"plane_a": 1, "plane_b": 2, "x0": 5.0, "y0": 0.0, "x1": 5.0, "y1": 5.0},
                {"plane_a": 1, "plane_b": 2, "x0": 5.0, "y0": 5.0, "x1": 5.0, "y1": 10.0},
            ],
        }
        return refined, roof, footprint, topology

    def test_full_supported_perimeter_and_height_step(self):
        refined, roof, footprint, topology = self._fixture()
        shell = build_shell_preview(
            refined,
            roof=roof,
            footprint=footprint,
            topology=topology,
        )
        self.assertAlmostEqual(shell["supported_perimeter_ratio"], 1.0, places=6)
        self.assertEqual(shell["height_step_face_count"], 1)
        self.assertFalse(shell["watertight_claim"])
        step = shell["height_step_faces"][0]
        zs = [vertex[2] for vertex in step["vertices_local_xyz"]]
        self.assertIn(5.0, zs)
        self.assertIn(8.0, zs)

    def test_unresolved_boundary_gap_reduces_wall_coverage(self):
        refined, roof, footprint, topology = self._fixture()
        refined["regions"][1]["vertices_local_xyz"] = [
            [5, 2, 8], [10, 2, 8], [10, 10, 8], [5, 10, 8]
        ]
        refined["resolved_area_m2"] = 90.0
        refined["resolved_area_ratio"] = 0.9
        refined["remaining_unresolved_area_m2"] = 10.0
        shell = build_shell_preview(
            refined,
            roof=roof,
            footprint=footprint,
            topology=topology,
        )
        self.assertLess(shell["supported_perimeter_ratio"], 1.0)
        self.assertGreater(shell["supported_perimeter_ratio"], 0.8)

    def test_obj_and_ply_emit_named_shell_geometry(self):
        refined, roof, footprint, topology = self._fixture()
        shell = build_shell_preview(
            refined,
            roof=roof,
            footprint=footprint,
            topology=topology,
        )
        with tempfile.TemporaryDirectory() as tmp:
            obj = Path(tmp) / "shell.obj"
            ply = Path(tmp) / "shell.ply"
            write_shell_obj(obj, shell)
            write_shell_ply(ply, shell)
            obj_text = obj.read_text(encoding="utf-8")
            ply_text = ply.read_text(encoding="utf-8")
            self.assertIn("g roof", obj_text)
            self.assertIn("g perimeter_walls", obj_text)
            self.assertIn("g height_steps", obj_text)
            self.assertIn("face_type 0=roof 1=perimeter_wall 2=height_step 3=ground", ply_text)


if __name__ == "__main__":
    unittest.main()
