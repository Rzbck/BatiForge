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

    def _split_assembly(self, link_overlap: float = 0.82):
        records = []
        for component_id, levels in (
            (1, (10.0, 11.0)),
            (2, (13.2, 14.2)),
        ):
            for z in levels:
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
                            "component_id": component_id,
                            "x": x,
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
                    "member_component_ids": [1, 2],
                    "member_count": 2,
                    "point_count": len(records),
                    "reconstruction_gate": True,
                    "max_observed_vertical_gap_m": 1.4,
                }
            ],
            "links": [
                {
                    "component_a": 1,
                    "component_b": 2,
                    "xy_overlap_ratio": link_overlap,
                    "vertical_gap_m": 1.4,
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

    def test_assembly_evidence_recovers_split_strong_components(self):
        result = build_high_structure_mesh_with_recovery(
            self._split_assembly(),
            slice_height_m=1.0,
            min_slice_points=8,
            min_section_area_m2=0.2,
            ring_vertices=8,
            max_bridge_gap_m=2.0,
            adaptive_target_sections=2,
            adaptive_max_band_height_m=0.5,
            recovery_gap_factor=1.30,
            min_gap_xy_overlap_ratio=0.55,
            max_assembly_evidence_gap_m=1.75,
            min_assembly_link_overlap_ratio=0.65,
        )
        self.assertEqual(result["mesh_count"], 1)
        self.assertEqual(result["skipped_count"], 0)
        mesh = result["meshes"][0]
        self.assertEqual(mesh["section_mode"], "assembly_link_gap_recovery")
        self.assertEqual(mesh["assembly_internal_link_count"], 1)
        self.assertAlmostEqual(mesh["assembly_observed_vertical_gap_m"], 1.4)
        self.assertGreaterEqual(mesh["assembly_min_link_xy_overlap_ratio"], 0.65)

    def test_assembly_evidence_rejects_weak_link(self):
        result = build_high_structure_mesh_with_recovery(
            self._split_assembly(link_overlap=0.40),
            slice_height_m=1.0,
            min_slice_points=8,
            min_section_area_m2=0.2,
            ring_vertices=8,
            max_bridge_gap_m=2.0,
            adaptive_target_sections=2,
            adaptive_max_band_height_m=0.5,
            recovery_gap_factor=1.30,
            min_gap_xy_overlap_ratio=0.55,
            max_assembly_evidence_gap_m=1.75,
            min_assembly_link_overlap_ratio=0.65,
        )
        self.assertEqual(result["mesh_count"], 0)
        self.assertEqual(result["skipped_count"], 1)
        self.assertEqual(result["recovery"]["recovered_count"], 0)
        self.assertLess(
            result["skipped"][0]["assembly_min_link_xy_overlap_ratio"],
            0.65,
        )


if __name__ == "__main__":
    unittest.main()
