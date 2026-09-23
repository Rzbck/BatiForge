from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from batiforge.reconstruction.high_structure_assembly import (
    assemble_high_structures,
    write_obj,
    write_ply,
)


class HighStructureAssemblyTests(unittest.TestCase):
    def _component(
        self,
        component_id: int,
        parent: int,
        *,
        bounds: tuple[float, float, float, float, float, float],
        strong: bool = True,
        points: int = 10,
    ):
        x0, x1, y0, y1, z0, z1 = bounds
        return {
            "component_id": component_id,
            "parent_xy_component_id": parent,
            "point_count": points,
            "reconstruction_gate": strong,
            "evidence_class": "strong_protrusion_candidate" if strong else "local_protrusion_candidate",
            "local_bounds_m": {
                "min_x": x0,
                "max_x": x1,
                "min_y": y0,
                "max_y": y1,
                "min_z": z0,
                "max_z": z1,
                "width_x": x1 - x0,
                "depth_y": y1 - y0,
                "height_z": z1 - z0,
            },
        }

    def _record(self, component_id: int, z: float):
        return {
            "component_id": component_id,
            "x": 0.0,
            "y": 0.0,
            "z": z,
        }

    def test_stacked_strong_components_same_parent_are_assembled(self):
        refined = {
            "schema_version": 1,
            "georeference": {"local_axes": "X east / Y north / Z up"},
            "components": [
                self._component(1, 7, bounds=(-3, 3, -2, 2, 20.0, 29.0), points=20),
                self._component(2, 7, bounds=(-2.9, 2.9, -1.9, 1.9, 6.0, 18.6), points=30),
            ],
            "point_records": [
                self._record(1, 22.0),
                self._record(2, 12.0),
            ],
        }
        result = assemble_high_structures(
            refined,
            min_xy_overlap_ratio=0.65,
            max_vertical_gap_m=1.75,
        )
        self.assertEqual(result["assembly_count"], 1)
        self.assertEqual(result["merged_assembly_count"], 1)
        assembly = result["assemblies"][0]
        self.assertEqual(assembly["member_component_ids"], [1, 2])
        self.assertAlmostEqual(assembly["max_observed_vertical_gap_m"], 1.4, places=4)
        self.assertTrue(assembly["evidence_gap_is_inferred"])

    def test_different_parent_components_are_not_assembled(self):
        refined = {
            "schema_version": 1,
            "components": [
                self._component(1, 1, bounds=(-2, 2, -2, 2, 10, 15)),
                self._component(2, 2, bounds=(-2, 2, -2, 2, 15.5, 20)),
            ],
            "point_records": [],
        }
        result = assemble_high_structures(refined)
        self.assertEqual(result["assembly_count"], 2)
        self.assertEqual(result["merged_assembly_count"], 0)

    def test_poor_xy_overlap_prevents_assembly(self):
        refined = {
            "schema_version": 1,
            "components": [
                self._component(1, 1, bounds=(-4, -1, -1, 1, 10, 15)),
                self._component(2, 1, bounds=(1, 4, -1, 1, 15.2, 20)),
            ],
            "point_records": [],
        }
        result = assemble_high_structures(refined)
        self.assertEqual(result["assembly_count"], 2)

    def test_residual_components_remain_outside_reconstruction_assemblies(self):
        refined = {
            "schema_version": 1,
            "components": [
                self._component(1, 1, bounds=(-2, 2, -2, 2, 10, 20)),
                self._component(2, 1, bounds=(-1, 1, -1, 1, 12, 12.2), strong=False),
            ],
            "point_records": [self._record(1, 15.0), self._record(2, 12.1)],
        }
        result = assemble_high_structures(refined)
        self.assertEqual(result["assembly_count"], 1)
        self.assertEqual(result["residual_component_count"], 1)
        self.assertEqual(len(result["point_records"]), 1)

    def test_outputs_mark_assemblies_without_claiming_production_geometry(self):
        refined = {
            "schema_version": 1,
            "components": [
                self._component(1, 1, bounds=(-1, 1, -1, 1, 10, 14)),
            ],
            "point_records": [self._record(1, 12.0)],
        }
        result = assemble_high_structures(refined)
        with tempfile.TemporaryDirectory() as tmp:
            ply = Path(tmp) / "assembled.ply"
            obj = Path(tmp) / "assembled.obj"
            write_ply(ply, result)
            write_obj(obj, result)
            ply_text = ply.read_text(encoding="utf-8")
            obj_text = obj.read_text(encoding="utf-8")
        self.assertIn("property int assembly_id", ply_text)
        self.assertIn("high_structure_assembly_01", obj_text)
        self.assertIn("NOT production geometry", obj_text)


if __name__ == "__main__":
    unittest.main()
