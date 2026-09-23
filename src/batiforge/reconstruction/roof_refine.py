from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .roof_regions import _plane_lookup


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def _polygon_xy(piece: dict[str, Any]) -> list[tuple[float, float]]:
    raw = piece.get("polygon_local_xy")
    if not isinstance(raw, list) or len(raw) < 3:
        raise ValueError("unresolved piece has no polygon_local_xy")
    return [(float(point[0]), float(point[1])) for point in raw]


def _vertices_for_plane(
    polygon: list[tuple[float, float]],
    plane: tuple[float, float, float],
    ground_z: float,
) -> list[list[float]]:
    a, b, c = plane
    return [
        [round(x, 5), round(y, 5), round(a * x + b * y + c - ground_z, 5)]
        for x, y in polygon
    ]


def refine_roof_cleanup(
    cleaned: dict[str, Any],
    *,
    roof: dict[str, Any],
    max_medium_area_m2: float = 6.5,
    min_medium_purity: float = 0.45,
    min_neighbor_boundary_m: float = 0.50,
    min_strong_boundary_m: float = 1.00,
    min_footprint_boundary_m: float = 1.00,
) -> dict[str, Any]:
    """Promote only medium unresolved pieces with strict single-plane evidence.

    This is deliberately non-recursive. Neighbor evidence must already be present
    in the HOST_VALIDATED cleanup JSON and therefore comes from direct-LiDAR roof
    regions, not from earlier inferred pieces. Large, low-purity, unsupported or
    multi-plane gaps remain unresolved.
    """

    if max_medium_area_m2 <= 0.0:
        raise ValueError("max_medium_area_m2 must be > 0")
    if not 0.0 <= min_medium_purity <= 1.0:
        raise ValueError("min_medium_purity must be in [0,1]")
    if min_neighbor_boundary_m <= 0.0:
        raise ValueError("min_neighbor_boundary_m must be > 0")
    if min_strong_boundary_m <= 0.0:
        raise ValueError("min_strong_boundary_m must be > 0")
    if min_footprint_boundary_m < 0.0:
        raise ValueError("min_footprint_boundary_m must be >= 0")

    georef = cleaned.get("georeference")
    if not isinstance(georef, dict):
        raise ValueError("cleanup JSON has no georeference")
    ground_z = float(georef["ground_z"])
    planes = _plane_lookup(roof)

    base_regions = [dict(region) for region in cleaned.get("regions", [])]
    promoted: list[dict[str, Any]] = []
    remaining: list[dict[str, Any]] = []

    for piece in cleaned.get("unresolved", []):
        item = dict(piece)
        area = float(item.get("area_m2", 0.0))
        reason = str(item.get("reason", "unknown"))
        best_plane_raw = item.get("best_plane_index")
        purity = float(item.get("purity", 0.0) or 0.0)
        footprint_shared = float(item.get("footprint_boundary_shared_m", 0.0) or 0.0)
        neighbors_raw = item.get("neighbor_boundary_m_by_plane", {})
        if not isinstance(neighbors_raw, dict):
            neighbors_raw = {}
        neighbors = {int(key): float(value) for key, value in neighbors_raw.items()}
        eligible = {
            plane: length
            for plane, length in neighbors.items()
            if length >= min_neighbor_boundary_m
        }

        accepted_plane: int | None = None
        if (
            reason == "insufficient_support_or_purity"
            and 0.0 < area <= max_medium_area_m2
            and best_plane_raw is not None
            and purity >= min_medium_purity
            and len(eligible) == 1
        ):
            best_plane = int(best_plane_raw)
            sole_plane, shared_length = next(iter(eligible.items()))
            if best_plane == sole_plane and (
                shared_length >= min_strong_boundary_m
                or footprint_shared >= min_footprint_boundary_m
            ):
                accepted_plane = best_plane

        if accepted_plane is None:
            remaining.append(item)
            continue
        if accepted_plane not in planes:
            raise ValueError(f"unknown promoted plane {accepted_plane}")

        polygon = _polygon_xy(item)
        promoted.append(
            {
                "region_index": len(base_regions) + len(promoted) + 1,
                "source_piece_index": int(item["piece_index"]),
                "plane_index": accepted_plane,
                "area_xy_m2": round(area, 4),
                "point_count": int(item.get("point_count", 0)),
                "support_count": int(item.get("best_plane_support_count", 0)),
                "purity": round(purity, 6),
                "provenance": "inferred_medium_gap_strict",
                "shared_boundary_to_plane_m": round(eligible[accepted_plane], 4),
                "footprint_boundary_shared_m": round(footprint_shared, 4),
                "vertices_local_xyz": _vertices_for_plane(
                    polygon, planes[accepted_plane], ground_z
                ),
            }
        )

    all_regions = base_regions + promoted
    footprint_area = float(cleaned["footprint_area_m2"])
    resolved_area = sum(float(region["area_xy_m2"]) for region in all_regions)
    remaining_area = sum(float(piece.get("area_m2", 0.0)) for piece in remaining)

    provenance_counts: Counter[str] = Counter()
    area_by_plane: Counter[int] = Counter()
    for region in all_regions:
        provenance_counts[str(region.get("provenance", "unknown"))] += 1
        area_by_plane[int(region["plane_index"])] += float(region["area_xy_m2"])

    return {
        "schema_version": 1,
        "method": "strict non-recursive medium-gap roof refinement",
        "georeference": georef,
        "parameters": {
            "max_medium_area_m2": max_medium_area_m2,
            "min_medium_purity": min_medium_purity,
            "min_neighbor_boundary_m": min_neighbor_boundary_m,
            "min_strong_boundary_m": min_strong_boundary_m,
            "min_footprint_boundary_m": min_footprint_boundary_m,
        },
        "footprint_area_m2": footprint_area,
        "input_resolved_area_m2": float(cleaned["resolved_area_m2"]),
        "input_resolved_area_ratio": float(cleaned["resolved_area_ratio"]),
        "promoted_region_count": len(promoted),
        "promoted_area_m2": round(sum(float(r["area_xy_m2"]) for r in promoted), 4),
        "resolved_region_count": len(all_regions),
        "resolved_area_m2": round(resolved_area, 4),
        "resolved_area_ratio": round(resolved_area / footprint_area if footprint_area else 0.0, 6),
        "remaining_unresolved_count": len(remaining),
        "remaining_unresolved_area_m2": round(remaining_area, 4),
        "high_structure_point_count": int(cleaned.get("high_structure_point_count", 0)),
        "provenance_counts": dict(sorted(provenance_counts.items())),
        "area_by_plane_m2": {
            str(index): round(float(area_by_plane.get(index, 0.0)), 4)
            for index in sorted(planes)
        },
        "regions": all_regions,
        "promoted": promoted,
        "unresolved": remaining,
    }


