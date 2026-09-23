import json
import tempfile
import unittest
from pathlib import Path

from batiforge.reconstruction.context_ortho import (
    build_wms_params,
    image_size_for_bbox,
    write_textured_obj,
)


class ContextOrthoTests(unittest.TestCase):
    def test_image_size_preserves_metric_aspect(self):
        width, height = image_size_for_bbox((0.0, 0.0, 80.0, 40.0), gsd_m=0.20)
        self.assertEqual(width, 400)
        self.assertEqual(height, 200)

    def test_image_size_respects_max_pixels(self):
        width, height = image_size_for_bbox((0.0, 0.0, 1000.0, 500.0), gsd_m=0.10, max_pixels=1000)
        self.assertEqual(width, 1000)
        self.assertEqual(height, 500)

    def test_wms_params_use_epsg2154_bbox(self):
        params = build_wms_params(
            (100.0, 200.0, 180.0, 240.0),
            layer="ORTHOIMAGERY.ORTHOPHOTOS",
            width=400,
            height=200,
        )
        self.assertEqual(params["CRS"], "EPSG:2154")
        self.assertEqual(params["BBOX"], "100.0,200.0,180.0,240.0")
        self.assertEqual(params["WIDTH"], "400")
        self.assertEqual(params["HEIGHT"], "200")

    def test_textured_obj_maps_crop_corners_to_uv_corners(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "ground.obj"
            out_obj = root / "ground-ortho.obj"
            out_mtl = root / "ground-ortho.mtl"
            source.write_text(
                "v -10 -20 0\n"
                "v 10 -20 0\n"
                "v 10 20 0\n"
                "v -10 20 0\n"
                "f 1 2 3\n"
                "f 1 3 4\n",
                encoding="utf-8",
            )
            context = {
                "georeference": {"origin_x": 110.0, "origin_y": 220.0},
                "crop_abs_xy": {
                    "min_x": 100.0,
                    "min_y": 200.0,
                    "max_x": 120.0,
                    "max_y": 240.0,
                },
            }
            meta = write_textured_obj(
                source,
                out_obj,
                out_mtl,
                "ortho.jpg",
                context,
            )
            text = out_obj.read_text(encoding="utf-8")
            self.assertIn("vt 0.00000000 0.00000000", text)
            self.assertIn("vt 1.00000000 1.00000000", text)
            self.assertIn("f 1/1 2/2 3/3", text)
            self.assertIn("map_Kd ortho.jpg", out_mtl.read_text(encoding="utf-8"))
            self.assertEqual(meta["vertex_count"], 4)
            self.assertEqual(meta["uv_count"], 4)
            self.assertEqual(meta["face_count"], 2)


if __name__ == "__main__":
    unittest.main()
