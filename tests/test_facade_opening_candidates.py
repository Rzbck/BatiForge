import tempfile
import unittest
from pathlib import Path

from batiforge.reconstruction.facade_opening_candidates import (
    extract_vertical_wall_planes,
    map_openings_to_walls,
)


class FacadeOpeningCandidateTests(unittest.TestCase):
    def test_extracts_simple_vertical_wall(self):
        obj = """\
v 0 0 0
v 4 0 0
v 4 0 3
v 0 0 3
f 1 2 3
f 1 3 4
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wall.obj"
            path.write_text(obj, encoding="utf-8")
            walls = extract_vertical_wall_planes(path, min_area_m2=1.0)
        self.assertEqual(len(walls), 1)
        self.assertAlmostEqual(walls[0].width_m, 4.0, places=6)
        self.assertAlmostEqual(walls[0].height_m, 3.0, places=6)

    def test_maps_normal_and_mirrored_candidates(self):
        obj = """\
v 0 0 0
v 4 0 0
v 4 0 3
v 0 0 3
f 1 2 3
f 1 3 4
"""
        segmentation = {
            "facade_aspect_px": 4.0 / 3.0,
            "openings": [
                {
                    "class": "window",
                    "bbox_px": [10, 10, 20, 30],
                    "bbox_facade_norm": {"x0": 0.10, "y0": 0.20, "x1": 0.30, "y1": 0.60},
                    "area_px": 100,
                    "mean_confidence": 0.9,
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wall.obj"
            path.write_text(obj, encoding="utf-8")
            walls = extract_vertical_wall_planes(path, min_area_m2=1.0)
            candidates = map_openings_to_walls(segmentation, walls, top_walls=1)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(len(candidates[0]["openings"]), 1)
        self.assertAlmostEqual(candidates[0]["openings"][0]["width_m"], 0.8, places=6)
        self.assertAlmostEqual(candidates[0]["openings"][0]["height_m"], 1.2, places=6)
        self.assertNotEqual(
            candidates[0]["openings"][0]["center_xyz"][0:2],
            candidates[1]["openings"][0]["center_xyz"][0:2],
        )


if __name__ == "__main__":
    unittest.main()
