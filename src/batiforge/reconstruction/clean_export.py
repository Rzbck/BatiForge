from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from .roof_regions import _plane_lookup
from .shell_preview import _footprint_ring, _merge_intervals, _point_on, _segments, build_shell_preview


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def _project_t(a: tuple[float, float], b: tuple[float, float], p: tuple[float, float]) -> float:
    vx, vy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(vx, vy)
    if length <= 1e-12:
        return 0.0
    return ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / length


def _region_centroid_xy(region: dict[str, Any]) -> tuple[float, float]:
    raw = region.get("vertices_local_xyz", [])
    if not raw:
        return (0.0, 0.0)
    return (
        sum(float(v[0]) for v in raw) / len(raw),
        sum(float(v[1]) for v in raw) / len(raw),
    )


def _nearest_roof_z(
    x: float,
    y: float,
    *,
    refined: dict[str, Any],
    roof: dict[str, Any],
) -> tuple[float, int]:
    planes = _plane_lookup(roof)
    ground_z = float(refined["georeference"]["ground_z"])
    best: tuple[float, int] | None = None
    for region in refined.get("regions", []):
        plane_index = int(region["plane_index"])
        if plane_index not in planes:
            continue
        cx, cy = _region_centroid_xy(region)
        d2 = (cx - x) ** 2 + (cy - y) ** 2
        if best is None or d2 < best[0]:
            best = (d2, plane_index)
    if best is None:
        raise ValueError("no resolved roof region available for perimeter closure")
    plane_index = best[1]
    a, b, c = planes[plane_index]
    z = a * x + b * y + c - ground_z
    return float(z), plane_index


def _complement_intervals(length: float, covered: list[tuple[float, float]], eps: float = 1e-4) -> list[tuple[float, float]]:
    gaps: list[tuple[float, float]] = []
    cursor = 0.0
    for left, right in _merge_intervals(covered, tolerance_m=eps):
        if left > cursor + eps:
            gaps.append((cursor, left))
        cursor = max(cursor, right)
    if cursor < length - eps:
        gaps.append((cursor, length))
    return gaps


def _interpolated_top_z(
    t: float,
    samples: list[tuple[float, float]],
    *,
    xy: tuple[float, float],
    refined: dict[str, Any],
    roof: dict[str, Any],
) -> tuple[float, int | None, str]:
    if samples:
        samples = sorted(samples)
        left = [sample for sample in samples if sample[0] <= t]
        right = [sample for sample in samples if sample[0] >= t]
        if left and right:
            a = left[-1]
            b = right[0]
            if abs(b[0] - a[0]) <= 1e-9:
                return float(a[1]), None, "interpolated_supported_edge"
            f = (t - a[0]) / (b[0] - a[0])
            return float(a[1] + f * (b[1] - a[1])), None, "interpolated_supported_edge"
        nearest = min(samples, key=lambda sample: abs(sample[0] - t))
        return float(nearest[1]), None, "nearest_supported_edge"
    z, plane_index = _nearest_roof_z(xy[0], xy[1], refined=refined, roof=roof)
    return z, plane_index, "nearest_resolved_roof_plane"


