import unittest

import numpy as np

from batiforge.reconstruction.facade_projective_detail import _iou, _nms, _pointed_arch, _quatrefoil


class FacadeProjectiveDetailTests(unittest.TestCase):
    def test_iou(self):
        self.assertAlmostEqual(_iou([0,0,10,10],[0,0,10,10]),1.0)
        self.assertEqual(_iou([0,0,1,1],[2,2,3,3]),0.0)

    def test_nms_keeps_different_classes(self):
        items=[
            {"class":"window","score":0.8,"bbox_px":[0,0,10,10]},
            {"class":"window","score":0.7,"bbox_px":[1,1,9,9]},
            {"class":"door","score":0.6,"bbox_px":[1,1,9,9]},
        ]
        out=_nms(items,0.4)
        self.assertEqual(len(out),2)
        self.assertEqual({x["class"] for x in out},{"window","door"})

    def test_pointed_arch_has_vertical_base_and_apex(self):
        pts=_pointed_arch(2.0,4.0)
        self.assertGreater(len(pts),8)
        self.assertAlmostEqual(float(pts[:,1].max()),2.0,places=6)
        self.assertAlmostEqual(float(pts[:,1].min()),-2.0,places=6)

    def test_quatrefoil_is_closed_shape_source(self):
        pts=_quatrefoil(2.0,2.0)
        self.assertEqual(pts.shape,(48,2))
        self.assertTrue(np.isfinite(pts).all())


if __name__ == "__main__":
    unittest.main()
