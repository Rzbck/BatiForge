from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import laspy
import numpy as np

from .rnb_footprint import _points_in_ring


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def _validate_frames(*payloads: dict[str, Any]) -> tuple[float, float, float, str, str]:
    frames: list[tuple[float, float, float, str, str]] = []
    for payload in payloads:
        georef = payload.get("georeference")
        if isinstance(georef, dict):
            frames.append(
                (
                    float(georef["origin_x"]),
                    float(georef["origin_y"]),
                    float(georef["ground_z"]),
                    str(georef["horizontal_crs"]),
                    str(georef["vertical_datum"]),
                )
            )
            continue
        if "origin_x" in payload and "origin_y" in payload and "target_crs" in payload:
            frames.append(
                (
                    float(payload["origin_x"]),
                    float(payload["origin_y"]),
                    float("nan"),
                    str(payload["target_crs"]),
                    "",
                )
            )
            continue
        raise ValueError("payload has no usable georeference")

    reference = frames[0]
    for frame in frames[1:]:
        if abs(frame[0] - reference[0]) > 1e-3 or abs(frame[1] - reference[1]) > 1e-3:
            raise ValueError("local-frame origin mismatch")
        if frame[3] != reference[3]:
            raise ValueError("horizontal CRS mismatch")
        if math.isfinite(frame[2]) and math.isfinite(reference[2]) and abs(frame[2] - reference[2]) > 1e-3:
            raise ValueError("ground reference mismatch")
    return reference


def _local_footprint_ring(footprint: dict[str, Any]) -> tuple[tuple[float, float], ...]:
    polygons = footprint.get("polygons_local_xy")
    if not isinstance(polygons, list) or len(polygons) != 1:
        raise ValueError("roof-region stage currently requires one simple footprint polygon")
    raw = polygons[0]
    if not isinstance(raw, list) or len(raw) < 3:
        raise ValueError("invalid footprint polygon")
    ring = [(float(point[0]), float(point[1])) for point in raw]
    return _clean_ring(tuple(ring))


def _signed_area(ring: tuple[tuple[float, float], ...] | list[tuple[float, float]]) -> float:
    if len(ring) < 3:
        return 0.0
    return 0.5 * sum(
        ring[i][0] * ring[(i + 1) % len(ring)][1]
        - ring[(i + 1) % len(ring)][0] * ring[i][1]
        for i in range(len(ring))
    )


def _clean_ring(ring: tuple[tuple[float, float], ...]) -> tuple[tuple[float, float], ...]:
    cleaned: list[tuple[float, float]] = []
    for point in ring:
        if not cleaned or math.hypot(point[0] - cleaned[-1][0], point[1] - cleaned[-1][1]) > 1e-9:
            cleaned.append(point)
    if len(cleaned) >= 2 and math.hypot(cleaned[0][0] - cleaned[-1][0], cleaned[0][1] - cleaned[-1][1]) <= 1e-9:
        cleaned.pop()
    if len(cleaned) < 3:
        raise ValueError("footprint ring has fewer than three unique vertices")
    if _signed_area(cleaned) < 0.0:
        cleaned.reverse()
    return tuple(cleaned)