def _provenance_code(region: dict[str, Any]) -> int:
    provenance = str(region.get("provenance", ""))
    if provenance == "direct_lidar":
        return 0
    if provenance == "inferred_medium_gap_strict":
        return 2
    return 1


def _mesh_arrays(
    refined: dict[str, Any],
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]], list[int], list[int]]:
    vertices: list[tuple[float, float, float]] = []
    vertex_map: dict[tuple[float, float, float], int] = {}
    faces: list[tuple[int, int, int]] = []
    face_planes: list[int] = []
    face_provenance: list[int] = []

    def index_of(raw: list[float]) -> int:
        key = (round(float(raw[0]), 5), round(float(raw[1]), 5), round(float(raw[2]), 5))
        if key not in vertex_map:
            vertex_map[key] = len(vertices)
            vertices.append(key)
        return vertex_map[key]

    for region in refined.get("regions", []):
        raw = region.get("vertices_local_xyz", [])
        if len(raw) < 3:
            continue
        ids = [index_of(vertex) for vertex in raw]
        code = _provenance_code(region)
        for i in range(1, len(ids) - 1):
            faces.append((ids[0], ids[i], ids[i + 1]))
            face_planes.append(int(region["plane_index"]))
            face_provenance.append(code)
    return vertices, faces, face_planes, face_provenance