def close_perimeter_walls(
    shell: dict[str, Any],
    *,
    refined: dict[str, Any],
    footprint: dict[str, Any],
    roof: dict[str, Any],
    min_gap_m: float = 0.02,
) -> tuple[list[dict[str, Any]], float]:
    ring = _footprint_ring(footprint)
    existing = [dict(wall) for wall in shell.get("perimeter_walls", [])]
    inferred: list[dict[str, Any]] = []
    inferred_length = 0.0

    for edge_index, (a, b) in enumerate(_segments(ring), start=1):
        edge_length = math.hypot(b[0] - a[0], b[1] - a[1])
        if edge_length <= 1e-9:
            continue
        intervals: list[tuple[float, float]] = []
        samples: list[tuple[float, float]] = []
        for wall in existing:
            if int(wall.get("edge_index", -1)) != edge_index:
                continue
            raw = wall.get("vertices_local_xyz", [])
            if len(raw) != 4:
                continue
            p0 = (float(raw[0][0]), float(raw[0][1]))
            p1 = (float(raw[1][0]), float(raw[1][1]))
            t0 = max(0.0, min(edge_length, _project_t(a, b, p0)))
            t1 = max(0.0, min(edge_length, _project_t(a, b, p1)))
            left, right = sorted((t0, t1))
            intervals.append((left, right))
            # wall order: bottom0, bottom1, top1, top0
            samples.append((t0, float(raw[3][2])))
            samples.append((t1, float(raw[2][2])))

        for left, right in _complement_intervals(edge_length, intervals):
            if right - left < min_gap_m:
                continue
            p0 = _point_on(a, b, left)
            p1 = _point_on(a, b, right)
            z0, plane0, source0 = _interpolated_top_z(
                left, samples, xy=p0, refined=refined, roof=roof
            )
            z1, plane1, source1 = _interpolated_top_z(
                right, samples, xy=p1, refined=refined, roof=roof
            )
            inferred.append(
                {
                    "edge_index": edge_index,
                    "plane_index": plane0 if plane0 == plane1 else None,
                    "length_m": round(right - left, 4),
                    "provenance": "provisional_perimeter_closure",
                    "top_source_start": source0,
                    "top_source_end": source1,
                    "vertices_local_xyz": [
                        [round(p0[0], 5), round(p0[1], 5), 0.0],
                        [round(p1[0], 5), round(p1[1], 5), 0.0],
                        [round(p1[0], 5), round(p1[1], 5), round(max(0.0, z1), 5)],
                        [round(p0[0], 5), round(p0[1], 5), round(max(0.0, z0), 5)],
                    ],
                }
            )
            inferred_length += right - left

    return existing + inferred, inferred_length


def build_clean_export(
    *,
    refined: dict[str, Any],
    roof: dict[str, Any],
    footprint: dict[str, Any],
    topology: dict[str, Any],
    close_perimeter: bool = True,
) -> dict[str, Any]:
    shell = build_shell_preview(
        refined,
        roof=roof,
        footprint=footprint,
        topology=topology,
    )
    walls = [dict(wall) for wall in shell.get("perimeter_walls", [])]
    for wall in walls:
        wall.setdefault("provenance", "direct_supported_perimeter")
    inferred_length = 0.0
    if close_perimeter:
        shell_for_close = dict(shell)
        shell_for_close["perimeter_walls"] = walls
        walls, inferred_length = close_perimeter_walls(
            shell_for_close,
            refined=refined,
            footprint=footprint,
            roof=roof,
        )
    ring = _footprint_ring(footprint)
    perimeter = sum(math.hypot(b[0]-a[0], b[1]-a[1]) for a, b in _segments(ring))
    direct = float(shell.get("supported_perimeter_m", 0.0))
    return {
        "schema_version": 1,
        "method": "clean polygonal shell export with explicit provisional perimeter closure",
        "georeference": refined.get("georeference", {}),
        "roof_resolved_area_m2": float(refined.get("resolved_area_m2", 0.0)),
        "roof_unresolved_area_m2": float(refined.get("remaining_unresolved_area_m2", 0.0)),
        "roof_regions": refined.get("regions", []),
        "perimeter_walls": walls,
        "height_step_faces": shell.get("height_step_faces", []),
        "floor_polygon_local_xy": [[round(x, 5), round(y, 5)] for x, y in ring],
        "perimeter_m": round(perimeter, 4),
        "direct_supported_perimeter_m": round(direct, 4),
        "provisional_closed_perimeter_m": round(inferred_length, 4),
        "exported_perimeter_ratio": round(min(1.0, (direct + inferred_length) / perimeter), 6) if perimeter else 0.0,
        "provisional_wall_count": sum(1 for wall in walls if wall.get("provenance") == "provisional_perimeter_closure"),
        "watertight_claim": False,
        "notes": [
            "Roof polygons are exported as polygons, not first-vertex triangle fans.",
            "Provisional perimeter closures are explicit and are not promoted to measured evidence.",
            "Remaining unresolved roof area stays open and is reported separately.",
        ],
    }


def _obj_add_polygon(lines: list[str], raw: list[list[float]], offset: int) -> int:
    if len(raw) < 3:
        return offset
    for vertex in raw:
        lines.append(f"v {float(vertex[0]):.6f} {float(vertex[1]):.6f} {float(vertex[2]):.6f}")
    lines.append("f " + " ".join(str(offset + i) for i in range(len(raw))))
    return offset + len(raw)


