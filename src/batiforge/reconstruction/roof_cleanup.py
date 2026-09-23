from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .roof_regions import _plane_lookup, _signed_area


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def _poly_xy_from_region(region: dict[str, Any]) -> list[tuple[float, float]]:
    return [(float(v[0]), float(v[1])) for v in region["vertices_local_xyz"]]


def _poly_xy_from_unresolved(piece: dict[str, Any]) -> list[tuple[float, float]]:
    return [(float(v[0]), float(v[1])) for v in piece["polygon_local_xy"]]


def _segments(poly: list[tuple[float, float]]) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    return [(poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly))]


def _shared_collinear_length(
    first: list[tuple[float, float]],
    second: list[tuple[float, float]],
    *,
    tolerance_m: float = 1e-4,
) -> float:
    total = 0.0
    for a, b in _segments(first):
        vx = b[0] - a[0]
        vy = b[1] - a[1]
        length = math.hypot(vx, vy)
        if length <= tolerance_m:
            continue
        ux, uy = vx / length, vy / length
        nx, ny = -uy, ux
        for c, d in _segments(second):
            dc = abs((c[0] - a[0]) * nx + (c[1] - a[1]) * ny)
            dd = abs((d[0] - a[0]) * nx + (d[1] - a[1]) * ny)
            if dc > tolerance_m or dd > tolerance_m:
                continue
            tc = (c[0] - a[0]) * ux + (c[1] - a[1]) * uy
            td = (d[0] - a[0]) * ux + (d[1] - a[1]) * uy
            left = max(0.0, min(tc, td))
            right = min(length, max(tc, td))
            if right > left + tolerance_m:
                total += right - left
    return total


def _footprint_ring(footprint: dict[str, Any]) -> list[tuple[float, float]]:
    raw = footprint.get("polygons_local_xy")
    if not isinstance(raw, list) or len(raw) != 1 or len(raw[0]) < 3:
        raise ValueError("cleanup currently requires one simple footprint polygon")
    return [(float(p[0]), float(p[1])) for p in raw[0]]


def _area(poly: list[tuple[float, float]]) -> float:
    return abs(_signed_area(poly))


def _vertices_for_plane(
    poly: list[tuple[float, float]],
    plane: tuple[float, float, float],
    ground_z: float,
) -> list[list[float]]:
    a, b, c = plane
    return [
        [round(x, 5), round(y, 5), round(a * x + b * y + c - ground_z, 5)]
        for x, y in poly
    ]


