from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from .roof_regions import _ear_clip, _plane_lookup


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def _footprint_ring(footprint: dict[str, Any]) -> list[tuple[float, float]]:
    raw = footprint.get("polygons_local_xy")
    if not isinstance(raw, list) or len(raw) != 1 or len(raw[0]) < 3:
        raise ValueError("shell preview currently requires one simple footprint polygon")
    ring = [(float(p[0]), float(p[1])) for p in raw[0]]
    if len(ring) >= 2 and math.hypot(ring[0][0] - ring[-1][0], ring[0][1] - ring[-1][1]) <= 1e-9:
        ring.pop()
    return ring


def _segments(poly: list[tuple[float, float]]) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    return [(poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly))]


def _region_xy(region: dict[str, Any]) -> list[tuple[float, float]]:
    return [(float(v[0]), float(v[1])) for v in region.get("vertices_local_xyz", [])]


def _overlap_on_segment(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
    *,
    tolerance_m: float = 1e-4,
) -> tuple[float, float] | None:
    vx, vy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(vx, vy)
    if length <= tolerance_m:
        return None
    ux, uy = vx / length, vy / length
    nx, ny = -uy, ux
    if abs((c[0] - a[0]) * nx + (c[1] - a[1]) * ny) > tolerance_m:
        return None
    if abs((d[0] - a[0]) * nx + (d[1] - a[1]) * ny) > tolerance_m:
        return None
    tc = (c[0] - a[0]) * ux + (c[1] - a[1]) * uy
    td = (d[0] - a[0]) * ux + (d[1] - a[1]) * uy
    left = max(0.0, min(tc, td))
    right = min(length, max(tc, td))
    if right <= left + tolerance_m:
        return None
    return left, right


def _merge_intervals(intervals: list[tuple[float, float]], tolerance_m: float = 1e-4) -> list[tuple[float, float]]:
    if not intervals:
        return []
    merged: list[list[float]] = []
    for left, right in sorted(intervals):
        if not merged or left > merged[-1][1] + tolerance_m:
            merged.append([left, right])
        else:
            merged[-1][1] = max(merged[-1][1], right)
    return [(left, right) for left, right in merged]


def _point_on(a: tuple[float, float], b: tuple[float, float], distance: float) -> tuple[float, float]:
    length = math.hypot(b[0] - a[0], b[1] - a[1])
    if length <= 1e-12:
        return a
    return (
        a[0] + (b[0] - a[0]) * distance / length,
        a[1] + (b[1] - a[1]) * distance / length,
    )


def _z_local(plane: tuple[float, float, float], x: float, y: float, ground_z: float) -> float:
    return plane[0] * x + plane[1] * y + plane[2] - ground_z


def _perimeter_walls(
    refined: dict[str, Any],
    footprint: dict[str, Any],
    roof: dict[str, Any],
    *,
    min_overlap_m: float,
) -> tuple[list[dict[str, Any]], float, float]:
    ring = _footprint_ring(footprint)
    planes = _plane_lookup(roof)
    ground_z = float(refined["georeference"]["ground_z"])
    walls: list[dict[str, Any]] = []
    perimeter = 0.0
    covered = 0.0

    for edge_index, (a, b) in enumerate(_segments(ring), start=1):
        edge_length = math.hypot(b[0] - a[0], b[1] - a[1])
        perimeter += edge_length
        by_plane: dict[int, list[tuple[float, float]]] = defaultdict(list)
        all_intervals: list[tuple[float, float]] = []

        for region in refined.get("regions", []):
            plane_index = int(region["plane_index"])
            for c, d in _segments(_region_xy(region)):
                overlap = _overlap_on_segment(a, b, c, d)
                if overlap is None:
                    continue
                if overlap[1] - overlap[0] < min_overlap_m:
                    continue
                by_plane[plane_index].append(overlap)
                all_intervals.append(overlap)

        covered += sum(right - left for left, right in _merge_intervals(all_intervals))

        for plane_index, intervals in sorted(by_plane.items()):
            if plane_index not in planes:
                raise ValueError(f"unknown roof plane {plane_index}")
            for left, right in _merge_intervals(intervals):
                if right - left < min_overlap_m:
                    continue
                p0 = _point_on(a, b, left)
                p1 = _point_on(a, b, right)
                z0 = _z_local(planes[plane_index], p0[0], p0[1], ground_z)
                z1 = _z_local(planes[plane_index], p1[0], p1[1], ground_z)
                if max(z0, z1) <= 0.0:
                    continue
                walls.append(
                    {
                        "edge_index": edge_index,
                        "plane_index": plane_index,
                        "length_m": round(right - left, 4),
                        "vertices_local_xyz": [
                            [round(p0[0], 5), round(p0[1], 5), 0.0],
                            [round(p1[0], 5), round(p1[1], 5), 0.0],
                            [round(p1[0], 5), round(p1[1], 5), round(z1, 5)],
                            [round(p0[0], 5), round(p0[1], 5), round(z0, 5)],
                        ],
                    }
                )
    return walls, perimeter, covered


