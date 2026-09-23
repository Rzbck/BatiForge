from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import laspy
import numpy as np
import requests
from pyproj import Transformer


RNB_OGC_ITEM_URL = (
    "https://rnb-api.beta.gouv.fr/api/alpha/ogc/collections/buildings/items/{rnb_id}"
)


@dataclass(frozen=True, slots=True)
class ProjectedFootprint:
    rnb_id: str
    source_url: str
    source_crs: str
    target_crs: str
    origin_x: float
    origin_y: float
    polygons_abs_xy: tuple[tuple[tuple[float, float], ...], ...]

    @property
    def polygons_local_xy(self) -> tuple[tuple[tuple[float, float], ...], ...]:
        return tuple(
            tuple((x - self.origin_x, y - self.origin_y) for x, y in ring)
            for ring in self.polygons_abs_xy
        )

    @property
    def bounds(self) -> dict[str, float]:
        all_points = [point for ring in self.polygons_abs_xy for point in ring]
        xs = [point[0] for point in all_points]
        ys = [point[1] for point in all_points]
        return {
            "min_x": min(xs),
            "max_x": max(xs),
            "min_y": min(ys),
            "max_y": max(ys),
            "width_m": max(xs) - min(xs),
            "height_m": max(ys) - min(ys),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "rnb_id": self.rnb_id,
            "source_url": self.source_url,
            "source_crs": self.source_crs,
            "target_crs": self.target_crs,
            "origin_x": self.origin_x,
            "origin_y": self.origin_y,
            "polygons_abs_xy": [
                [[round(x, 4), round(y, 4)] for x, y in ring]
                for ring in self.polygons_abs_xy
            ],
            "polygons_local_xy": [
                [[round(x, 4), round(y, 4)] for x, y in ring]
                for ring in self.polygons_local_xy
            ],
            "bounds": {key: round(value, 4) for key, value in self.bounds.items()},
            "planimetric_area_m2": round(
                sum(abs(_signed_area(ring)) for ring in self.polygons_abs_xy), 3
            ),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def _signed_area(ring: tuple[tuple[float, float], ...]) -> float:
    if len(ring) < 3:
        return 0.0
    area = 0.0
    for index, current in enumerate(ring):
        nxt = ring[(index + 1) % len(ring)]
        area += current[0] * nxt[1] - nxt[0] * current[1]
    return 0.5 * area


def _outer_rings_from_geometry(geometry: dict[str, Any]) -> list[list[list[float]]]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")

    if geometry_type == "Polygon" and isinstance(coordinates, list) and coordinates:
        if len(coordinates) != 1:
            raise ValueError("RNB footprint contains interior rings; refusing to discard holes")
        return [coordinates[0]]

    if geometry_type == "MultiPolygon" and isinstance(coordinates, list):
        rings: list[list[list[float]]] = []
        for polygon in coordinates:
            if not isinstance(polygon, list) or not polygon:
                continue
            if len(polygon) != 1:
                raise ValueError("RNB footprint contains interior rings; refusing to discard holes")
            rings.append(polygon[0])
        return rings

    raise ValueError(f"unsupported RNB geometry type: {geometry_type!r}")


def project_geojson_footprint(
    feature: dict[str, Any],
    *,
    rnb_id: str,
    origin_x: float,
    origin_y: float,
    target_crs: str = "EPSG:2154",
    source_url: str | None = None,
) -> ProjectedFootprint:
    if feature.get("type") != "Feature":
        raise ValueError("RNB response must be a GeoJSON Feature")

    geometry = feature.get("geometry")
    if not isinstance(geometry, dict):
        raise ValueError("RNB feature has no geometry")

    transformer = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)
    projected: list[tuple[tuple[float, float], ...]] = []

    for raw_ring in _outer_rings_from_geometry(geometry):
        ring: list[tuple[float, float]] = []
        for coordinate in raw_ring:
            if not isinstance(coordinate, list) or len(coordinate) < 2:
                raise ValueError("invalid coordinate in RNB footprint")
            lon = float(coordinate[0])
            lat = float(coordinate[1])
            x, y = transformer.transform(lon, lat)
            ring.append((float(x), float(y)))

        if len(ring) >= 2 and ring[0] == ring[-1]:
            ring.pop()
        if len(ring) < 3:
            raise ValueError("RNB footprint ring has fewer than three vertices")
        projected.append(tuple(ring))

    if not projected:
        raise ValueError("RNB footprint contains no polygon")

    return ProjectedFootprint(
        rnb_id=rnb_id,
        source_url=source_url or RNB_OGC_ITEM_URL.format(rnb_id=rnb_id),
        source_crs="EPSG:4326",
        target_crs=target_crs,
        origin_x=float(origin_x),
        origin_y=float(origin_y),
        polygons_abs_xy=tuple(projected),
    )


