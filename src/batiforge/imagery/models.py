from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from math import asin, cos, radians, sin, sqrt
from typing import Any


@dataclass(frozen=True, slots=True)
class ImageCandidate:
    provider: str
    source_id: str
    latitude: float
    longitude: float
    distance_m: float
    sequence_id: str | None = None
    captured_at: str | None = None
    width: int | None = None
    height: int | None = None
    heading_deg: float | None = None
    field_of_view_deg: float | None = None
    panoramic: bool | None = None
    source_url: str | None = None
    license_id: str | None = None
    license_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SurveyResult:
    provider: str
    endpoint: str
    target_latitude: float
    target_longitude: float
    radius_m: float
    candidates: tuple[ImageCandidate, ...]
    license_id: str | None = None
    license_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "target": {
                "latitude": self.target_latitude,
                "longitude": self.target_longitude,
                "radius_m": self.radius_m,
            },
            "license": {
                "id": self.license_id,
                "url": self.license_url,
            },
            "candidate_count": len(self.candidates),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def haversine_distance_m(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """Return great-circle distance in metres between two WGS84 coordinates."""

    earth_radius_m = 6_371_008.8
    phi1 = radians(lat1)
    phi2 = radians(lat2)
    d_phi = radians(lat2 - lat1)
    d_lambda = radians(lon2 - lon1)

    a = (
        sin(d_phi / 2.0) ** 2
        + cos(phi1) * cos(phi2) * sin(d_lambda / 2.0) ** 2
    )
    return 2.0 * earth_radius_m * asin(sqrt(a))
