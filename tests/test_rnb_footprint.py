from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from batiforge.reconstruction.rnb_footprint import (
    project_geojson_footprint,
    write_footprint_obj,
)


class RnbFootprintTests(unittest.TestCase):
    def _feature(self) -> dict:
        return {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [6.09830, 45.90855],
                    [6.09860, 45.90855],
                    [6.09860, 45.90880],
                    [6.09830, 45.90880],
                    [6.09830, 45.90855],
                ]],
            },
            "properties": {"rnb_id": "TEST12345678"},
        }

    def test_projection_is_metric_local_and_deterministic(self) -> None:
        first = project_geojson_footprint(
            self._feature(),
            rnb_id="TEST12345678",
            origin_x=940133.586,
            origin_y=6539042.591,
        )
        second = project_geojson_footprint(
            self._feature(),
            rnb_id="TEST12345678",
            origin_x=940133.586,
            origin_y=6539042.591,
        )

        self.assertEqual(first.to_json(), second.to_json())
        payload = json.loads(first.to_json())
        self.assertEqual(payload["source_crs"], "EPSG:4326")
        self.assertEqual(payload["target_crs"], "EPSG:2154")
        self.assertEqual(len(payload["polygons_abs_xy"]), 1)
        self.assertEqual(len(payload["polygons_abs_xy"][0]), 4)
        self.assertGreater(payload["planimetric_area_m2"], 100.0)
        self.assertLess(payload["planimetric_area_m2"], 2000.0)

    def test_diagnostic_obj_uses_same_local_origin(self) -> None:
        footprint = project_geojson_footprint(
            self._feature(),
            rnb_id="TEST12345678",
            origin_x=940133.586,
            origin_y=6539042.591,
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "footprint.obj"
            write_footprint_obj(path, footprint)
            text = path.read_text(encoding="utf-8")

        self.assertIn("# rnb_id=TEST12345678", text)
        self.assertIn("# target_crs=EPSG:2154", text)
        self.assertIn("o rnb_footprint_01", text)
        self.assertIn("\nv ", text)
        self.assertIn("\nl ", text)

    def test_multipolygon_outer_rings_are_preserved(self) -> None:
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "MultiPolygon",
                "coordinates": [
                    [[[6.0, 45.0], [6.0001, 45.0], [6.0, 45.0001], [6.0, 45.0]]],
                    [[[6.001, 45.001], [6.0011, 45.001], [6.001, 45.0011], [6.001, 45.001]]],
                ],
            },
            "properties": {},
        }
        footprint = project_geojson_footprint(
            feature,
            rnb_id="TEST12345678",
            origin_x=0.0,
            origin_y=0.0,
        )
        self.assertEqual(len(footprint.polygons_abs_xy), 2)


if __name__ == "__main__":
    unittest.main()
