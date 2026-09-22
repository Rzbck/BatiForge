from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from batiforge.reconstruction.roof_planes import (
    analyze_roof_planes,
    write_diagnostic_obj,
)


class RoofPlaneTests(unittest.TestCase):
    def _synthetic_gable(self) -> np.ndarray:
        rng = np.random.default_rng(12345)

        left_xy = np.column_stack(
            (
                rng.uniform(-10.0, 0.0, 1200),
                rng.uniform(-8.0, 8.0, 1200),
            )
        )
        right_xy = np.column_stack(
            (
                rng.uniform(0.0, 10.0, 1200),
                rng.uniform(-8.0, 8.0, 1200),
            )
        )

        left_z = 110.0 + 0.4 * left_xy[:, 0] + rng.normal(0.0, 0.02, 1200)
        right_z = 110.0 - 0.4 * right_xy[:, 0] + rng.normal(0.0, 0.02, 1200)

        left = np.column_stack((1000.0 + left_xy[:, 0], 2000.0 + left_xy[:, 1], left_z))
        right = np.column_stack((1000.0 + right_xy[:, 0], 2000.0 + right_xy[:, 1], right_z))

        outliers = np.column_stack(
            (
                rng.uniform(990.0, 1010.0, 180),
                rng.uniform(1992.0, 2008.0, 180),
                rng.uniform(103.0, 114.0, 180),
            )
        )
        return np.vstack((left, right, outliers))

    def test_two_gable_planes_are_recovered_deterministically(self) -> None:
        xyz = self._synthetic_gable()

        first = analyze_roof_planes(
            xyz,
            ground_z=100.0,
            min_height_m=2.0,
            residual_threshold_m=0.08,
            min_plane_points=700,
            min_plane_area_m2=20.0,
            max_planes=4,
            ransac_iterations=500,
            seed=7,
        )
        second = analyze_roof_planes(
            xyz,
            ground_z=100.0,
            min_height_m=2.0,
            residual_threshold_m=0.08,
            min_plane_points=700,
            min_plane_area_m2=20.0,
            max_planes=4,
            ransac_iterations=500,
            seed=7,
        )

        self.assertEqual(first.to_json(), second.to_json())
        self.assertEqual(len(first.planes), 2)
        self.assertGreater(first.coverage_ratio, 0.85)

        slopes = sorted(plane.slope_deg for plane in first.planes)
        expected_slope = np.degrees(np.arctan(0.4))
        self.assertAlmostEqual(slopes[0], expected_slope, delta=0.5)
        self.assertAlmostEqual(slopes[1], expected_slope, delta=0.5)

        coefficients = sorted((plane.a for plane in first.planes))
        self.assertAlmostEqual(coefficients[0], -0.4, delta=0.02)
        self.assertAlmostEqual(coefficients[1], 0.4, delta=0.02)
        self.assertTrue(all(plane.rmse_m < 0.05 for plane in first.planes))
        self.assertTrue(all(plane.area_m2 > 100.0 for plane in first.planes))

    def test_summary_preserves_metric_reference_and_height_evidence(self) -> None:
        xyz = self._synthetic_gable()
        analysis = analyze_roof_planes(
            xyz,
            ground_z=100.0,
            horizontal_crs="EPSG:2154",
            vertical_datum="IGN69",
            residual_threshold_m=0.08,
            min_plane_points=700,
            min_plane_area_m2=20.0,
            ransac_iterations=300,
            seed=9,
        )

        payload = json.loads(analysis.to_json())
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["georeference"]["horizontal_crs"], "EPSG:2154")
        self.assertEqual(payload["georeference"]["vertical_datum"], "IGN69")
        self.assertEqual(payload["georeference"]["ground_z"], 100.0)
        self.assertEqual(payload["source_point_count"], len(xyz))
        self.assertIn("p50", payload["z_above_ground_quantiles_m"])
        self.assertIn("ge_22m", payload["high_structure_counts"])

    def test_diagnostic_obj_is_local_and_records_georeference(self) -> None:
        analysis = analyze_roof_planes(
            self._synthetic_gable(),
            ground_z=100.0,
            residual_threshold_m=0.08,
            min_plane_points=700,
            min_plane_area_m2=20.0,
            ransac_iterations=300,
            seed=11,
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "roof.obj"
            write_diagnostic_obj(path, analysis)
            text = path.read_text(encoding="utf-8")

        self.assertIn("# horizontal_crs=EPSG:2154", text)
        self.assertIn("# vertical_datum=IGN69", text)
        self.assertIn("# ground_z=100.000000", text)
        self.assertIn("o roof_plane_01", text)
        self.assertIn("\nv ", text)
        self.assertIn("\nf ", text)


if __name__ == "__main__":
    unittest.main()
