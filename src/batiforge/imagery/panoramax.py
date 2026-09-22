from __future__ import annotations

from math import cos, radians
from typing import Any

import requests

from .models import (
    ImageCandidate,
    SurveyResult,
    classify_view_geometry,
    haversine_distance_m,
    initial_bearing_deg,
)


class PanoramaxError(RuntimeError):
    """Raised when the Panoramax survey cannot be completed safely."""


class PanoramaxProvider:
    """Metadata-only Panoramax/STAC imagery discovery provider."""

    name = "panoramax"

    def __init__(
        self,
        endpoint: str = "https://panoramax.openstreetmap.fr/api",
        *,
        timeout_s: float = 30.0,
        session: requests.Session | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.timeout_s = timeout_s
        self.session = session or requests.Session()
        self.session.headers.setdefault(
            "User-Agent",
            "BatiForge/0.1 (+https://github.com/Rzbck/BatiForge)",
        )

    def survey(
        self,
        *,
        latitude: float,
        longitude: float,
        radius_m: float,
        limit: int = 2_000,
        page_limit: int = 500,
    ) -> SurveyResult:
        if radius_m <= 0:
            raise ValueError("radius_m must be > 0")
        if limit <= 0:
            raise ValueError("limit must be > 0")

        license_id, license_url = self._license_metadata()
        bbox = _bbox_for_radius(latitude, longitude, radius_m)

        features: list[dict[str, Any]] = []
        seen: set[str] = set()
        url = f"{self.endpoint}/search"
        params: dict[str, Any] | None = {
            "bbox": ",".join(f"{value:.8f}" for value in bbox),
            "limit": min(page_limit, limit),
        }
        method = "GET"
        body: dict[str, Any] | None = None

        while url and len(features) < limit:
            payload = self._request_json(method, url, params=params, json_body=body)
            page_features = payload.get("features")
            if not isinstance(page_features, list):
                raise PanoramaxError("Panoramax /search returned no FeatureCollection features")

            for feature in page_features:
                if not isinstance(feature, dict):
                    continue
                source_id = str(feature.get("id") or "")
                if not source_id or source_id in seen:
                    continue
                seen.add(source_id)
                features.append(feature)
                if len(features) >= limit:
                    break

            next_link = _link_by_rel(payload.get("links"), "next")
            if not next_link or len(features) >= limit:
                break

            url = str(next_link.get("href") or "")
            if not url:
                break
            method = str(next_link.get("method") or "GET").upper()
            body = next_link.get("body") if isinstance(next_link.get("body"), dict) else None
            params = None

        candidates: list[ImageCandidate] = []
        for feature in features:
            candidate = self._candidate_from_feature(
                feature,
                target_latitude=latitude,
                target_longitude=longitude,
                license_id=license_id,
                license_url=license_url,
            )
            if candidate is not None and candidate.distance_m <= radius_m:
                candidates.append(candidate)

        candidates.sort(key=lambda item: (item.distance_m, item.source_id))

        return SurveyResult(
            provider=self.name,
            endpoint=self.endpoint,
            target_latitude=latitude,
            target_longitude=longitude,
            radius_m=radius_m,
            candidates=tuple(candidates),
            license_id=license_id,
            license_url=license_url,
        )

    def _license_metadata(self) -> tuple[str | None, str | None]:
        license_id: str | None = None
        license_url: str | None = None

        try:
            config = self._request_json("GET", f"{self.endpoint}/configuration")
            license_id = _first_string(
                config,
                "pictures_license",
                "picture_license",
                "license",
                "license_id",
            )
            license_url = _first_string(
                config,
                "pictures_license_url",
                "picture_license_url",
                "license_url",
            )
        except PanoramaxError:
            config = {}

        try:
            landing = self._request_json("GET", self.endpoint)
            license_link = _link_by_rel(landing.get("links"), "license")
            if license_link:
                license_url = license_url or _optional_string(license_link.get("href"))
                license_id = license_id or _optional_string(
                    license_link.get("title") or license_link.get("id")
                )
        except PanoramaxError:
            if not config:
                raise

        return license_id, license_url

    def _candidate_from_feature(
        self,
        feature: dict[str, Any],
        *,
        target_latitude: float,
        target_longitude: float,
        license_id: str | None,
        license_url: str | None,
    ) -> ImageCandidate | None:
        source_id = _optional_string(feature.get("id"))
        geometry = feature.get("geometry")
        if not source_id or not isinstance(geometry, dict):
            return None

        coords = geometry.get("coordinates")
        if not isinstance(coords, list) or len(coords) < 2:
            return None

        try:
            longitude = float(coords[0])
            latitude = float(coords[1])
        except (TypeError, ValueError):
            return None

        properties = feature.get("properties")
        if not isinstance(properties, dict):
            properties = {}

        width, height = _image_dimensions(feature, properties)
        heading = _first_number(
            properties,
            "view:azimuth",
            "pers:heading",
            "panoramax:heading",
            "heading",
        )
        if heading is not None:
            heading %= 360.0

        fov = _field_of_view(properties)
        panoramic = _panoramic_flag(properties, fov)
        target_bearing = initial_bearing_deg(
            latitude,
            longitude,
            target_latitude,
            target_longitude,
        )
        view_class, heading_error, target_in_fov = classify_view_geometry(
            heading_deg=heading,
            target_bearing_deg=target_bearing,
            field_of_view_deg=fov,
            panoramic=panoramic,
        )

        sequence_id = _optional_string(
            feature.get("collection") or properties.get("collection")
        )
        captured_at = _optional_string(
            properties.get("datetime")
            or properties.get("datetimetz")
            or properties.get("created")
        )
        self_link = _link_by_rel(feature.get("links"), "self")
        source_url = (
            _optional_string(self_link.get("href"))
            if self_link
            else f"{self.endpoint}/pictures/{source_id}"
        )

        return ImageCandidate(
            provider=self.name,
            source_id=source_id,
            latitude=latitude,
            longitude=longitude,
            distance_m=round(
                haversine_distance_m(
                    target_latitude,
                    target_longitude,
                    latitude,
                    longitude,
                ),
                3,
            ),
            sequence_id=sequence_id,
            captured_at=captured_at,
            width=width,
            height=height,
            heading_deg=heading,
            field_of_view_deg=fov,
            panoramic=panoramic,
            source_url=source_url,
            license_id=license_id,
            license_url=license_url,
            target_bearing_deg=round(target_bearing, 3),
            heading_error_deg=round(heading_error, 3) if heading_error is not None else None,
            target_in_fov=target_in_fov,
            view_class=view_class,
        )

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = self.session.request(
                method,
                url,
                params=params,
                json=json_body,
                timeout=self.timeout_s,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise PanoramaxError(f"Panoramax request failed: {exc}") from exc
        except ValueError as exc:
            raise PanoramaxError("Panoramax returned invalid JSON") from exc

        if not isinstance(payload, dict):
            raise PanoramaxError("Panoramax returned a non-object JSON payload")
        return payload


def _bbox_for_radius(
    latitude: float,
    longitude: float,
    radius_m: float,
) -> tuple[float, float, float, float]:
    lat_delta = radius_m / 111_320.0
    longitude_scale = max(cos(radians(latitude)), 1e-6)
    lon_delta = radius_m / (111_320.0 * longitude_scale)
    return (
        longitude - lon_delta,
        latitude - lat_delta,
        longitude + lon_delta,
        latitude + lat_delta,
    )


def _link_by_rel(value: Any, rel: str) -> dict[str, Any] | None:
    if not isinstance(value, list):
        return None
    for link in value:
        if isinstance(link, dict) and link.get("rel") == rel:
            return link
    return None


def _first_string(mapping: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _optional_string(mapping.get(key))
        if value:
            return value
    return None


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _first_number(mapping: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _field_of_view(properties: dict[str, Any]) -> float | None:
    direct = _first_number(
        properties,
        "view:fov",
        "pers:horizontal_fov",
        "panoramax:horizontal_fov",
        "field_of_view",
    )
    if direct is not None:
        return direct

    interior = properties.get("pers:interior_orientation")
    if isinstance(interior, dict):
        return _first_number(interior, "field_of_view", "horizontal_fov")

    return None


def _image_dimensions(
    feature: dict[str, Any],
    properties: dict[str, Any],
) -> tuple[int | None, int | None]:
    shape = properties.get("proj:shape")
    if isinstance(shape, list) and len(shape) >= 2:
        try:
            return int(shape[1]), int(shape[0])
        except (TypeError, ValueError):
            pass

    geovisio_image = properties.get("geovisio:image")
    if isinstance(geovisio_image, dict):
        width = geovisio_image.get("width")
        height = geovisio_image.get("height")
        if isinstance(width, int) and isinstance(height, int):
            return width, height

    assets = feature.get("assets")
    if isinstance(assets, dict):
        for asset in assets.values():
            if not isinstance(asset, dict):
                continue
            width = asset.get("width")
            height = asset.get("height")
            if isinstance(width, int) and isinstance(height, int):
                return width, height

    return None, None


def _panoramic_flag(
    properties: dict[str, Any],
    field_of_view_deg: float | None,
) -> bool | None:
    for key in ("panoramax:is_panoramic", "is_panoramic", "panoramic"):
        value = properties.get(key)
        if isinstance(value, bool):
            return value

    view_type = properties.get("view:type")
    if isinstance(view_type, str):
        normalized = view_type.lower()
        if normalized in {"equirectangular", "spherical", "panorama", "360"}:
            return True
        if normalized in {"perspective", "rectilinear", "flat"}:
            return False

    if field_of_view_deg is not None and field_of_view_deg >= 359.0:
        return True

    return None
