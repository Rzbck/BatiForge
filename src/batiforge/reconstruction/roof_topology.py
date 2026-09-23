from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
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


def _validate_frames(roof: dict[str, Any], footprint: dict[str, Any]) -> tuple[float, float, float]:
    georef = roof.get("georeference")
    if not isinstance(georef, dict):
        raise ValueError("roof analysis has no georeference object")

    roof_crs = str(georef.get("horizontal_crs", ""))
    footprint_crs = str(footprint.get("target_crs", ""))
    if roof_crs != footprint_crs:
        raise ValueError(f"CRS mismatch: roof={roof_crs!r}, footprint={footprint_crs!r}")

    origin_x = float(georef["origin_x"])
    origin_y = float(georef["origin_y"])
    ground_z = float(georef["ground_z"])
    footprint_origin_x = float(footprint["origin_x"])
    footprint_origin_y = float(footprint["origin_y"])

    if abs(origin_x - footprint_origin_x) > 1e-3 or abs(origin_y - footprint_origin_y) > 1e-3:
        raise ValueError(
            "local-frame origin mismatch: "
            f"roof=({origin_x},{origin_y}) footprint=({footprint_origin_x},{footprint_origin_y})"
        )
    return origin_x, origin_y, ground_z


def _footprint_rings_abs(footprint: dict[str, Any]) -> tuple[tuple[tuple[float, float], ...], ...]:
    raw = footprint.get("polygons_abs_xy")
    if not isinstance(raw, list) or not raw:
        raise ValueError("footprint JSON has no polygons_abs_xy")

    rings: list[tuple[tuple[float, float], ...]] = []
    for polygon in raw:
        if not isinstance(polygon, list) or len(polygon) < 3:
            raise ValueError("invalid footprint polygon")
        ring = tuple((float(point[0]), float(point[1])) for point in polygon)
        rings.append(ring)
    return tuple(rings)


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


def _plane_arrays(roof: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    raw_planes = roof.get("planes")
    if not isinstance(raw_planes, list) or not raw_planes:
        raise ValueError("roof analysis has no planes")
    indices = np.asarray([int(plane["index"]) for plane in raw_planes], dtype=np.int64)
    a = np.asarray([float(plane["a"]) for plane in raw_planes], dtype=np.float64)
    b = np.asarray([float(plane["b"]) for plane in raw_planes], dtype=np.float64)
    c = np.asarray([float(plane["c"]) for plane in raw_planes], dtype=np.float64)
    if len(set(indices.tolist())) != len(indices):
        raise ValueError("roof plane indices are not unique")
    return indices, a, b, c


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(np.asarray(values, dtype=np.float64), q))


