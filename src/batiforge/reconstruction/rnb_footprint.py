from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from pyproj import Transformer


RNB_BUILDING_URL = "https://rnb-api.beta.gouv.fr/api/alpha/buildings/{rnb_id}/"


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
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
        return [coordinates[0]]

    if geometry_type == "MultiPolygon" and isinstance(coordinates, list):
        rings: list[list[list[float]]] = []
        for polygon in coordinates:
            if isinstance(polygon, list) and polygon:
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
        source_url=source_url or RNB_BUILDING_URL.format(rnb_id=rnb_id),
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
    url = RNB_BUILDING_URL.format(rnb_id=rnb_id)
    response = requests.get(
        url,
        params={"format": "geojson"},
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
        description="Fetch and project the authoritative RNB footprint for BatiForge."
    )
    parser.add_argument("--rnb-id", required=True)
    parser.add_argument("--origin-x", type=float, required=True)
    parser.add_argument("--origin-y", type=float, required=True)
    parser.add_argument("--target-crs", default="EPSG:2154")
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-obj", type=Path)
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
    except (requests.RequestException, ValueError) as exc:
        print(f"BatiForge RNB footprint acquisition failed: {exc}")
        return 2

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(footprint.to_json(), encoding="utf-8", newline="\n")
    if args.output_obj:
        write_footprint_obj(args.output_obj, footprint)

    print(
        f"RNB footprint: rnb_id={footprint.rnb_id} "
        f"polygons={len(footprint.polygons_abs_xy)} "
        f"area_m2={footprint.to_dict()['planimetric_area_m2']:.3f}"
    )
    print(f"json: {args.output_json}")
    if args.output_obj:
        print(f"diagnostic obj: {args.output_obj}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