def fetch_rnb_footprint(
    rnb_id: str,
    *,
    origin_x: float,
    origin_y: float,
    target_crs: str = "EPSG:2154",
    timeout_s: float = 30.0,
) -> ProjectedFootprint:
    """Fetch one authoritative RNB building as a GeoJSON Feature.

    Use the documented OGC API - Features item endpoint directly. The legacy
    ``/buildings/{id}/?format=geojson`` route still advertises an
    ``application/json`` response and can reject ``Accept: application/geo+json``
    with HTTP 406. The OGC item endpoint explicitly serves GeoJSON and avoids
    that content-negotiation ambiguity.
    """

    url = RNB_OGC_ITEM_URL.format(rnb_id=rnb_id)
    response = requests.get(
        url,
        headers={"Accept": "application/geo+json", "User-Agent": "BatiForge/0.1"},
        timeout=timeout_s,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("RNB response is not a JSON object")

    return project_geojson_footprint(
        payload,
        rnb_id=rnb_id,
        origin_x=origin_x,
        origin_y=origin_y,
        target_crs=target_crs,
        source_url=response.url,
    )


def _points_in_ring(xy: np.ndarray, ring: tuple[tuple[float, float], ...]) -> np.ndarray:
    """Vectorized odd-even point-in-polygon test for one simple ring."""

    points = np.asarray(xy, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 2:
        raise ValueError("xy must be an Nx2 array")
    polygon = np.asarray(ring, dtype=np.float64)
    if len(polygon) < 3:
        return np.zeros(len(points), dtype=bool)

    x = points[:, 0]
    y = points[:, 1]
    inside = np.zeros(len(points), dtype=bool)
    xj, yj = polygon[-1]
    for xi, yi in polygon:
        crosses = (yi > y) != (yj > y)
        denominator = yj - yi
        safe = denominator if abs(denominator) > 1e-15 else 1e-15
        x_cross = (xj - xi) * (y - yi) / safe + xi
        inside ^= crosses & (x < x_cross)
        xj, yj = xi, yi
    return inside


def lidar_alignment_metrics(
    lidar_path: Path,
    footprint: ProjectedFootprint,
    *,
    classification: int | None = 6,
) -> dict[str, Any]:
    las = laspy.read(lidar_path)
    xy = np.column_stack((np.asarray(las.x), np.asarray(las.y))).astype(np.float64)

    if classification is not None and "classification" in las.point_format.dimension_names:
        classes = np.asarray(las.classification)
        xy = xy[classes == classification]

    if len(xy) == 0:
        raise ValueError("no LiDAR points remain for footprint alignment")

    inside = np.zeros(len(xy), dtype=bool)
    for ring in footprint.polygons_abs_xy:
        inside |= _points_in_ring(xy, ring)

    inside_count = int(inside.sum())
    total = int(len(xy))
    outside_count = total - inside_count
    return {
        "lidar_point_count": total,
        "inside_footprint_count": inside_count,
        "outside_footprint_count": outside_count,
        "inside_ratio": round(inside_count / total, 6),
        "classification": classification,
        "lidar_bounds": {
            "min_x": round(float(np.min(xy[:, 0])), 4),
            "max_x": round(float(np.max(xy[:, 0])), 4),
            "min_y": round(float(np.min(xy[:, 1])), 4),
            "max_y": round(float(np.max(xy[:, 1])), 4),
        },
    }


def write_footprint_obj(path: Path, footprint: ProjectedFootprint) -> None:
    lines = [
        "# BatiForge authoritative RNB footprint diagnostic OBJ",
        f"# rnb_id={footprint.rnb_id}",
        f"# source_url={footprint.source_url}",
        f"# source_crs={footprint.source_crs}",
        f"# target_crs={footprint.target_crs}",
        f"# origin_x={footprint.origin_x:.6f}",
        f"# origin_y={footprint.origin_y:.6f}",
        "# axes: X east, Y north, Z up; Z=0 is the roof-analysis ground reference",
    ]

    vertex_offset = 1
    for polygon_index, ring in enumerate(footprint.polygons_local_xy, start=1):
        lines.append(f"o rnb_footprint_{polygon_index:02d}")
        for x, y in ring:
            lines.append(f"v {x:.6f} {y:.6f} 0.000000")
        count = len(ring)
        if count >= 2:
            indices = [str(vertex_offset + index) for index in range(count)]
            indices.append(str(vertex_offset))
            lines.append("l " + " ".join(indices))
        vertex_offset += count

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch/project the authoritative RNB footprint and optionally audit LiDAR alignment."
    )
    parser.add_argument("--rnb-id", required=True)
    parser.add_argument("--origin-x", type=float, required=True)
    parser.add_argument("--origin-y", type=float, required=True)
    parser.add_argument("--target-crs", default="EPSG:2154")
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-obj", type=Path)
    parser.add_argument("--lidar", type=Path)
    parser.add_argument("--classification", type=int, default=6)
    parser.add_argument("--all-classes", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        footprint = fetch_rnb_footprint(
            args.rnb_id,
            origin_x=args.origin_x,
            origin_y=args.origin_y,
            target_crs=args.target_crs,
        )
        payload = footprint.to_dict()
        if args.lidar:
            payload["lidar_alignment"] = lidar_alignment_metrics(
                args.lidar,
                footprint,
                classification=None if args.all_classes else args.classification,
            )
    except (OSError, requests.RequestException, ValueError, laspy.errors.LaspyException) as exc:
        print(f"BatiForge RNB footprint acquisition failed: {exc}")
        return 2

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if args.output_obj:
        write_footprint_obj(args.output_obj, footprint)

    print(
        f"RNB footprint: rnb_id={footprint.rnb_id} "
        f"polygons={len(footprint.polygons_abs_xy)} "
        f"area_m2={payload['planimetric_area_m2']:.3f} "
        f"bbox={payload['bounds']['width_m']:.3f}x{payload['bounds']['height_m']:.3f}m"
    )
    if "lidar_alignment" in payload:
        alignment = payload["lidar_alignment"]
        print(
            "LiDAR alignment: "
            f"inside={alignment['inside_footprint_count']}/{alignment['lidar_point_count']} "
            f"ratio={alignment['inside_ratio']:.4f}"
        )
    print(f"json: {args.output_json}")
    if args.output_obj:
        print(f"diagnostic obj: {args.output_obj}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