def analyze_topology_evidence(
    xyz: np.ndarray,
    *,
    roof: dict[str, Any],
    footprint: dict[str, Any],
    residual_threshold_m: float | None = None,
    min_height_m: float | None = None,
    high_structure_min_height_m: float = 22.0,
    cell_size_m: float = 0.5,
    min_cell_points: int = 3,
    min_cell_purity: float = 0.60,
    continuous_gap_m: float = 0.35,
) -> dict[str, Any]:
    """Build support-aware roof-topology evidence without creating final geometry.

    A metric occupancy grid is used only to measure which fitted planes are
    locally supported and where different supports become adjacent. The grid is
    evidence, not a production mesh: no staircase geometry is exported as a
    building surface.
    """

    if cell_size_m <= 0.0:
        raise ValueError("cell_size_m must be > 0")
    if min_cell_points < 1:
        raise ValueError("min_cell_points must be >= 1")
    if not 0.0 < min_cell_purity <= 1.0:
        raise ValueError("min_cell_purity must be in (0, 1]")
    if continuous_gap_m <= 0.0:
        raise ValueError("continuous_gap_m must be > 0")

    points = np.asarray(xyz, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) == 0:
        raise ValueError("xyz must be a non-empty Nx3 array")
    points = points[np.isfinite(points).all(axis=1)]
    if len(points) == 0:
        raise ValueError("no finite xyz points")

    origin_x, origin_y, ground_z = _validate_frames(roof, footprint)
    rings = _footprint_rings_abs(footprint)
    plane_indices, plane_a, plane_b, plane_c = _plane_arrays(roof)

    if residual_threshold_m is None:
        residual_threshold_m = float(roof.get("parameters", {}).get("residual_threshold_m", 0.18))
    if min_height_m is None:
        min_height_m = float(roof.get("parameters", {}).get("min_height_m", 2.0))
    if residual_threshold_m <= 0.0:
        raise ValueError("residual_threshold_m must be > 0")
    if high_structure_min_height_m <= min_height_m:
        raise ValueError("high_structure_min_height_m must be above min_height_m")

    xy_abs = points[:, :2]
    inside = np.zeros(len(points), dtype=bool)
    for ring in rings:
        inside |= _points_in_ring(xy_abs, ring)

    z_above_ground = points[:, 2] - ground_z
    main_roof_mask = (
        inside
        & (z_above_ground >= float(min_height_m))
        & (z_above_ground < float(high_structure_min_height_m))
    )
    high_structure_mask = inside & (z_above_ground >= float(high_structure_min_height_m))

    candidate = points[main_roof_mask]
    if len(candidate) == 0:
        raise ValueError("no main-roof LiDAR candidates remain")

    x_local = candidate[:, 0] - origin_x
    y_local = candidate[:, 1] - origin_y
    predicted = (
        x_local[:, None] * plane_a[None, :]
        + y_local[:, None] * plane_b[None, :]
        + plane_c[None, :]
    )
    residuals = np.abs(candidate[:, 2, None] - predicted)
    best_column = np.argmin(residuals, axis=1)
    best_residual = residuals[np.arange(len(candidate)), best_column]
    accepted = best_residual <= float(residual_threshold_m)
    assigned_plane_indices = plane_indices[best_column]

    local_rings = tuple(
        tuple((x - origin_x, y - origin_y) for x, y in ring)
        for ring in rings
    )
    all_local_xy = [point for ring in local_rings for point in ring]
    min_x = min(point[0] for point in all_local_xy)
    min_y = min(point[1] for point in all_local_xy)

    cell_totals: dict[tuple[int, int], int] = defaultdict(int)
    cell_plane_counts: dict[tuple[int, int], Counter[int]] = defaultdict(Counter)
    point_support = Counter(int(index) for index in assigned_plane_indices[accepted])

    for row in range(len(candidate)):
        ix = int(math.floor((x_local[row] - min_x) / cell_size_m))
        iy = int(math.floor((y_local[row] - min_y) / cell_size_m))
        key = (ix, iy)
        cell_totals[key] += 1
        if accepted[row]:
            cell_plane_counts[key][int(assigned_plane_indices[row])] += 1

    cell_labels: dict[tuple[int, int], int] = {}
    unresolved_sparse = 0
    unresolved_mixed = 0
    unresolved_no_support = 0
    for key, total in sorted(cell_totals.items()):
        if total < min_cell_points:
            unresolved_sparse += 1
            continue
        counts = cell_plane_counts.get(key)
        if not counts:
            unresolved_no_support += 1
            continue
        plane_index, support_count = counts.most_common(1)[0]
        purity = support_count / total
        if purity < min_cell_purity:
            unresolved_mixed += 1
            continue
        cell_labels[key] = int(plane_index)

    plane_cells = Counter(cell_labels.values())

    plane_lookup = {
        int(index): (float(a), float(b), float(c))
        for index, a, b, c in zip(plane_indices, plane_a, plane_b, plane_c, strict=True)
    }

    adjacency_raw: dict[tuple[int, int], dict[str, Any]] = {}
    boundary_segments: list[dict[str, Any]] = []

    def z_for(plane_index: int, x: float, y: float) -> float:
        a, b, c = plane_lookup[plane_index]
        return a * x + b * y + c

    for (ix, iy), left_plane in sorted(cell_labels.items()):
        for dx, dy in ((1, 0), (0, 1)):
            neighbor = (ix + dx, iy + dy)
            right_plane = cell_labels.get(neighbor)
            if right_plane is None or right_plane == left_plane:
                continue

            pair = tuple(sorted((left_plane, right_plane)))
            record = adjacency_raw.setdefault(
                pair,
                {"height_gaps": [], "line_distances": [], "edge_midpoints": []},
            )

            if dx == 1:
                x_mid = min_x + (ix + 1) * cell_size_m
                y_mid = min_y + (iy + 0.5) * cell_size_m
                p0 = (x_mid, y_mid - 0.5 * cell_size_m)
                p1 = (x_mid, y_mid + 0.5 * cell_size_m)
            else:
                x_mid = min_x + (ix + 0.5) * cell_size_m
                y_mid = min_y + (iy + 1) * cell_size_m
                p0 = (x_mid - 0.5 * cell_size_m, y_mid)
                p1 = (x_mid + 0.5 * cell_size_m, y_mid)

            z_a = z_for(pair[0], x_mid, y_mid)
            z_b = z_for(pair[1], x_mid, y_mid)
            gap = abs(z_a - z_b)

            a0, b0, c0 = plane_lookup[pair[0]]
            a1, b1, c1 = plane_lookup[pair[1]]
            line_a = a0 - a1
            line_b = b0 - b1
            line_c = c0 - c1
            line_norm = math.hypot(line_a, line_b)
            line_distance = (
                abs(line_a * x_mid + line_b * y_mid + line_c) / line_norm
                if line_norm > 1e-12
                else float("inf")
            )

            record["height_gaps"].append(gap)
            record["line_distances"].append(line_distance)
            record["edge_midpoints"].append((x_mid, y_mid))
            boundary_segments.append(
                {
                    "plane_a": pair[0],
                    "plane_b": pair[1],
                    "x0": round(p0[0], 4),
                    "y0": round(p0[1], 4),
                    "x1": round(p1[0], 4),
                    "y1": round(p1[1], 4),
                    "z_abs": round((z_a + z_b) * 0.5, 4),
                    "height_gap_m": round(gap, 4),
                }
            )

    adjacency: list[dict[str, Any]] = []
    for pair, record in sorted(adjacency_raw.items()):
        gaps = record["height_gaps"]
        distances = [value for value in record["line_distances"] if math.isfinite(value)]
        median_gap = _percentile(gaps, 50.0)
        p95_gap = _percentile(gaps, 95.0)
        median_line_distance = _percentile(distances, 50.0) if distances else None

        a0, b0, c0 = plane_lookup[pair[0]]
        a1, b1, c1 = plane_lookup[pair[1]]
        line_a = a0 - a1
        line_b = b0 - b1
        line_c = c0 - c1
        line_norm = math.hypot(line_a, line_b)
        equality_line = None
        if line_norm > 1e-12:
            equality_line = {
                "a": round(line_a / line_norm, 8),
                "b": round(line_b / line_norm, 8),
                "c": round(line_c / line_norm, 8),
            }

        if median_gap <= continuous_gap_m and (
            median_line_distance is None or median_line_distance <= max(0.75, 1.5 * cell_size_m)
        ):
            relation = "continuous_intersection_candidate"
        elif median_gap > continuous_gap_m:
            relation = "height_step_or_overlap_candidate"
        else:
            relation = "ambiguous"

        adjacency.append(
            {
                "plane_a": pair[0],
                "plane_b": pair[1],
                "boundary_edge_count": len(gaps),
                "approx_boundary_length_m": round(len(gaps) * cell_size_m, 3),
                "median_height_gap_m": round(median_gap, 4),
                "p95_height_gap_m": round(p95_gap, 4),
                "median_distance_to_plane_equality_line_m": (
                    round(float(median_line_distance), 4)
                    if median_line_distance is not None
                    else None
                ),
                "relation": relation,
                "equality_line_local": equality_line,
            }
        )

    support_payload = []
    for plane_index in plane_indices.tolist():
        support_payload.append(
            {
                "plane_index": int(plane_index),
                "assigned_point_count": int(point_support.get(int(plane_index), 0)),
                "resolved_cell_count": int(plane_cells.get(int(plane_index), 0)),
                "approx_resolved_cell_area_m2": round(
                    plane_cells.get(int(plane_index), 0) * cell_size_m * cell_size_m,
                    3,
                ),
            }
        )

    accepted_count = int(np.count_nonzero(accepted))
    observed_cell_count = len(cell_totals)
    resolved_cell_count = len(cell_labels)

    return {
        "schema_version": 1,
        "method": "support-aware occupancy topology evidence; grid is diagnostic only",
        "georeference": {
            "origin_x": origin_x,
            "origin_y": origin_y,
            "ground_z": ground_z,
            "horizontal_crs": roof["georeference"]["horizontal_crs"],
            "vertical_datum": roof["georeference"]["vertical_datum"],
            "local_axes": "X east / Y north / Z up",
        },
        "parameters": {
            "residual_threshold_m": float(residual_threshold_m),
            "min_height_m": float(min_height_m),
            "high_structure_min_height_m": float(high_structure_min_height_m),
            "cell_size_m": float(cell_size_m),
            "min_cell_points": int(min_cell_points),
            "min_cell_purity": float(min_cell_purity),
            "continuous_gap_m": float(continuous_gap_m),
        },
        "source_point_count": int(len(points)),
        "inside_footprint_point_count": int(np.count_nonzero(inside)),
        "outside_footprint_point_count": int(np.count_nonzero(~inside)),
        "main_roof_candidate_count": int(len(candidate)),
        "assigned_main_roof_point_count": accepted_count,
        "unassigned_main_roof_point_count": int(len(candidate) - accepted_count),
        "main_roof_assignment_ratio": round(accepted_count / len(candidate), 6),
        "high_structure_point_count": int(np.count_nonzero(high_structure_mask)),
        "observed_cell_count": observed_cell_count,
        "resolved_cell_count": resolved_cell_count,
        "unresolved_cell_count": observed_cell_count - resolved_cell_count,
        "resolved_cell_ratio": round(
            resolved_cell_count / observed_cell_count if observed_cell_count else 0.0,
            6,
        ),
        "unresolved_cell_reasons": {
            "sparse": unresolved_sparse,
            "mixed_support": unresolved_mixed,
            "no_plane_within_residual": unresolved_no_support,
        },
        "plane_support": support_payload,
        "adjacency_count": len(adjacency),
        "adjacencies": adjacency,
        "boundary_segment_count": len(boundary_segments),
        "boundary_segments": boundary_segments,
    }