def clean_roof_regions(
    regions: dict[str, Any],
    *,
    roof: dict[str, Any],
    footprint: dict[str, Any],
    max_inferred_area_m2: float = 2.0,
    min_shared_boundary_m: float = 0.25,
    min_weak_purity: float = 0.35,
    footprint_touch_length_m: float = 0.10,
) -> dict[str, Any]:
    """Conservatively fill only small roof gaps with unambiguous local evidence.

    This stage never performs recursive flood filling. Each inference is based only
    on the already HOST_VALIDATED direct-LiDAR regions from the input JSON.
    Ambiguous gaps, large gaps and unsupported interior holes remain explicit.
    """

    if max_inferred_area_m2 <= 0.0:
        raise ValueError("max_inferred_area_m2 must be > 0")
    if min_shared_boundary_m <= 0.0:
        raise ValueError("min_shared_boundary_m must be > 0")
    if not 0.0 <= min_weak_purity <= 1.0:
        raise ValueError("min_weak_purity must be in [0,1]")

    georef = regions.get("georeference")
    if not isinstance(georef, dict):
        raise ValueError("region JSON has no georeference")
    ground_z = float(georef["ground_z"])
    planes = _plane_lookup(roof)
    footprint_poly = _footprint_ring(footprint)

    direct: list[dict[str, Any]] = []
    direct_polys: list[list[tuple[float, float]]] = []
    for region in regions.get("regions", []):
        item = dict(region)
        item["provenance"] = "direct_lidar"
        direct.append(item)
        direct_polys.append(_poly_xy_from_region(region))

    inferred: list[dict[str, Any]] = []
    remaining: list[dict[str, Any]] = []

    for piece in regions.get("unresolved", []):
        poly = _poly_xy_from_unresolved(piece)
        area_m2 = float(piece.get("area_m2", _area(poly)))
        neighbor_lengths: dict[int, float] = defaultdict(float)
        for region, resolved_poly in zip(direct, direct_polys, strict=True):
            shared = _shared_collinear_length(poly, resolved_poly)
            if shared > 1e-6:
                neighbor_lengths[int(region["plane_index"])] += shared

        footprint_shared = _shared_collinear_length(poly, footprint_poly)
        eligible_neighbors = {
            plane: length
            for plane, length in neighbor_lengths.items()
            if length >= min_shared_boundary_m
        }
        sole_plane = next(iter(eligible_neighbors)) if len(eligible_neighbors) == 1 else None
        reason = str(piece.get("reason", "unknown"))
        best_plane = piece.get("best_plane_index")
        purity = float(piece.get("purity", 0.0) or 0.0)
        decision: str | None = None

        if area_m2 <= max_inferred_area_m2 and sole_plane is not None:
            if (
                reason == "insufficient_support_or_purity"
                and best_plane is not None
                and int(best_plane) == sole_plane
                and purity >= min_weak_purity
            ):
                decision = "inferred_single_neighbor_weak_lidar"
            elif reason == "no_supported_plane" and footprint_shared >= footprint_touch_length_m:
                decision = "inferred_single_neighbor_eave_extension"

        if decision is None:
            unresolved_item = dict(piece)
            unresolved_item["neighbor_boundary_m_by_plane"] = {
                str(k): round(v, 4) for k, v in sorted(neighbor_lengths.items())
            }
            unresolved_item["footprint_boundary_shared_m"] = round(footprint_shared, 4)
            remaining.append(unresolved_item)
            continue

        if sole_plane not in planes:
            raise ValueError(f"unknown inferred plane {sole_plane}")
        inferred.append(
            {
                "region_index": len(direct) + len(inferred) + 1,
                "source_piece_index": int(piece["piece_index"]),
                "plane_index": int(sole_plane),
                "area_xy_m2": round(area_m2, 4),
                "point_count": int(piece.get("point_count", 0)),
                "support_count": int(piece.get("best_plane_support_count", 0)),
                "purity": round(purity, 6),
                "provenance": decision,
                "shared_boundary_to_plane_m": round(eligible_neighbors[sole_plane], 4),
                "footprint_boundary_shared_m": round(footprint_shared, 4),
                "vertices_local_xyz": _vertices_for_plane(poly, planes[sole_plane], ground_z),
            }
        )

    all_regions = direct + inferred
    direct_area = sum(float(item["area_xy_m2"]) for item in direct)
    inferred_area = sum(float(item["area_xy_m2"]) for item in inferred)
    unresolved_area = sum(float(item["area_m2"]) for item in remaining)
    footprint_area = float(regions["footprint_area_m2"])

    area_by_plane: Counter[int] = Counter()
    provenance_counts: Counter[str] = Counter()
    for item in all_regions:
        area_by_plane[int(item["plane_index"])] += float(item["area_xy_m2"])
        provenance_counts[str(item["provenance"])] += 1

    return {
        "schema_version": 1,
        "method": "conservative non-recursive gap inference over validated roof regions",
        "georeference": georef,
        "parameters": {
            "max_inferred_area_m2": max_inferred_area_m2,
            "min_shared_boundary_m": min_shared_boundary_m,
            "min_weak_purity": min_weak_purity,
            "footprint_touch_length_m": footprint_touch_length_m,
        },
        "footprint_area_m2": footprint_area,
        "direct_region_count": len(direct),
        "direct_area_m2": round(direct_area, 4),
        "inferred_region_count": len(inferred),
        "inferred_area_m2": round(inferred_area, 4),
        "resolved_region_count": len(all_regions),
        "resolved_area_m2": round(direct_area + inferred_area, 4),
        "resolved_area_ratio": round((direct_area + inferred_area) / footprint_area, 6),
        "remaining_unresolved_count": len(remaining),
        "remaining_unresolved_area_m2": round(unresolved_area, 4),
        "provenance_counts": dict(sorted(provenance_counts.items())),
        "area_by_plane_m2": {
            str(index): round(float(area_by_plane.get(index, 0.0)), 4)
            for index in sorted(planes)
        },
        "regions": all_regions,
        "inferred": inferred,
        "unresolved": remaining,
    }


