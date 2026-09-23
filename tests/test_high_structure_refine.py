from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from batiforge.reconstruction.high_structure_refine import (
    refine_high_structures,
    write_obj,
    write_ply,
)


class HighStructureRefineTests(unittest.TestCase):
    def _detected(self, records):
        return {
            "schema_version": 1,
            "georeference": {
                "origin_x": 0.0,
                "origin_y": 0.0,
                "ground_z": 0.0,
                "horizontal_crs": "EPSG:2154",
                "vertical_datum": "IGN69",
            },
            "main_roof_ceiling_height_m": 15.0,
            "component_count": 1,
            "point_records": records,
        }

    def test_vertical_layers_with_same_xy_are_split(self):
        records = []
        for index in range(8):
            records.append(
                {
                    "component_id": 1,
                    "x": 0.05 * index,
                    "y": 0.03 * index,
                    "z": 11.0 + 0.03 * index,
                    "excess_above_resolved_roof_m": 4.5,
                }
            )
        for index in range(8):
            records.append(
                {
                    "component_id": 1,
                    "x": 0.05 * index,
                    "y": 0.03 * index,
                    "z": 19.0 + 0.15 * index,
                    "excess_above_resolved_roof_m": 8.0,
                }
            )

        result = refine_high_structures(
            self._detected(records),
            xy_cell_m=0.5,
            z_cell_m=0.75,
            min_component_points=4,
        )
        self.assertEqual(result["component_count"], 2)
        self.assertEqual(result["strong_candidate_count"], 1)
        strong = [item for item in result["components"] if item["reconstruction_gate"]]
        self.assertGreater(strong[0]["height_above_ground_m"]["min"], 18.0)

    def test_vertically_connected_protrusion_stays_one_component(self):
        records = [
            {
                "component_id": 1,
                "x": 0.1 * (index % 3),
                "y": 0.1 * ((index // 3) % 3),
                "z": 15.8 + 0.55 * index,
                "excess_above_resolved_roof_m": 1.2 + 0.2 * index,
            }
            for index in range(12)
        ]
        result = refine_high_structures(
            self._detected(records),
            xy_cell_m=0.5,
            z_cell_m=0.75,
            min_component_points=4,
        )
        self.assertEqual(result["component_count"], 1)
        self.assertEqual(result["strong_candidate_count"], 1)
        self.assertEqual(result["components"][0]["evidence_class"], "strong_protrusion_candidate")

    def test_thin_local_residual_is_not_auto_reconstruction_gate(self):
        records = [
            {
                "component_id": 1,
                "x": 0.1 * index,
                "y": 0.05 * index,
                "z": 11.2 + 0.01 * index,
                "excess_above_resolved_roof_m": 5.0,
            }
            for index in range(8)
        ]
        result = refine_high_structures(
            self._detected(records),
            min_component_points=4,
        )
        self.assertEqual(result["component_count"], 1)
        component = result["components"][0]
        self.assertFalse(component["reconstruction_gate"])
        self.assertEqual(component["evidence_class"], "local_protrusion_candidate")

    def test_outputs_preserve_component_ids(self):
        records = [
            {
                "component_id": 1,
                "x": 0.1 * index,
                "y": 0.0,
                "z": 17.0 + 0.2 * index,
                "excess_above_resolved_roof_m": 2.0,
            }
            for index in range(8)
        ]
        result = refine_high_structures(self._detected(records), min_component_points=4)
        with tempfile.TemporaryDirectory() as tmp:
            ply = Path(tmp) / "refined.ply"
            obj = Path(tmp) / "refined.obj"
            write_ply(ply, result)
            write_obj(obj, result)
            self.assertIn("property int component_id", ply.read_text(encoding="utf-8"))
            self.assertIn("strong_protrusion_candidate", obj.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
