from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from batiforge.reconstruction.high_structure_mesh import (
    build_high_structure_mesh,
    write_composite_obj,
    write_high_structure_obj,
)


class HighStructureMeshTests(unittest.TestCase):
    def _assembly(self):
        records = []
        points_by_z = {
            10.0: [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0), (0.0, -1.0), (1.0, 0.0), (0.0, 1.0), (-1.0, 0.0)],
            11.0: [(-0.9, -0.9), (0.9, -0.9), (0.9, 0.9), (-0.9, 0.9), (0.0, -0.9), (0.9, 0.0), (0.0, 0.9), (-0.9, 0.0)],
            12.0: [(-0.7, -0.7), (0.7, -0.7), (0.7, 0.7), (-0.7, 0.7), (0.0, -0.7), (0.7, 0.0), (0.0, 0.7), (-0.7, 0.0)],
        }
        for z, xy in points_by_z.items():
            for x, y in xy:
                records.append({"assembly_id": 1, "component_id": 1, "x": x, "y": y, "z": z})
        return {
            "schema_version": 1,
            "georeference": {
                "origin_x": 100.0,
                "origin_y": 200.0,
                "ground_z": 0.0,
                "horizontal_crs": "EPSG:2154",
                "vertical_datum": "IGN69",
            },
            "assemblies": [
                {
                    "assembly_id": 1,
                    "point_count": len(records),
                    "reconstruction_gate": True,
                }
            ],
            "point_records": records,
        }

    def _shell(self):
        return {
            "georeference": self._assembly()["georeference"],
            "roof_regions": [
                {
                    "region_index": 1,
                    "plane_index": 1,
                    "vertices_local_xyz": [
                        [-3.0, -2.0, 4.0],
                        [3.0, -2.0, 4.0],
                        [3.0, 2.0, 4.0],
                        [-3.0, 2.0, 4.0],
                    ],
                }
            ],
            "perimeter_walls": [
                {
                    "provenance": "direct_supported_perimeter",
                    "vertices_local_xyz": [
                        [-3.0, -2.0, 0.0],
                        [3.0, -2.0, 0.0],
                        [3.0, -2.0, 4.0],
                        [-3.0, -2.0, 4.0],
                    ],
                }
            ],
            "height_step_faces": [],
            "floor_polygon_local_xy": [
                [-3.0, -2.0],
                [3.0, -2.0],
                [3.0, 2.0],
                [0.5, 1.0],
                [-3.0, 2.0],
            ],
        }

    def test_layered_lidar_builds_multiple_loft_sections(self):
        result = build_high_structure_mesh(
            self._assembly(),
            slice_height_m=1.0,
            min_slice_points=8,
            min_section_area_m2=0.2,
            ring_vertices=8,
            max_bridge_gap_m=1.5,
        )
        self.assertEqual(result["mesh_count"], 1)
        mesh = result["meshes"][0]
        self.assertEqual(mesh["section_count"], 3)
        self.assertEqual(mesh["ring_vertices"], 8)
        self.assertAlmostEqual(mesh["sections"][0]["z_m"], 10.0)
        self.assertAlmostEqual(mesh["sections"][-1]["z_m"], 12.0)

    def test_sparse_evidence_is_not_meshed(self):
        assembly = self._assembly()
        assembly["point_records"] = assembly["point_records"][:4]
        assembly["assemblies"][0]["point_count"] = 4
        result = build_high_structure_mesh(
            assembly,
            min_slice_points=6,
        )
        self.assertEqual(result["mesh_count"], 0)
        self.assertEqual(result["skipped_count"], 1)

    def test_composite_obj_contains_shell_ear_clipped_floor_and_loft(self):
        result = build_high_structure_mesh(
            self._assembly(),
            slice_height_m=1.0,
            min_slice_points=8,
            min_section_area_m2=0.2,
            ring_vertices=8,
            max_bridge_gap_m=1.5,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            high_obj = root / "high.obj"
            composite = root / "composite.obj"
            write_high_structure_obj(high_obj, result)
            write_composite_obj(composite, self._shell(), result)
            high_text = high_obj.read_text(encoding="utf-8")
            composite_text = composite.read_text(encoding="utf-8")

        self.assertIn("o high_structure_01", high_text)
        self.assertIn("o shell_ground_floor", composite_text)
        self.assertIn("o high_structure_01", composite_text)
        # Concave floor is ear-clipped into triangles instead of one 5-vertex face.
        floor_part = composite_text.split("o shell_ground_floor", 1)[1].split("o high_structure_01", 1)[0]
        face_lines = [line for line in floor_part.splitlines() if line.startswith("f ")]
        self.assertGreaterEqual(len(face_lines), 3)
        self.assertTrue(all(len(line.split()) == 4 for line in face_lines))


if __name__ == "__main__":
    unittest.main()