def _mesh_arrays(cleaned: dict[str, Any]) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]], list[int], list[int]]:
    vertices: list[tuple[float, float, float]] = []
    vertex_map: dict[tuple[float, float, float], int] = {}
    faces: list[tuple[int, int, int]] = []
    face_planes: list[int] = []
    face_provenance: list[int] = []

    def vertex_index(raw: list[float]) -> int:
        key = (round(float(raw[0]), 5), round(float(raw[1]), 5), round(float(raw[2]), 5))
        if key not in vertex_map:
            vertex_map[key] = len(vertices)
            vertices.append(key)
        return vertex_map[key]

    for region in cleaned.get("regions", []):
        raw = region["vertices_local_xyz"]
        if len(raw) < 3:
            continue
        ids = [vertex_index(v) for v in raw]
        code = 0 if region.get("provenance") == "direct_lidar" else 1
        for index in range(1, len(ids) - 1):
            faces.append((ids[0], ids[index], ids[index + 1]))
            face_planes.append(int(region["plane_index"]))
            face_provenance.append(code)
    return vertices, faces, face_planes, face_provenance


def write_clean_ply(path: Path, cleaned: dict[str, Any]) -> None:
    vertices, faces, planes, provenance = _mesh_arrays(cleaned)
    lines = [
        "ply",
        "format ascii 1.0",
        "comment BatiForge cleaned roof; X east, Y north, Z up",
        "comment provenance_code 0=direct_lidar 1=conservative_inference",
        f"element vertex {len(vertices)}",
        "property float x",
        "property float y",
        "property float z",
        f"element face {len(faces)}",
        "property list uchar int vertex_indices",
        "property int plane_index",
        "property int provenance_code",
        "end_header",
    ]
    lines.extend(f"{x:.6f} {y:.6f} {z:.6f}" for x, y, z in vertices)
    lines.extend(
        f"3 {a} {b} {c} {plane} {prov}"
        for (a, b, c), plane, prov in zip(faces, planes, provenance, strict=True)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Conservatively clean BatiForge roof-region gaps.")
    parser.add_argument("--regions-json", type=Path, required=True)
    parser.add_argument("--roof-json", type=Path, required=True)
    parser.add_argument("--footprint-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-ply", type=Path, required=True)
    parser.add_argument("--max-inferred-area-m2", type=float, default=2.0)
    parser.add_argument("--min-shared-boundary-m", type=float, default=0.25)
    parser.add_argument("--min-weak-purity", type=float, default=0.35)
    parser.add_argument("--footprint-touch-length-m", type=float, default=0.10)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        regions = _load_json(args.regions_json)
        roof = _load_json(args.roof_json)
        footprint = _load_json(args.footprint_json)
        cleaned = clean_roof_regions(
            regions,
            roof=roof,
            footprint=footprint,
            max_inferred_area_m2=args.max_inferred_area_m2,
            min_shared_boundary_m=args.min_shared_boundary_m,
            min_weak_purity=args.min_weak_purity,
            footprint_touch_length_m=args.footprint_touch_length_m,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"BatiForge roof cleanup failed: {exc}")
        return 2

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(cleaned, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_clean_ply(args.output_ply, cleaned)
    print(
        "roof cleanup: "
        f"direct={cleaned['direct_area_m2']:.2f}m2 "
        f"inferred={cleaned['inferred_area_m2']:.2f}m2 "
        f"resolved={cleaned['resolved_area_m2']:.2f}/{cleaned['footprint_area_m2']:.2f}m2 "
        f"ratio={cleaned['resolved_area_ratio']:.3f} "
        f"remaining={cleaned['remaining_unresolved_count']}"
    )
    print(f"json: {args.output_json}")
    print(f"ply: {args.output_ply}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