def _step_faces(
    topology: dict[str, Any],
    roof: dict[str, Any],
    *,
    ground_z: float,
    min_boundary_length_m: float,
) -> list[dict[str, Any]]:
    planes = _plane_lookup(roof)
    wanted = {
        tuple(sorted((int(a["plane_a"]), int(a["plane_b"])))): float(a["approx_boundary_length_m"])
        for a in topology.get("adjacencies", [])
        if a.get("relation") == "height_step_or_overlap_candidate"
        and float(a.get("approx_boundary_length_m", 0.0)) >= min_boundary_length_m
    }
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for segment in topology.get("boundary_segments", []):
        pair = tuple(sorted((int(segment["plane_a"]), int(segment["plane_b"]))))
        if pair in wanted:
            grouped[pair].append(segment)

    faces: list[dict[str, Any]] = []
    for pair, segments in sorted(grouped.items()):
        if len(segments) < 2:
            continue
        midpoints = np.asarray(
            [[0.5 * (float(s["x0"]) + float(s["x1"])), 0.5 * (float(s["y0"]) + float(s["y1"]))] for s in segments],
            dtype=np.float64,
        )
        center = midpoints.mean(axis=0)
        _, _, vh = np.linalg.svd(midpoints - center, full_matrices=False)
        direction = vh[0]
        endpoints = np.asarray(
            [[float(s[kx]), float(s[ky])] for s in segments for kx, ky in (("x0", "y0"), ("x1", "y1"))],
            dtype=np.float64,
        )
        t = (endpoints - center) @ direction
        start_xy = center + direction * float(np.min(t))
        end_xy = center + direction * float(np.max(t))
        pa, pb = planes[pair[0]], planes[pair[1]]
        za0 = _z_local(pa, float(start_xy[0]), float(start_xy[1]), ground_z)
        za1 = _z_local(pa, float(end_xy[0]), float(end_xy[1]), ground_z)
        zb0 = _z_local(pb, float(start_xy[0]), float(start_xy[1]), ground_z)
        zb1 = _z_local(pb, float(end_xy[0]), float(end_xy[1]), ground_z)
        faces.append(
            {
                "plane_a": pair[0],
                "plane_b": pair[1],
                "support_length_m": round(wanted[pair], 4),
                "vector_length_m": round(float(np.max(t) - np.min(t)), 4),
                "vertices_local_xyz": [
                    [round(float(start_xy[0]), 5), round(float(start_xy[1]), 5), round(za0, 5)],
                    [round(float(end_xy[0]), 5), round(float(end_xy[1]), 5), round(za1, 5)],
                    [round(float(end_xy[0]), 5), round(float(end_xy[1]), 5), round(zb1, 5)],
                    [round(float(start_xy[0]), 5), round(float(start_xy[1]), 5), round(zb0, 5)],
                ],
            }
        )
    return faces


def build_shell_preview(
    refined: dict[str, Any],
    *,
    roof: dict[str, Any],
    footprint: dict[str, Any],
    topology: dict[str, Any],
    min_perimeter_overlap_m: float = 0.05,
    min_step_boundary_length_m: float = 1.0,
) -> dict[str, Any]:
    georef = refined.get("georeference")
    if not isinstance(georef, dict):
        raise ValueError("refined roof has no georeference")
    walls, perimeter, covered = _perimeter_walls(
        refined, footprint, roof, min_overlap_m=min_perimeter_overlap_m
    )
    steps = _step_faces(
        topology,
        roof,
        ground_z=float(georef["ground_z"]),
        min_boundary_length_m=min_step_boundary_length_m,
    )
    ring = _footprint_ring(footprint)
    floor_triangles = [
        [[round(x, 5), round(y, 5), 0.0] for x, y in tri]
        for tri in _ear_clip(tuple(ring))
    ]
    return {
        "schema_version": 1,
        "method": "evidence-bounded roof + supported perimeter walls + measured height-step faces",
        "georeference": georef,
        "parameters": {
            "min_perimeter_overlap_m": min_perimeter_overlap_m,
            "min_step_boundary_length_m": min_step_boundary_length_m,
        },
        "watertight_claim": False,
        "roof_resolved_area_m2": float(refined["resolved_area_m2"]),
        "roof_resolved_area_ratio": float(refined["resolved_area_ratio"]),
        "roof_unresolved_area_m2": float(refined["remaining_unresolved_area_m2"]),
        "perimeter_m": round(perimeter, 4),
        "supported_perimeter_m": round(covered, 4),
        "supported_perimeter_ratio": round(covered / perimeter if perimeter else 0.0, 6),
        "roof_region_count": len(refined.get("regions", [])),
        "perimeter_wall_count": len(walls),
        "height_step_face_count": len(steps),
        "floor_triangle_count": len(floor_triangles),
        "roof_regions": refined.get("regions", []),
        "perimeter_walls": walls,
        "height_step_faces": steps,
        "floor_triangles": floor_triangles,
    }