def write_refined_ply(path: Path, refined: dict[str, Any]) -> None:
    vertices, faces, planes, provenance = _mesh_arrays(refined)
    lines = [
        "ply",
        "format ascii 1.0",
        "comment BatiForge refined roof; X east, Y north, Z up",
        "comment provenance_code 0=direct_lidar 1=small_conservative_inference 2=medium_strict_inference",
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


def write_refined_obj(path: Path, refined: dict[str, Any]) -> None:
    georef = refined["georeference"]
    lines = [
        "# BatiForge refined roof surface",
        "# axes: X east / Y north / Z up",
        "# provenance remains authoritative in the companion JSON/PLY",
        f"# horizontal_crs={georef['horizontal_crs']}",
        f"# vertical_datum={georef['vertical_datum']}",
        f"# origin_x={float(georef['origin_x']):.6f}",
        f"# origin_y={float(georef['origin_y']):.6f}",
        f"# ground_z={float(georef['ground_z']):.6f}",
    ]
    offset = 1
    for region in refined.get("regions", []):
        raw = region.get("vertices_local_xyz", [])
        if len(raw) < 3:
            continue
        provenance = str(region.get("provenance", "unknown"))
        lines.append(
            f"o roof_r{int(region['region_index']):03d}_p{int(region['plane_index']):02d}_{provenance}"
        )
        for vertex in raw:
            lines.append(
                f"v {float(vertex[0]):.6f} {float(vertex[1]):.6f} {float(vertex[2]):.6f}"
            )
        for i in range(2, len(raw)):
            lines.append(f"f {offset} {offset + i - 1} {offset + i}")
        offset += len(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply strict medium-gap refinement to a HOST_VALIDATED BatiForge roof cleanup."
    )
    parser.add_argument("--clean-json", type=Path, required=True)
    parser.add_argument("--roof-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-ply", type=Path, required=True)
    parser.add_argument("--output-obj", type=Path, required=True)
    parser.add_argument("--max-medium-area-m2", type=float, default=6.5)
    parser.add_argument("--min-medium-purity", type=float, default=0.45)
    parser.add_argument("--min-neighbor-boundary-m", type=float, default=0.50)
    parser.add_argument("--min-strong-boundary-m", type=float, default=1.00)
    parser.add_argument("--min-footprint-boundary-m", type=float, default=1.00)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        cleaned = _load_json(args.clean_json)
        roof = _load_json(args.roof_json)
        refined = refine_roof_cleanup(
            cleaned,
            roof=roof,
            max_medium_area_m2=args.max_medium_area_m2,
            min_medium_purity=args.min_medium_purity,
            min_neighbor_boundary_m=args.min_neighbor_boundary_m,
            min_strong_boundary_m=args.min_strong_boundary_m,
            min_footprint_boundary_m=args.min_footprint_boundary_m,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"BatiForge roof refinement failed: {exc}")
        return 2

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(refined, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    write_refined_ply(args.output_ply, refined)
    write_refined_obj(args.output_obj, refined)
    print(
        "roof refinement: "
        f"promoted={refined['promoted_region_count']} "
        f"+{refined['promoted_area_m2']:.2f}m2 "
        f"resolved={refined['resolved_area_m2']:.2f}/{refined['footprint_area_m2']:.2f}m2 "
        f"ratio={refined['resolved_area_ratio']:.3f} "
        f"remaining={refined['remaining_unresolved_count']}"
    )
    print(f"json: {args.output_json}")
    print(f"ply: {args.output_ply}")
    print(f"obj: {args.output_obj}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
