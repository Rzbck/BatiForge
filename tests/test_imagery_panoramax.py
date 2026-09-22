from __future__ import annotations

import json
import unittest

from batiforge.imagery.models import (
    angular_difference_deg,
    classify_view_geometry,
    haversine_distance_m,
    initial_bearing_deg,
)
from batiforge.imagery.panoramax import PanoramaxProvider


class _Response:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _Session:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.calls: list[tuple[str, str, dict | None]] = []

    def request(self, method, url, params=None, json=None, timeout=None):
        self.calls.append((method, url, params))

        if url.endswith("/configuration"):
            return _Response(
                {
                    "pictures_license": "etalab-2.0",
                    "pictures_license_url": "https://www.etalab.gouv.fr/licence-ouverte-open-licence/",
                }
            )

        if url == "https://example.test/api":
            return _Response(
                {
                    "links": [
                        {
                            "rel": "license",
                            "href": "https://www.etalab.gouv.fr/licence-ouverte-open-licence/",
                        }
                    ]
                }
            )

        if url.endswith("/search"):
            return _Response(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "id": "near-picture",
                            "collection": "sequence-a",
                            "geometry": {
                                "type": "Point",
                                "coordinates": [6.0984874, 45.9086611],
                            },
                            "properties": {
                                "datetime": "2026-01-01T12:00:00Z",
                                "view:azimuth": 270.0,
                                "proj:shape": [3000, 4000],
                                "pers:interior_orientation": {
                                    "field_of_view": 90,
                                },
                            },
                            "links": [
                                {
                                    "rel": "self",
                                    "href": "https://example.test/api/pictures/near-picture",
                                }
                            ],
                        },
                        {
                            "type": "Feature",
                            "id": "outside-picture",
                            "collection": "sequence-b",
                            "geometry": {
                                "type": "Point",
                                "coordinates": [6.11, 45.92],
                            },
                            "properties": {},
                        },
                    ],
                    "links": [],
                }
            )

        raise AssertionError(f"unexpected request: {method} {url}")


class PanoramaxProviderTests(unittest.TestCase):
    def test_haversine_zero(self) -> None:
        self.assertEqual(haversine_distance_m(45.0, 6.0, 45.0, 6.0), 0.0)

    def test_bearing_and_angular_difference(self) -> None:
        self.assertAlmostEqual(initial_bearing_deg(0.0, 0.0, 1.0, 0.0), 0.0)
        self.assertAlmostEqual(initial_bearing_deg(0.0, 0.0, 0.0, 1.0), 90.0)
        self.assertEqual(angular_difference_deg(359.0, 1.0), 2.0)
        self.assertEqual(angular_difference_deg(10.0, 190.0), 180.0)

    def test_view_geometry_classes(self) -> None:
        front = classify_view_geometry(
            heading_deg=5.0,
            target_bearing_deg=0.0,
            field_of_view_deg=60.0,
            panoramic=False,
        )
        self.assertEqual(front, ("front", 5.0, True))

        lateral = classify_view_geometry(
            heading_deg=90.0,
            target_bearing_deg=0.0,
            field_of_view_deg=90.0,
            panoramic=False,
        )
        self.assertEqual(lateral, ("lateral", 90.0, False))

        rear = classify_view_geometry(
            heading_deg=180.0,
            target_bearing_deg=0.0,
            field_of_view_deg=90.0,
            panoramic=False,
        )
        self.assertEqual(rear, ("rear", 180.0, False))

        panoramic = classify_view_geometry(
            heading_deg=None,
            target_bearing_deg=270.0,
            field_of_view_deg=360.0,
            panoramic=True,
        )
        self.assertEqual(panoramic, ("panoramic", None, True))

        unknown = classify_view_geometry(
            heading_deg=None,
            target_bearing_deg=270.0,
            field_of_view_deg=None,
            panoramic=None,
        )
        self.assertEqual(unknown, ("unknown", None, None))

    def test_metadata_only_survey_filters_by_radius_and_is_deterministic(self) -> None:
        provider = PanoramaxProvider(
            endpoint="https://example.test/api",
            session=_Session(),
        )

        result = provider.survey(
            latitude=45.9086611,
            longitude=6.0984374,
            radius_m=100.0,
            limit=10,
        )

        self.assertEqual(len(result.candidates), 1)
        candidate = result.candidates[0]
        self.assertEqual(candidate.source_id, "near-picture")
        self.assertEqual(candidate.sequence_id, "sequence-a")
        self.assertEqual(candidate.width, 4000)
        self.assertEqual(candidate.height, 3000)
        self.assertEqual(candidate.heading_deg, 270.0)
        self.assertEqual(candidate.field_of_view_deg, 90.0)
        self.assertLess(candidate.distance_m, 10.0)
        self.assertEqual(candidate.license_id, "etalab-2.0")
        self.assertAlmostEqual(candidate.target_bearing_deg or 0.0, 270.0, delta=0.1)
        self.assertLess(candidate.heading_error_deg or 999.0, 0.1)
        self.assertTrue(candidate.target_in_fov)
        self.assertEqual(candidate.view_class, "front")

        first = result.to_json()
        second = result.to_json()
        self.assertEqual(first, second)
        decoded = json.loads(first)
        self.assertEqual(decoded["schema_version"], 2)
        self.assertEqual(decoded["candidate_count"], 1)
        self.assertEqual(decoded["summary"]["sequence_count"], 1)
        self.assertEqual(decoded["summary"]["view_class_counts"]["front"], 1)
        self.assertEqual(decoded["summary"]["target_in_fov_counts"]["true"], 1)
        self.assertEqual(decoded["sequences"][0]["sequence_id"], "sequence-a")
        self.assertEqual(decoded["candidates"][0]["source_id"], "near-picture")


if __name__ == "__main__":
    unittest.main()