def write_obj(path: Path, result: dict[str, Any]) -> None:
    geo = result.get("georeference", {})
    lines = [
        "# BatiForge clean shell export",
        "# X east / Y north / Z up",
        "# polygonal faces are intentional; no concave first-vertex fan triangulation",
        "s off",
        f"# horizontal_crs={geo.get('horizontal_crs')}",
        f"# vertical_datum={geo.get('vertical_datum')}",
    ]
    offset = 1
    for region in result.get("roof_regions", []):
        lines.append(f"o roof_r{int(region.get('region_index', 0)):03d}_p{int(region['plane_index']):02d}")
        offset = _obj_add_polygon(lines, region.get("vertices_local_xyz", []), offset)
    for index, wall in enumerate(result.get("perimeter_walls", []), start=1):
        lines.append(f"o wall_{index:03d}_{wall.get('provenance', 'unknown')}")
        offset = _obj_add_polygon(lines, wall.get("vertices_local_xyz", []), offset)
    for index, step in enumerate(result.get("height_step_faces", []), start=1):
        lines.append(f"o height_step_{index:03d}")
        offset = _obj_add_polygon(lines, step.get("vertices_local_xyz", []), offset)
    floor = [[float(x), float(y), 0.0] for x, y in result.get("floor_polygon_local_xy", [])]
    lines.append("o ground_floor")
    _obj_add_polygon(lines, floor, offset)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_ply(path: Path, result: dict[str, Any]) -> None:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[list[int], int, int]] = []

    def add(raw: list[list[float]], face_type: int, provenance: int) -> None:
        if len(raw) < 3:
            return
        ids: list[int] = []
        for v in raw:
            ids.append(len(vertices))
            vertices.append((float(v[0]), float(v[1]), float(v[2])))
        faces.append((ids, face_type, provenance))

    for region in result.get("roof_regions", []):
        add(region.get("vertices_local_xyz", []), 0, 0)
    for wall in result.get("perimeter_walls", []):
        prov = 1 if wall.get("provenance") == "provisional_perimeter_closure" else 0
        add(wall.get("vertices_local_xyz", []), 1, prov)
    for step in result.get("height_step_faces", []):
        add(step.get("vertices_local_xyz", []), 2, 0)
    add([[float(x), float(y), 0.0] for x, y in result.get("floor_polygon_local_xy", [])], 3, 0)

    lines = [
        "ply",
        "format ascii 1.0",
        "comment BatiForge clean polygonal shell export",
        "comment face_type 0=roof 1=wall 2=height_step 3=floor",
        "comment provenance 0=evidence_or_existing_inference 1=provisional_perimeter_closure",
        f"element vertex {len(vertices)}",
        "property float x",
        "property float y",
        "property float z",
        f"element face {len(faces)}",
        "property list uchar int vertex_indices",
        "property int face_type",
        "property int provenance",
        "end_header",
    ]
    lines.extend(f"{x:.6f} {y:.6f} {z:.6f}" for x, y, z in vertices)
    for ids, face_type, provenance in faces:
        lines.append(f"{len(ids)} " + " ".join(str(i) for i in ids) + f" {face_type} {provenance}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export a clean polygonal BatiForge shell without fan-triangulation artifacts.")
    parser.add_argument("--refined-json", type=Path, required=True)
    parser.add_argument("--roof-json", type=Path, required=True)
    parser.add_argument("--footprint-json", type=Path, required=True)
    parser.add_argument("--topology-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-obj", type=Path, required=True)
    parser.add_argument("--output-ply", type=Path, required=True)
    parser.add_argument("--no-close-perimeter", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        refined = _load_json(args.refined_json)
        roof = _load_json(args.roof_json)
        footprint = _load_json(args.footprint_json)
        topology = _load_json(args.topology_json)
        result = build_clean_export(
            refined=refined,
            roof=roof,
            footprint=footprint,
            topology=topology,
            close_perimeter=not args.no_close_perimeter,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"BatiForge clean shell export failed: {exc}")
        return 2

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    write_obj(args.output_obj, result)
    write_ply(args.output_ply, result)
    print(
        "clean shell export: "
        f"direct_perimeter={result['direct_supported_perimeter_m']:.2f}m "
        f"provisional_closure={result['provisional_closed_perimeter_m']:.2f}m "
        f"exported_ratio={result['exported_perimeter_ratio']:.4f} "
        f"roof_unresolved={result['roof_unresolved_area_m2']:.2f}m2"
    )
    print(f"json: {args.output_json}")
    print(f"obj: {args.output_obj}")
    print(f"ply: {args.output_ply}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
