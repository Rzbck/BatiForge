from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def _validate_frames(
    topology: dict[str, Any],
    roof: dict[str, Any],
    footprint: dict[str, Any],
) -> tuple[float, float, float]:
    topo_geo = topology.get("georeference")
    roof_geo = roof.get("georeference")
    if not isinstance(topo_geo, dict) or not isinstance(roof_geo, dict):
        raise ValueError("topology/roof georeference missing")

    origin_x = float(roof_geo["origin_x"])
    origin_y = float(roof_geo["origin_y"])
    ground_z = float(roof_geo["ground_z"])

    checks = (
        (float(topo_geo["origin_x"]), origin_x, "topology origin_x"),
        (float(topo_geo["origin_y"]), origin_y, "topology origin_y"),
        (float(topo_geo["ground_z"]), ground_z, "topology ground_z"),
        (float(footprint["origin_x"]), origin_x, "footprint origin_x"),
        (float(footprint["origin_y"]), origin_y, "footprint origin_y"),
    )
    for actual, expected, label in checks:
        if abs(actual - expected) > 1e-3:
            raise ValueError(f"frame mismatch for {label}: {actual} != {expected}")

    roof_crs = str(roof_geo.get("horizontal_crs", ""))
    topo_crs = str(topo_geo.get("horizontal_crs", ""))
    footprint_crs = str(footprint.get("target_crs", ""))
    if not roof_crs or roof_crs != topo_crs or roof_crs != footprint_crs:
        raise ValueError(
            f"CRS mismatch: roof={roof_crs!r}, topology={topo_crs!r}, footprint={footprint_crs!r}"
        )
    return origin_x, origin_y, ground_z


def _local_rings(footprint: dict[str, Any]) -> tuple[tuple[tuple[float, float], ...], ...]:
    raw = footprint.get("polygons_local_xy")
    if not isinstance(raw, list) or not raw:
        raise ValueError("footprint JSON has no polygons_local_xy")
    rings: list[tuple[tuple[float, float], ...]] = []
    for polygon in raw:
        if not isinstance(polygon, list) or len(polygon) < 3:
            raise ValueError("invalid local footprint polygon")
        rings.append(tuple((float(point[0]), float(point[1])) for point in polygon))
    return tuple(rings)


def _plane_lookup(roof: dict[str, Any]) -> dict[int, tuple[float, float, float]]:
    raw = roof.get("planes")
    if not isinstance(raw, list) or not raw:
        raise ValueError("roof analysis has no planes")
    lookup: dict[int, tuple[float, float, float]] = {}
    for plane in raw:
        index = int(plane["index"])
        if index in lookup:
            raise ValueError(f"duplicate roof plane index: {index}")
        lookup[index] = (float(plane["a"]), float(plane["b"]), float(plane["c"]))
    return lookup


def _line_from_planes(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
) -> tuple[float, float, float, tuple[float, float], tuple[float, float]]:
    a = first[0] - second[0]
    b = first[1] - second[1]
    c = first[2] - second[2]
    norm = math.hypot(a, b)
    if norm <= 1e-12:
        raise ValueError("roof planes are parallel in XY and have no finite equality line")
    a /= norm
    b /= norm
    c /= norm
    base = (-a * c, -b * c)
    direction = (-b, a)
    return a, b, c, base, direction


def _line_t(point: tuple[float, float], base: tuple[float, float], direction: tuple[float, float]) -> float:
    return (point[0] - base[0]) * direction[0] + (point[1] - base[1]) * direction[1]


def _line_point(t: float, base: tuple[float, float], direction: tuple[float, float]) -> tuple[float, float]:
    return (base[0] + t * direction[0], base[1] + t * direction[1])


def _point_in_ring(point: tuple[float, float], ring: tuple[tuple[float, float], ...]) -> bool:
    x, y = point
    inside = False
    xj, yj = ring[-1]
    for xi, yi in ring:
        crosses = (yi > y) != (yj > y)
        if crosses:
            x_cross = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_cross:
                inside = not inside
        xj, yj = xi, yi
    return inside


def _unique_sorted(values: list[float], tolerance: float = 1e-8) -> list[float]:
    ordered = sorted(values)
    result: list[float] = []
    for value in ordered:
        if not result or abs(value - result[-1]) > tolerance:
            result.append(value)
    return result