def _cross(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _point_in_triangle(
    point: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    eps: float = 1e-10,
) -> bool:
    c1 = _cross(a, b, point)
    c2 = _cross(b, c, point)
    c3 = _cross(c, a, point)
    return c1 >= -eps and c2 >= -eps and c3 >= -eps


def _ear_clip(ring: tuple[tuple[float, float], ...]) -> list[list[tuple[float, float]]]:
    vertices = list(ring)
    indices = list(range(len(vertices)))
    triangles: list[list[tuple[float, float]]] = []
    guard = 0

    while len(indices) > 3:
        ear_found = False
        guard += 1
        if guard > len(vertices) * len(vertices) * 2:
            raise ValueError("could not triangulate footprint polygon")
        for position, current in enumerate(indices):
            previous = indices[position - 1]
            following = indices[(position + 1) % len(indices)]
            a, b, c = vertices[previous], vertices[current], vertices[following]
            if _cross(a, b, c) <= 1e-10:
                continue
            if any(
                other not in (previous, current, following)
                and _point_in_triangle(vertices[other], a, b, c)
                for other in indices
            ):
                continue
            triangles.append([a, b, c])
            del indices[position]
            ear_found = True
            break
        if not ear_found:
            # Remove one nearly-collinear vertex and retry before failing hard.
            removed = False
            for position, current in enumerate(indices):
                previous = indices[position - 1]
                following = indices[(position + 1) % len(indices)]
                if abs(_cross(vertices[previous], vertices[current], vertices[following])) <= 1e-8:
                    del indices[position]
                    removed = True
                    break
            if not removed:
                raise ValueError("footprint triangulation stalled on non-simple geometry")

    triangles.append([vertices[index] for index in indices])
    return triangles


def _normalize_line(a: float, b: float, c: float) -> tuple[float, float, float]:
    norm = math.hypot(a, b)
    if norm <= 1e-12:
        raise ValueError("degenerate divider line")
    a, b, c = a / norm, b / norm, c / norm
    if a < -1e-12 or (abs(a) <= 1e-12 and b < 0.0):
        a, b, c = -a, -b, -c
    return a, b, c


def _clip_half_plane(
    polygon: list[tuple[float, float]],
    line: tuple[float, float, float],
    keep_positive: bool,
) -> list[tuple[float, float]]:
    if not polygon:
        return []
    a, b, c = line

    def value(point: tuple[float, float]) -> float:
        raw = a * point[0] + b * point[1] + c
        return raw if keep_positive else -raw

    output: list[tuple[float, float]] = []
    previous = polygon[-1]
    previous_value = value(previous)
    previous_inside = previous_value >= -1e-9
    for current in polygon:
        current_value = value(current)
        current_inside = current_value >= -1e-9
        if current_inside != previous_inside:
            denominator = previous_value - current_value
            if abs(denominator) > 1e-15:
                t = previous_value / denominator
                intersection = (
                    previous[0] + t * (current[0] - previous[0]),
                    previous[1] + t * (current[1] - previous[1]),
                )
                output.append(intersection)
        if current_inside:
            output.append(current)
        previous = current
        previous_value = current_value
        previous_inside = current_inside
    return output


def _split_convex_polygon(
    polygon: list[tuple[float, float]],
    line: tuple[float, float, float],
    min_area_m2: float,
) -> list[list[tuple[float, float]]]:
    values = [line[0] * x + line[1] * y + line[2] for x, y in polygon]
    if min(values) >= -1e-8 or max(values) <= 1e-8:
        return [polygon]
    pieces = []
    for keep_positive in (True, False):
        clipped = _clip_half_plane(polygon, line, keep_positive)
        if len(clipped) >= 3 and abs(_signed_area(clipped)) >= min_area_m2:
            pieces.append(clipped)
    return pieces or [polygon]


def _plane_lookup(roof: dict[str, Any]) -> dict[int, tuple[float, float, float]]:
    planes = roof.get("planes")
    if not isinstance(planes, list) or not planes:
        raise ValueError("roof JSON has no planes")
    return {
        int(plane["index"]): (float(plane["a"]), float(plane["b"]), float(plane["c"]))
        for plane in planes
    }


def _continuous_dividers(vectors: dict[str, Any]) -> list[dict[str, Any]]:
    dividers: list[dict[str, Any]] = []
    for edge in vectors.get("vector_edges", []):
        raw = edge.get("equality_line_local")
        if not isinstance(raw, dict):
            continue
        line = _normalize_line(float(raw["a"]), float(raw["b"]), float(raw["c"]))
        dividers.append(
            {
                "kind": "continuous",
                "plane_a": int(edge["plane_a"]),
                "plane_b": int(edge["plane_b"]),
                "line": line,
                "evidence_length_m": float(edge["measured_boundary_length_m"]),
            }
        )
    return dividers


def _step_dividers(
    topology: dict[str, Any],
    *,
    min_step_boundary_length_m: float,
) -> list[dict[str, Any]]:
    step_pairs = {
        tuple(sorted((int(item["plane_a"]), int(item["plane_b"])))): float(item["approx_boundary_length_m"])
        for item in topology.get("adjacencies", [])
        if item.get("relation") == "height_step_or_overlap_candidate"
        and float(item.get("approx_boundary_length_m", 0.0)) >= min_step_boundary_length_m
    }
    grouped: dict[tuple[int, int], list[tuple[float, float]]] = {pair: [] for pair in step_pairs}
    for segment in topology.get("boundary_segments", []):
        pair = tuple(sorted((int(segment["plane_a"]), int(segment["plane_b"]))))
        if pair not in grouped:
            continue
        grouped[pair].append(
            (
                0.5 * (float(segment["x0"]) + float(segment["x1"])),
                0.5 * (float(segment["y0"]) + float(segment["y1"])),
            )
        )

    dividers: list[dict[str, Any]] = []
    for pair, points in sorted(grouped.items()):
        if len(points) < 2:
            continue
        matrix = np.asarray(points, dtype=np.float64)
        center = matrix.mean(axis=0)
        _, _, vh = np.linalg.svd(matrix - center, full_matrices=False)
        direction = vh[0]
        normal = np.asarray([-direction[1], direction[0]], dtype=np.float64)
        line = _normalize_line(
            float(normal[0]),
            float(normal[1]),
            -float(normal[0] * center[0] + normal[1] * center[1]),
        )
        dividers.append(
            {
                "kind": "height_step",
                "plane_a": pair[0],
                "plane_b": pair[1],
                "line": line,
                "evidence_length_m": step_pairs[pair],
            }
        )
    return dividers


def _load_las_xyz(path: Path, classification: int | None) -> np.ndarray:
    las = laspy.read(path)
    xyz = np.column_stack(
        (
            np.asarray(las.x, dtype=np.float64),
            np.asarray(las.y, dtype=np.float64),
            np.asarray(las.z, dtype=np.float64),
        )
    )
    if classification is not None and "classification" in las.point_format.dimension_names:
        classes = np.asarray(las.classification)
        xyz = xyz[classes == classification]
    if len(xyz) == 0:
        raise ValueError("no LiDAR points remain after classification filtering")
    return xyz


def build_roof_regions(
    xyz: np.ndarray,
    *,
    roof: dict[str, Any],
    footprint: dict[str, Any],
    topology: dict[str, Any],
    vectors: dict[str, Any],
    residual_threshold_m: float = 0.18,
    min_height_m: float = 2.0,
    high_structure_min_height_m: float = 22.0,
    min_region_points: int = 3,
    min_region_purity: float = 0.55,
    min_partition_area_m2: float = 0.01,
    min_step_boundary_length_m: float = 1.0,
) -> dict[str, Any]:
    """Build vector roof-face regions from measured planes and supported dividers.

    The footprint is triangulated only as an internal robust polygon-partition aid.
    Continuous dividers are exact plane-equality lines. Height-step dividers are
    straight least-squares/PCA fits to measured topology boundaries. Each final
    polygon piece is assigned to a roof plane only when real LiDAR support inside
    that piece passes point-count and purity gates. Unresolved area stays explicit.
    """

    if residual_threshold_m <= 0.0:
        raise ValueError("residual_threshold_m must be > 0")
    if min_region_points < 1:
        raise ValueError("min_region_points must be >= 1")
    if not 0.0 < min_region_purity <= 1.0:
        raise ValueError("min_region_purity must be in (0, 1]")
    if min_partition_area_m2 <= 0.0:
        raise ValueError("min_partition_area_m2 must be > 0")

    origin_x, origin_y, ground_z, horizontal_crs, vertical_datum = _validate_frames(
        roof, footprint, topology, vectors
    )
    ring = _local_footprint_ring(footprint)
    footprint_area = abs(_signed_area(ring))
    planes = _plane_lookup(roof)

    dividers = _continuous_dividers(vectors)
    dividers.extend(
        _step_dividers(topology, min_step_boundary_length_m=min_step_boundary_length_m)
    )

    pieces: list[list[tuple[float, float]]] = _ear_clip(ring)
    for divider in dividers:
        next_pieces: list[list[tuple[float, float]]] = []
        for polygon in pieces:
            next_pieces.extend(
                _split_convex_polygon(
                    polygon,
                    divider["line"],
                    min_partition_area_m2,
                )
            )
        pieces = next_pieces

    points = np.asarray(xyz, dtype=np.float64)
    points = points[np.isfinite(points).all(axis=1)]
    if len(points) == 0:
        raise ValueError("no finite LiDAR points")
    local_xy = points[:, :2].copy()
    local_xy[:, 0] -= origin_x
    local_xy[:, 1] -= origin_y
    z_above = points[:, 2] - ground_z

    footprint_abs = tuple((x + origin_x, y + origin_y) for x, y in ring)
    inside = _points_in_ring(points[:, :2], footprint_abs)
    main_mask = inside & (z_above >= min_height_m) & (z_above < high_structure_min_height_m)
    candidate_xyz = points[main_mask]
    candidate_xy = local_xy[main_mask]

    plane_indices = np.asarray(sorted(planes), dtype=np.int64)
    plane_a = np.asarray([planes[int(index)][0] for index in plane_indices], dtype=np.float64)
    plane_b = np.asarray([planes[int(index)][1] for index in plane_indices], dtype=np.float64)
    plane_c = np.asarray([planes[int(index)][2] for index in plane_indices], dtype=np.float64)
    predicted = (
        candidate_xy[:, 0, None] * plane_a[None, :]
        + candidate_xy[:, 1, None] * plane_b[None, :]
        + plane_c[None, :]
    )
    residuals = np.abs(candidate_xyz[:, 2, None] - predicted)
    best_column = np.argmin(residuals, axis=1)
    accepted = residuals[np.arange(len(candidate_xyz)), best_column] <= residual_threshold_m
    assigned_plane = plane_indices[best_column]

    regions: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    area_by_plane: Counter[int] = Counter()

    for piece_index, polygon in enumerate(pieces, start=1):
        area = abs(_signed_area(polygon))
        if area < min_partition_area_m2:
            continue
        xs = [point[0] for point in polygon]
        ys = [point[1] for point in polygon]
        bbox_mask = (
            (candidate_xy[:, 0] >= min(xs) - 1e-9)
            & (candidate_xy[:, 0] <= max(xs) + 1e-9)
            & (candidate_xy[:, 1] >= min(ys) - 1e-9)
            & (candidate_xy[:, 1] <= max(ys) + 1e-9)
        )
        rows = np.flatnonzero(bbox_mask)
        if len(rows):
            rows = rows[_points_in_ring(candidate_xy[rows], tuple(polygon))]
        support_rows = rows[accepted[rows]] if len(rows) else np.empty(0, dtype=np.int64)
        counts = Counter(int(value) for value in assigned_plane[support_rows])
        total_points = int(len(rows))

        if not counts:
            unresolved.append(
                {
                    "piece_index": piece_index,
                    "area_m2": round(area, 4),
                    "point_count": total_points,
                    "reason": "no_supported_plane",
                    "polygon_local_xy": [[round(x, 5), round(y, 5)] for x, y in polygon],
                }
            )
            continue

        plane_index, support_count = counts.most_common(1)[0]
        purity = support_count / total_points if total_points else 0.0
        if total_points < min_region_points or purity < min_region_purity:
            unresolved.append(
                {
                    "piece_index": piece_index,
                    "area_m2": round(area, 4),
                    "point_count": total_points,
                    "best_plane_index": plane_index,
                    "best_plane_support_count": support_count,
                    "purity": round(purity, 6),
                    "reason": "insufficient_support_or_purity",
                    "polygon_local_xy": [[round(x, 5), round(y, 5)] for x, y in polygon],
                }
            )
            continue

        a, b, c = planes[plane_index]
        vertices = [
            [round(x, 5), round(y, 5), round(a * x + b * y + c - ground_z, 5)]
            for x, y in polygon
        ]
        regions.append(
            {
                "region_index": len(regions) + 1,
                "source_piece_index": piece_index,
                "plane_index": plane_index,
                "area_xy_m2": round(area, 4),
                "point_count": total_points,
                "support_count": support_count,
                "purity": round(purity, 6),
                "vertices_local_xyz": vertices,
            }
        )
        area_by_plane[plane_index] += area

    resolved_area = sum(float(region["area_xy_m2"]) for region in regions)
    unresolved_area = sum(float(region["area_m2"]) for region in unresolved)

    return {
        "schema_version": 1,
        "method": "vector footprint partition + analytic roof planes + LiDAR-supported region assignment",
        "georeference": {
            "origin_x": origin_x,
            "origin_y": origin_y,
            "ground_z": ground_z,
            "horizontal_crs": horizontal_crs,
            "vertical_datum": vertical_datum,
            "local_axes": "X east / Y north / Z up",
        },
        "parameters": {
            "residual_threshold_m": residual_threshold_m,
            "min_height_m": min_height_m,
            "high_structure_min_height_m": high_structure_min_height_m,
            "min_region_points": min_region_points,
            "min_region_purity": min_region_purity,
            "min_partition_area_m2": min_partition_area_m2,
            "min_step_boundary_length_m": min_step_boundary_length_m,
        },
        "footprint_area_m2": round(footprint_area, 4),
        "partition_piece_count": len(pieces),
        "divider_count": len(dividers),
        "continuous_divider_count": sum(1 for divider in dividers if divider["kind"] == "continuous"),
        "height_step_divider_count": sum(1 for divider in dividers if divider["kind"] == "height_step"),
        "region_count": len(regions),
        "resolved_area_m2": round(resolved_area, 4),
        "resolved_area_ratio": round(resolved_area / footprint_area if footprint_area else 0.0, 6),
        "unresolved_piece_count": len(unresolved),
        "unresolved_area_m2": round(unresolved_area, 4),
        "high_structure_point_count": int(np.count_nonzero(inside & (z_above >= high_structure_min_height_m))),
        "area_by_plane_m2": {
            str(index): round(float(area_by_plane.get(index, 0.0)), 4)
            for index in sorted(planes)
        },
        "dividers": [
            {
                "kind": divider["kind"],
                "plane_a": divider["plane_a"],
                "plane_b": divider["plane_b"],
                "line_local": [round(value, 10) for value in divider["line"]],
                "evidence_length_m": round(float(divider["evidence_length_m"]), 4),
            }
            for divider in dividers
        ],
        "regions": regions,
        "unresolved": unresolved,
    }


def _mesh_arrays(regions: dict[str, Any]) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]], list[int]]:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    face_planes: list[int] = []
    for region in regions.get("regions", []):
        raw = region["vertices_local_xyz"]
        if len(raw) < 3:
            continue
        offset = len(vertices)
        vertices.extend((float(v[0]), float(v[1]), float(v[2])) for v in raw)
        for index in range(1, len(raw) - 1):
            faces.append((offset, offset + index, offset + index + 1))
            face_planes.append(int(region["plane_index"]))
    return vertices, faces, face_planes