def write_topology_boundary_obj(
    path: Path,
    topology: dict[str, Any],
    footprint: dict[str, Any],
) -> None:
    georef = topology["georeference"]
    origin_x = float(georef["origin_x"])
    origin_y = float(georef["origin_y"])
    ground_z = float(georef["ground_z"])

    lines = [
        "# BatiForge roof-topology boundary diagnostic OBJ",
        "# IMPORTANT: line evidence only; not production roof geometry",
        f"# horizontal_crs={georef['horizontal_crs']}",
        f"# vertical_datum={georef['vertical_datum']}",
        f"# origin_x={origin_x:.6f}",
        f"# origin_y={origin_y:.6f}",
        f"# ground_z={ground_z:.6f}",
    ]

    vertex_offset = 1
    for polygon_index, ring in enumerate(_footprint_rings_abs(footprint), start=1):
        lines.append(f"o footprint_{polygon_index:02d}")
        local = [(x - origin_x, y - origin_y) for x, y in ring]
        for x, y in local:
            lines.append(f"v {x:.6f} {y:.6f} 0.000000")
        indices = [str(vertex_offset + index) for index in range(len(local))]
        indices.append(str(vertex_offset))
        lines.append("l " + " ".join(indices))
        vertex_offset += len(local)

    for segment_index, segment in enumerate(topology["boundary_segments"], start=1):
        z_local = float(segment["z_abs"]) - ground_z
        lines.append(
            f"o boundary_{segment_index:04d}_p{segment['plane_a']:02d}_p{segment['plane_b']:02d}"
        )
        lines.append(
            f"# height_gap_m={float(segment['height_gap_m']):.4f}"
        )
        lines.append(
            f"v {float(segment['x0']):.6f} {float(segment['y0']):.6f} {z_local:.6f}"
        )
        lines.append(
            f"v {float(segment['x1']):.6f} {float(segment['y1']):.6f} {z_local:.6f}"
        )
        lines.append(f"l {vertex_offset} {vertex_offset + 1}")
        vertex_offset += 2

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure support-aware roof topology inside the authoritative footprint."
    )
    parser.add_argument("--lidar", type=Path, required=True)
    parser.add_argument("--roof-json", type=Path, required=True)
    parser.add_argument("--footprint-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-obj", type=Path)
    parser.add_argument("--classification", type=int, default=6)
    parser.add_argument("--all-classes", action="store_true")
    parser.add_argument("--residual-threshold-m", type=float)
    parser.add_argument("--min-height-m", type=float)
    parser.add_argument("--high-structure-min-height-m", type=float, default=22.0)
    parser.add_argument("--cell-size-m", type=float, default=0.5)
    parser.add_argument("--min-cell-points", type=int, default=3)
    parser.add_argument("--min-cell-purity", type=float, default=0.60)
    parser.add_argument("--continuous-gap-m", type=float, default=0.35)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        roof = _load_json(args.roof_json)
        footprint = _load_json(args.footprint_json)
        xyz = _load_las_xyz(
            args.lidar,
            None if args.all_classes else args.classification,
        )
        topology = analyze_topology_evidence(
            xyz,
            roof=roof,
            footprint=footprint,
            residual_threshold_m=args.residual_threshold_m,
            min_height_m=args.min_height_m,
            high_structure_min_height_m=args.high_structure_min_height_m,
            cell_size_m=args.cell_size_m,
            min_cell_points=args.min_cell_points,
            min_cell_purity=args.min_cell_purity,
            continuous_gap_m=args.continuous_gap_m,
        )
    except (OSError, ValueError, json.JSONDecodeError, laspy.errors.LaspyException) as exc:
        print(f"BatiForge roof topology analysis failed: {exc}")
        return 2

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(topology, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if args.output_obj:
        write_topology_boundary_obj(args.output_obj, topology, footprint)

    print(
        "roof topology: "
        f"main_candidates={topology['main_roof_candidate_count']} "
        f"assigned={topology['assigned_main_roof_point_count']} "
        f"assignment_ratio={topology['main_roof_assignment_ratio']:.3f} "
        f"cells={topology['resolved_cell_count']}/{topology['observed_cell_count']} "
        f"adjacencies={topology['adjacency_count']}"
    )
    print(f"json: {args.output_json}")
    if args.output_obj:
        print(f"diagnostic obj: {args.output_obj}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