def _line_intervals_in_ring(
    *,
    line_a: float,
    line_b: float,
    line_c: float,
    base: tuple[float, float],
    direction: tuple[float, float],
    ring: tuple[tuple[float, float], ...],
) -> list[tuple[float, float]]:
    intersections: list[float] = []
    epsilon = 1e-10

    for index, start in enumerate(ring):
        end = ring[(index + 1) % len(ring)]
        s0 = line_a * start[0] + line_b * start[1] + line_c
        s1 = line_a * end[0] + line_b * end[1] + line_c

        if abs(s0) <= epsilon:
            intersections.append(_line_t(start, base, direction))
        if abs(s1) <= epsilon:
            intersections.append(_line_t(end, base, direction))

        if s0 * s1 < -(epsilon * epsilon):
            u = s0 / (s0 - s1)
            point = (
                start[0] + u * (end[0] - start[0]),
                start[1] + u * (end[1] - start[1]),
            )
            intersections.append(_line_t(point, base, direction))

    ts = _unique_sorted(intersections)
    intervals: list[tuple[float, float]] = []
    for left, right in zip(ts, ts[1:]):
        if right - left <= 1e-8:
            continue
        midpoint = _line_point((left + right) * 0.5, base, direction)
        if _point_in_ring(midpoint, ring):
            intervals.append((left, right))
    return intervals


def _distance_point_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    vx = end[0] - start[0]
    vy = end[1] - start[1]
    length_sq = vx * vx + vy * vy
    if length_sq <= 1e-20:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    u = ((point[0] - start[0]) * vx + (point[1] - start[1]) * vy) / length_sq
    u = min(1.0, max(0.0, u))
    closest = (start[0] + u * vx, start[1] + u * vy)
    return math.hypot(point[0] - closest[0], point[1] - closest[1])


def _distance_to_footprint_boundary(
    point: tuple[float, float],
    rings: tuple[tuple[tuple[float, float], ...], ...],
) -> float:
    best = float("inf")
    for ring in rings:
        for index, start in enumerate(ring):
            end = ring[(index + 1) % len(ring)]
            best = min(best, _distance_point_segment(point, start, end))
    return best


def _boundary_midpoints(
    topology: dict[str, Any],
    plane_a: int,
    plane_b: int,
) -> list[tuple[float, float]]:
    pair = tuple(sorted((plane_a, plane_b)))
    result: list[tuple[float, float]] = []
    for segment in topology.get("boundary_segments", []):
        segment_pair = tuple(sorted((int(segment["plane_a"]), int(segment["plane_b"]))))
        if segment_pair != pair:
            continue
        result.append(
            (
                (float(segment["x0"]) + float(segment["x1"])) * 0.5,
                (float(segment["y0"]) + float(segment["y1"])) * 0.5,
            )
        )
    return result


