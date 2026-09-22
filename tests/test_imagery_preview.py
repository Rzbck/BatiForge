from __future__ import annotations

import unittest

from batiforge.imagery.preview import shortlist_candidates, thumbnail_url_from_item


class ImageryPreviewTests(unittest.TestCase):
    def test_shortlist_priority_and_sequence_cap(self) -> None:
        candidates = [
            {
                "source_id": "panorama-near",
                "sequence_id": "seq-pan",
                "distance_m": 200.0,
                "panoramic": True,
                "view_class": "panoramic",
                "target_in_fov": True,
            },
            {
                "source_id": "front-unknown",
                "sequence_id": "seq-front",
                "distance_m": 210.0,
                "panoramic": False,
                "view_class": "front",
                "target_in_fov": None,
                "heading_error_deg": 10.0,
            },
            {
                "source_id": "confirmed-1",
                "sequence_id": "seq-confirmed",
                "distance_m": 300.0,
                "panoramic": False,
                "view_class": "lateral",
                "target_in_fov": True,
                "heading_error_deg": 50.0,
            },
            {
                "source_id": "confirmed-2",
                "sequence_id": "seq-confirmed",
                "distance_m": 310.0,
                "panoramic": False,
                "view_class": "front",
                "target_in_fov": True,
                "heading_error_deg": 20.0,
            },
            {
                "source_id": "known-outside-fov",
                "sequence_id": "seq-out",
                "distance_m": 100.0,
                "panoramic": False,
                "view_class": "front",
                "target_in_fov": False,
                "heading_error_deg": 30.0,
            },
        ]

        selected = shortlist_candidates(candidates, max_items=4, per_sequence=1)
        self.assertEqual(
            [item["source_id"] for item in selected],
            ["confirmed-1", "front-unknown", "panorama-near"],
        )

    def test_thumbnail_url_prefers_explicit_derivative(self) -> None:
        item = {
            "properties": {
                "geovisio:thumbnail": "https://example.test/thumb.jpg",
            },
            "assets": {
                "other": {
                    "href": "https://example.test/asset-thumb.webp",
                    "roles": ["thumbnail"],
                }
            },
        }
        self.assertEqual(
            thumbnail_url_from_item(item),
            "https://example.test/thumb.jpg",
        )

    def test_thumbnail_url_reads_stac_thumbnail_role(self) -> None:
        item = {
            "properties": {},
            "assets": {
                "preview": {
                    "href": "https://example.test/asset-thumb.webp",
                    "roles": ["thumbnail"],
                }
            },
        }
        self.assertEqual(
            thumbnail_url_from_item(item),
            "https://example.test/asset-thumb.webp",
        )


if __name__ == "__main__":
    unittest.main()
