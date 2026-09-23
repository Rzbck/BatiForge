from __future__ import annotations

import unittest

from batiforge.reconstruction.high_structure_mesh_recovery import (
    build_high_structure_mesh_with_recovery,
)


class HighStructureMeshRecoveryTests(unittest.TestCase):
    def _assembly(self, shifted_upper: bool = False):
        records = []
        levels = (10.0, 11.0, 13.2, 14.2)
        for level_index, z in enumerate(levels):
            shift = 4.0 if shifted_upper and level_index >= 2 else 0.0
            for x, y in (
                (-1.0, -1.0),
                (1.0, -1.0),
                (1.0, 1.0),
                (-1.0, 1.0),
                (0.0, -1.0),
                (1.0, 0.0),
                (0.0, 1.0),
                (-1.0, 0.0),
            ):
                records.append(
                    {
                        "assembly_id": 1,
                        "component_id": 1,
                        "x": x + shift,
                        "y": y,
                        "z": z,
                    }
                )
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

    def test_guarded_recovery_accepts_small_sparse_gap_with_xy_continuity(self):
        result = build_high_structure_mesh_with_recovery(
            self._assembly(),
            slice_height_m=1.0,
            min_slice_points=8,
            min_section_area_m2=0.2,
            ring_vertices=8,
            max_bridge_gap_m=2.0,
            adaptive_target_sections=4,
            adaptive_max_band_height_m=1.0,
            recovery_gap_factor=1.30,
            min_gap_xy_overlap_ratio=0.55,
        )
        self.assertEqual(result["mesh_count"], 1)
        self.assertEqual(result["skipped_count"], 0)
        self.assertEqual(result["recovery"]["recovered_count"], 1)
        mesh = result["meshes"][0]
        self.assertEqual(mesh["section_mode"], "adaptive_gap_recovery")
        self.assertGreater(mesh["max_section_gap_m"], 2.0)
        self.assertGreaterEqual(mesh["recovery_xy_overlap_ratio"], 0.55)

    def test_guarded_recovery_rejects_gap_without_xy_continuity(self):
        result = build_high_structure_mesh_with_recovery(
            self._assembly(shifted_upper=True),
            slice_height_m=1.0,
            min_slice_points=8,
            min_section_area_m2=0.2,
            ring_vertices=8,
            max_bridge_gap_m=2.0,
            adaptive_target_sections=4,
            adaptive_max_band_height_m=1.0,
            recovery_gap_factor=1.30,
            min_gap_xy_overlap_ratio=0.55,
        )
        self.assertEqual(result["mesh_count"], 0)
        self.assertEqual(result["skipped_count"], 1)
        self.assertEqual(result["recovery"]["recovered_count"], 0)
        self.assertTrue(result["skipped"][0].get("recovery_attempted"))


if __name__ == "__main__":
    unittest.main()