def build_vector_intersections(
    *,
    topology: dict[str, Any],
    roof: dict[str, Any],
    footprint: dict[str, Any],
    min_boundary_length_m: float = 1.0,
    support_margin_m: float = 0.75,
    footprint_touch_tolerance_m: float = 0.15,
) -> dict[str, Any]:
    """Convert only well-supported continuous plane intersections to vector segments.

    Observed grid boundaries provide support extent only. Final segment geometry is
    analytic: it lies on the exact equality line of the two fitted roof planes and
    is clipped to the authoritative footprint. Height-step candidates, unresolved
    cells and the separate high structure are deliberately not converted to roof
    faces here.
    """

    if min_boundary_length_m <= 0.0:
        raise ValueError("min_boundary_length_m must be > 0")
    if support_margin_m < 0.0:
        raise ValueError("support_margin_m must be >= 0")
    if footprint_touch_tolerance_m < 0.0:
        raise ValueError("footprint_touch_tolerance_m must be >= 0")

    origin_x, origin_y, ground_z = _validate_frames(topology, roof, footprint)
    rings = _local_rings(footprint)
    planes = _plane_lookup(roof)

    vector_edges: list[dict[str, Any]] = []
    skipped_short = 0
    skipped_no_support = 0
    skipped_no_clip = 0
    continuous_seen = 0

    height_step_pairs = [
        {
            "plane_a": int(item["plane_a"]),
            "plane_b": int(item["plane_b"]),
            "approx_boundary_length_m": float(item["approx_boundary_length_m"]),
            "median_height_gap_m": float(item["median_height_gap_m"]),
        }
        for item in topology.get("adjacencies", [])
        if item.get("relation") == "height_step_or_overlap_candidate"
    ]

    for adjacency in topology.get("adjacencies", []):
        if adjacency.get("relation") != "continuous_intersection_candidate":
            continue
        continuous_seen += 1

        measured_length = float(adjacency["approx_boundary_length_m"])
        if measured_length < min_boundary_length_m:
            skipped_short += 1
            continue

        plane_a = int(adjacency["plane_a"])
        plane_b = int(adjacency["plane_b"])
        if plane_a not in planes or plane_b not in planes:
            raise ValueError(f"topology references unknown roof planes: {plane_a}, {plane_b}")

        midpoints = _boundary_midpoints(topology, plane_a, plane_b)
        if not midpoints:
            skipped_no_support += 1
            continue

        line_a, line_b, line_c, base, direction = _line_from_planes(
            planes[plane_a], planes[plane_b]
        )
        support_t = [_line_t(point, base, direction) for point in midpoints]
        support_min = min(support_t) - support_margin_m
        support_max = max(support_t) + support_margin_m

        footprint_intervals: list[tuple[float, float]] = []
        for ring in rings:
            footprint_intervals.extend(
                _line_intervals_in_ring(
                    line_a=line_a,
                    line_b=line_b,
                    line_c=line_c,
                    base=base,
                    direction=direction,
                    ring=ring,
                )
            )

        candidates: list[tuple[float, float]] = []
        for left, right in footprint_intervals:
            clipped_left = max(left, support_min)
            clipped_right = min(right, support_max)
            if clipped_right - clipped_left > 1e-6:
                candidates.append((clipped_left, clipped_right))

        if not candidates:
            skipped_no_clip += 1
            continue

        start_t, end_t = max(candidates, key=lambda interval: interval[1] - interval[0])
        start_xy = _line_point(start_t, base, direction)
        end_xy = _line_point(end_t, base, direction)

        first = planes[plane_a]
        second = planes[plane_b]

        def z_at(point: tuple[float, float]) -> tuple[float, float]:
            z_a = first[0] * point[0] + first[1] * point[1] + first[2]
            z_b = second[0] * point[0] + second[1] * point[1] + second[2]
            return (z_a + z_b) * 0.5, abs(z_a - z_b)

        start_z_abs, start_gap = z_at(start_xy)
        end_z_abs, end_gap = z_at(end_xy)
        if max(start_gap, end_gap) > 1e-5:
            raise ValueError("analytic vector endpoint is not on the plane equality line")

        start_boundary_distance = _distance_to_footprint_boundary(start_xy, rings)
        end_boundary_distance = _distance_to_footprint_boundary(end_xy, rings)

        vector_edges.append(
            {
                "index": len(vector_edges) + 1,
                "plane_a": plane_a,
                "plane_b": plane_b,
                "relation": "continuous_intersection_vector",
                "measured_boundary_length_m": round(measured_length, 4),
                "support_midpoint_count": len(midpoints),
                "support_span_m": round(max(support_t) - min(support_t), 4),
                "vector_length_m": round(end_t - start_t, 4),
                "median_height_gap_m": float(adjacency["median_height_gap_m"]),
                "p95_height_gap_m": float(adjacency["p95_height_gap_m"]),
                "median_distance_to_plane_equality_line_m": adjacency.get(
                    "median_distance_to_plane_equality_line_m"
                ),
                "equality_line_local": {
                    "a": round(line_a, 10),
                    "b": round(line_b, 10),
                    "c": round(line_c, 10),
                },
                "start_local_xyz": [
                    round(start_xy[0], 5),
                    round(start_xy[1], 5),
                    round(start_z_abs - ground_z, 5),
                ],
                "end_local_xyz": [
                    round(end_xy[0], 5),
                    round(end_xy[1], 5),
                    round(end_z_abs - ground_z, 5),
                ],
                "start_distance_to_footprint_boundary_m": round(start_boundary_distance, 4),
                "end_distance_to_footprint_boundary_m": round(end_boundary_distance, 4),
                "start_touches_footprint": start_boundary_distance <= footprint_touch_tolerance_m,
                "end_touches_footprint": end_boundary_distance <= footprint_touch_tolerance_m,
            }
        )

    return {
        "schema_version": 1,
        "method": "analytic plane intersections bounded by observed LiDAR support and authoritative footprint",
        "georeference": {
            "origin_x": origin_x,
            "origin_y": origin_y,
            "ground_z": ground_z,
            "horizontal_crs": roof["georeference"]["horizontal_crs"],
            "vertical_datum": roof["georeference"]["vertical_datum"],
            "local_axes": "X east / Y north / Z up",
        },
        "parameters": {
            "min_boundary_length_m": min_boundary_length_m,
            "support_margin_m": support_margin_m,
            "footprint_touch_tolerance_m": footprint_touch_tolerance_m,
        },
        "continuous_candidate_count": continuous_seen,
        "vector_edge_count": len(vector_edges),
        "skipped": {
            "short_support": skipped_short,
            "missing_boundary_support": skipped_no_support,
            "no_supported_footprint_clip": skipped_no_clip,
        },
        "height_step_pair_count": len(height_step_pairs),
        "height_step_pairs": height_step_pairs,
        "high_structure_point_count": int(topology.get("high_structure_point_count", 0)),
        "vector_edges": vector_edges,
    }


