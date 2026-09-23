import unittest

from batiforge.reconstruction.facade_opening_grounding import (
    box_iou,
    canonical_label,
    choose_facade_box,
    dedupe_detections,
)


class FacadeOpeningGroundingTests(unittest.TestCase):
    def test_canonical_label(self):
        self.assertEqual(canonical_label("arched window"), "window")
        self.assertEqual(canonical_label("church entrance"), "door")
        self.assertEqual(canonical_label("building facade"), "facade")
        self.assertIsNone(canonical_label("tree"))

    def test_iou_and_dedupe(self):
        self.assertAlmostEqual(box_iou([0, 0, 10, 10], [0, 0, 10, 10]), 1.0)
        items = [
            {"class": "window", "score": 0.9, "bbox_px": [0, 0, 10, 10]},
            {"class": "window", "score": 0.5, "bbox_px": [1, 1, 9, 9]},
            {"class": "door", "score": 0.8, "bbox_px": [1, 1, 9, 9]},
        ]
        kept = dedupe_detections(items, 0.4)
        self.assertEqual(len(kept), 2)
        self.assertEqual({item["class"] for item in kept}, {"window", "door"})

    def test_choose_facade_prefers_box_containing_openings(self):
        openings = [
            {"bbox_px": [20, 20, 30, 40]},
            {"bbox_px": [40, 20, 50, 40]},
        ]
        facade = choose_facade_box(
            [
                {"bbox_px": [0, 0, 10, 10], "score": 0.99},
                {"bbox_px": [10, 5, 60, 70], "score": 0.70},
            ],
            openings,
            (100, 100),
        )
        self.assertEqual(facade, [10.0, 5.0, 60.0, 70.0])


if __name__ == "__main__":
    unittest.main()