def write_region_obj(path: Path, regions: dict[str, Any]) -> None:
    georef = regions["georeference"]
    lines = [
        "# BatiForge support-resolved vector roof regions",
        "# axes: X east / Y north / Z up",
        "# NOTE: OBJ has no authoritative axis metadata; Blender import should use Forward=Y, Up=Z.",
        f"# horizontal_crs={georef['horizontal_crs']}",
        f"# vertical_datum={georef['vertical_datum']}",
        f"# origin_x={float(georef['origin_x']):.6f}",
        f"# origin_y={float(georef['origin_y']):.6f}",
        f"# ground_z={float(georef['ground_z']):.6f}",
    ]
    vertex_offset = 1
    for region in regions.get("regions", []):
        lines.append(
            f"o roof_region_{int(region['region_index']):03d}_p{int(region['plane_index']):02d}"
        )
        for vertex in region["vertices_local_xyz"]:
            lines.append(f"v {float(vertex[0]):.6f} {float(vertex[1]):.6f} {float(vertex[2]):.6f}")
        count = len(region["vertices_local_xyz"])
        for index in range(2, count):
            lines.append(f"f {vertex_offset} {vertex_offset + index - 1} {vertex_offset + index}")
        vertex_offset += count
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_region_ply(path: Path, regions: dict[str, Any]) -> None:
    """Write a Blender-friendly PLY that preserves the local XYZ coordinates as stored."""
    vertices, faces, face_planes = _mesh_arrays(regions)
    lines = [
        "ply",
        "format ascii 1.0",
        "comment BatiForge local metric roof regions; X east, Y north, Z up",
        f"element vertex {len(vertices)}",
        "property float x",
        "property float y",
        "property float z",
        f"element face {len(faces)}",
        "property list uchar int vertex_indices",
        "property int plane_index",
        "end_header",
    ]
    lines.extend(f"{x:.6f} {y:.6f} {z:.6f}" for x, y, z in vertices)
    lines.extend(
        f"3 {a} {b} {c} {plane_index}"
        for (a, b, c), plane_index in zip(faces, face_planes, strict=True)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build support-resolved vector roof regions from validated BatiForge evidence."
    )
    parser.add_argument("--lidar", type=Path, required=True)
    parser.add_argument("--roof-json", type=Path, required=True)
    parser.add_argument("--footprint-json", type=Path, required=True)
    parser.add_argument("--topology-json", type=Path, required=True)
    parser.add_argument("--vectors-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-obj", type=Path)
    parser.add_argument("--output-ply", type=Path)
    parser.add_argument("--classification", type=int, default=6)
    parser.add_argument("--all-classes", action="store_true")
    parser.add_argument("--residual-threshold-m", type=float, default=0.18)
    parser.add_argument("--min-height-m", type=float, default=2.0)
    parser.add_argument("--high-structure-min-height-m", type=float, default=22.0)
    parser.add_argument("--min-region-points", type=int, default=3)
    parser.add_argument("--min-region-purity", type=float, default=0.55)
    parser.add_argument("--min-partition-area-m2", type=float, default=0.01)
    parser.add_argument("--min-step-boundary-length-m", type=float, default=1.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        roof = _load_json(args.roof_json)
        footprint = _load_json(args.footprint_json)
        topology = _load_json(args.topology_json)
        vectors = _load_json(args.vectors_json)
        xyz = _load_las_xyz(args.lidar, None if args.all_classes else args.classification)
        regions = build_roof_regions(
            xyz,
            roof=roof,
            footprint=footprint,
            topology=topology,
            vectors=vectors,
            residual_threshold_m=args.residual_threshold_m,
            min_height_m=args.min_height_m,
            high_structure_min_height_m=args.high_structure_min_height_m,
            min_region_points=args.min_region_points,
            min_region_purity=args.min_region_purity,
            min_partition_area_m2=args.min_partition_area_m2,
            min_step_boundary_length_m=args.min_step_boundary_length_m,
        )
    except (OSError, ValueError, json.JSONDecodeError, laspy.errors.LaspyException) as exc:
        print(f"BatiForge roof-region build failed: {exc}")
        return 2

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(regions, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if args.output_obj:
        write_region_obj(args.output_obj, regions)
    if args.output_ply:
        write_region_ply(args.output_ply, regions)

    print(
        "roof regions: "
        f"regions={regions['region_count']} "
        f"resolved_area={regions['resolved_area_m2']:.2f}/{regions['footprint_area_m2']:.2f}m2 "
        f"ratio={regions['resolved_area_ratio']:.3f} "
        f"unresolved={regions['unresolved_piece_count']}"
    )
    print(f"json: {args.output_json}")
    if args.output_obj:
        print(f"obj: {args.output_obj}")
    if args.output_ply:
        print(f"ply: {args.output_ply}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