def _mesh_arrays(shell: dict[str, Any]) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]], list[int], list[int], list[int]]:
    vertices: list[tuple[float, float, float]] = []
    vertex_map: dict[tuple[float, float, float], int] = {}
    faces: list[tuple[int, int, int]] = []
    face_types: list[int] = []
    plane_a: list[int] = []
    plane_b: list[int] = []

    def idx(raw: list[float]) -> int:
        key = (round(float(raw[0]), 5), round(float(raw[1]), 5), round(float(raw[2]), 5))
        if key not in vertex_map:
            vertex_map[key] = len(vertices)
            vertices.append(key)
        return vertex_map[key]

    def add_poly(raw: list[list[float]], face_type: int, pa: int = -1, pb: int = -1) -> None:
        ids = [idx(v) for v in raw]
        for i in range(1, len(ids) - 1):
            faces.append((ids[0], ids[i], ids[i + 1]))
            face_types.append(face_type)
            plane_a.append(pa)
            plane_b.append(pb)

    for region in shell["roof_regions"]:
        add_poly(region["vertices_local_xyz"], 0, int(region["plane_index"]))
    for wall in shell["perimeter_walls"]:
        add_poly(wall["vertices_local_xyz"], 1, int(wall["plane_index"]))
    for step in shell["height_step_faces"]:
        add_poly(step["vertices_local_xyz"], 2, int(step["plane_a"]), int(step["plane_b"]))
    for tri in shell["floor_triangles"]:
        add_poly(tri, 3)
    return vertices, faces, face_types, plane_a, plane_b


def write_shell_ply(path: Path, shell: dict[str, Any]) -> None:
    vertices, faces, types, plane_a, plane_b = _mesh_arrays(shell)
    lines = [
        "ply",
        "format ascii 1.0",
        "comment BatiForge shell preview; X east, Y north, Z up",
        "comment face_type 0=roof 1=perimeter_wall 2=height_step 3=ground",
        f"element vertex {len(vertices)}",
        "property float x",
        "property float y",
        "property float z",
        f"element face {len(faces)}",
        "property list uchar int vertex_indices",
        "property int face_type",
        "property int plane_a",
        "property int plane_b",
        "end_header",
    ]
    lines.extend(f"{x:.6f} {y:.6f} {z:.6f}" for x, y, z in vertices)
    lines.extend(
        f"3 {a} {b} {c} {t} {pa} {pb}"
        for (a, b, c), t, pa, pb in zip(faces, types, plane_a, plane_b, strict=True)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_shell_obj(path: Path, shell: dict[str, Any]) -> None:
    vertices, faces, types, _, _ = _mesh_arrays(shell)
    lines = [
        "# BatiForge shell preview",
        "# X east / Y north / Z up",
        "# NOT WATERTIGHT: unresolved roof area is intentionally left open",
    ]
    lines.extend(f"v {x:.6f} {y:.6f} {z:.6f}" for x, y, z in vertices)
    names = {0: "roof", 1: "perimeter_walls", 2: "height_steps", 3: "ground"}
    for face_type in (0, 1, 2, 3):
        lines.append(f"g {names[face_type]}")
        for (a, b, c), current_type in zip(faces, types, strict=True):
            if current_type == face_type:
                lines.append(f"f {a + 1} {b + 1} {c + 1}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Build a non-watertight evidence-bounded BatiForge shell preview.")
    p.add_argument("--refined-json", type=Path, required=True)
    p.add_argument("--roof-json", type=Path, required=True)
    p.add_argument("--footprint-json", type=Path, required=True)
    p.add_argument("--topology-json", type=Path, required=True)
    p.add_argument("--output-json", type=Path, required=True)
    p.add_argument("--output-ply", type=Path, required=True)
    p.add_argument("--output-obj", type=Path, required=True)
    p.add_argument("--min-perimeter-overlap-m", type=float, default=0.05)
    p.add_argument("--min-step-boundary-length-m", type=float, default=1.0)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        refined = _load_json(args.refined_json)
        roof = _load_json(args.roof_json)
        footprint = _load_json(args.footprint_json)
        topology = _load_json(args.topology_json)
        shell = build_shell_preview(
            refined,
            roof=roof,
            footprint=footprint,
            topology=topology,
            min_perimeter_overlap_m=args.min_perimeter_overlap_m,
            min_step_boundary_length_m=args.min_step_boundary_length_m,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"BatiForge shell preview failed: {exc}")
        return 2

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(shell, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_shell_ply(args.output_ply, shell)
    write_shell_obj(args.output_obj, shell)
    print(
        "shell preview: "
        f"roof_ratio={shell['roof_resolved_area_ratio']:.3f} "
        f"perimeter={shell['supported_perimeter_m']:.2f}/{shell['perimeter_m']:.2f}m "
        f"walls={shell['perimeter_wall_count']} steps={shell['height_step_face_count']} "
        f"open_roof={shell['roof_unresolved_area_m2']:.2f}m2"
    )
    print(f"json: {args.output_json}")
    print(f"ply: {args.output_ply}")
    print(f"obj: {args.output_obj}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
