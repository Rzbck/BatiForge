from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from math import asin, atan2, cos, degrees, radians, sin, sqrt
from typing import Any


VIEW_CLASSES = ("panoramic", "front", "lateral", "rear", "unknown")


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
    target_bearing_deg: float | None = None
    heading_error_deg: float | None = None
    target_in_fov: bool | None = None
    view_class: str = "unknown"

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
        view_counts = {name: 0 for name in VIEW_CLASSES}
        in_fov_true = 0
        in_fov_false = 0
        in_fov_unknown = 0

        for candidate in self.candidates:
            view_counts[candidate.view_class] = view_counts.get(candidate.view_class, 0) + 1
            if candidate.target_in_fov is True:
                in_fov_true += 1
            elif candidate.target_in_fov is False:
                in_fov_false += 1
            else:
                in_fov_unknown += 1

        sequence_summaries = _sequence_summaries(self.candidates)

        return {
            "schema_version": 2,
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
            "summary": {
                "sequence_count": len(sequence_summaries),
                "unsequenced_count": sum(
                    1 for candidate in self.candidates if not candidate.sequence_id
                ),
                "view_class_counts": view_counts,
                "target_in_fov_counts": {
                    "true": in_fov_true,
                    "false": in_fov_false,
                    "unknown": in_fov_unknown,
                },
            },
            "sequences": sequence_summaries,
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


def initial_bearing_deg(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """Return initial great-circle bearing in degrees, clockwise from north."""

    phi1 = radians(lat1)
    phi2 = radians(lat2)
    d_lambda = radians(lon2 - lon1)

    y = sin(d_lambda) * cos(phi2)
    x = cos(phi1) * sin(phi2) - sin(phi1) * cos(phi2) * cos(d_lambda)
    return (degrees(atan2(y, x)) + 360.0) % 360.0


def angular_difference_deg(a_deg: float, b_deg: float) -> float:
    """Return the smallest unsigned angular difference, in [0, 180]."""

    return abs((a_deg - b_deg + 180.0) % 360.0 - 180.0)


def classify_view_geometry(
    *,
    heading_deg: float | None,
    target_bearing_deg: float,
    field_of_view_deg: float | None,
    panoramic: bool | None,
) -> tuple[str, float | None, bool | None]:
    """Classify horizontal camera orientation relative to the target.

    This is geometry-only metadata. It does not prove line of sight, facade
    visibility, absence of occlusion, or sufficient image detail.
    """

    heading_error: float | None = None
    if heading_deg is not None:
        heading_error = angular_difference_deg(heading_deg % 360.0, target_bearing_deg)

    if panoramic is True:
        return "panoramic", heading_error, True

    if heading_error is None:
        return "unknown", None, None

    if heading_error <= 45.0:
        view_class = "front"
    elif heading_error < 135.0:
        view_class = "lateral"
    else:
        view_class = "rear"

    target_in_fov: bool | None = None
    if field_of_view_deg is not None and field_of_view_deg > 0.0:
        horizontal_fov = min(field_of_view_deg, 360.0)
        target_in_fov = heading_error <= horizontal_fov / 2.0

    return view_class, heading_error, target_in_fov


def _sequence_summaries(
    candidates: tuple[ImageCandidate, ...],
) -> list[dict[str, Any]]:
    groups: dict[str, list[ImageCandidate]] = {}
    for candidate in candidates:
        if candidate.sequence_id:
            groups.setdefault(candidate.sequence_id, []).append(candidate)

    summaries: list[dict[str, Any]] = []
    for sequence_id, items in groups.items():
        summaries.append(
            {
                "sequence_id": sequence_id,
                "candidate_count": len(items),
                "min_distance_m": min(item.distance_m for item in items),
                "panoramic_count": sum(item.view_class == "panoramic" for item in items),
                "front_count": sum(item.view_class == "front" for item in items),
                "lateral_count": sum(item.view_class == "lateral" for item in items),
                "rear_count": sum(item.view_class == "rear" for item in items),
                "unknown_count": sum(item.view_class == "unknown" for item in items),
                "target_in_fov_count": sum(item.target_in_fov is True for item in items),
            }
        )

    summaries.sort(key=lambda item: (item["min_distance_m"], item["sequence_id"]))
    return summaries