def write_vector_obj(
    path: Path,
    vectors: dict[str, Any],
    footprint: dict[str, Any],
) -> None:
    georef = vectors["georeference"]
    lines = [
        "# BatiForge analytic roof-vector diagnostic OBJ",
        "# IMPORTANT: vector skeleton only; not a production watertight mesh",
        f"# horizontal_crs={georef['horizontal_crs']}",
        f"# vertical_datum={georef['vertical_datum']}",
        f"# origin_x={float(georef['origin_x']):.6f}",
        f"# origin_y={float(georef['origin_y']):.6f}",
        f"# ground_z={float(georef['ground_z']):.6f}",
    ]

    vertex_offset = 1
    for polygon_index, ring in enumerate(_local_rings(footprint), start=1):
        lines.append(f"o footprint_{polygon_index:02d}")
        for x, y in ring:
            lines.append(f"v {x:.6f} {y:.6f} 0.000000")
        indices = [str(vertex_offset + index) for index in range(len(ring))]
        indices.append(str(vertex_offset))
        lines.append("l " + " ".join(indices))
        vertex_offset += len(ring)

    for edge in vectors["vector_edges"]:
        start = edge["start_local_xyz"]
        end = edge["end_local_xyz"]
        lines.append(
            f"o roof_vector_{int(edge['index']):02d}_p{int(edge['plane_a']):02d}_p{int(edge['plane_b']):02d}"
        )
        lines.append(
            f"# measured_boundary_length_m={float(edge['measured_boundary_length_m']):.4f} "
            f"vector_length_m={float(edge['vector_length_m']):.4f}"
        )
        lines.append(f"v {float(start[0]):.6f} {float(start[1]):.6f} {float(start[2]):.6f}")
        lines.append(f"v {float(end[0]):.6f} {float(end[1]):.6f} {float(end[2]):.6f}")
        lines.append(f"l {vertex_offset} {vertex_offset + 1}")
        vertex_offset += 2

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build conservative analytic roof-intersection vectors from validated topology evidence."
    )
    parser.add_argument("--topology-json", type=Path, required=True)
    parser.add_argument("--roof-json", type=Path, required=True)
    parser.add_argument("--footprint-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-obj", type=Path)
    parser.add_argument("--min-boundary-length-m", type=float, default=1.0)
    parser.add_argument("--support-margin-m", type=float, default=0.75)
    parser.add_argument("--footprint-touch-tolerance-m", type=float, default=0.15)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        topology = _load_json(args.topology_json)
        roof = _load_json(args.roof_json)
        footprint = _load_json(args.footprint_json)
        vectors = build_vector_intersections(
            topology=topology,
            roof=roof,
            footprint=footprint,
            min_boundary_length_m=args.min_boundary_length_m,
            support_margin_m=args.support_margin_m,
            footprint_touch_tolerance_m=args.footprint_touch_tolerance_m,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"BatiForge roof vectorization failed: {exc}")
        return 2

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(vectors, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if args.output_obj:
        write_vector_obj(args.output_obj, vectors, footprint)

    print(
        "roof vectors: "
        f"continuous={vectors['continuous_candidate_count']} "
        f"accepted={vectors['vector_edge_count']} "
        f"height_steps={vectors['height_step_pair_count']}"
    )
    print(f"json: {args.output_json}")
    if args.output_obj:
        print(f"diagnostic obj: {args.output_obj}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
