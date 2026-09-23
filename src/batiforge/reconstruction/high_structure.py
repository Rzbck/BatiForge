from __future__ import annotations

import argparse
import json
import math
from collections import deque
from pathlib import Path
from typing import Any

import laspy
import numpy as np

from .rnb_footprint import _points_in_ring
from .roof_regions import _plane_lookup


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


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
        xyz = xyz[np.asarray(las.classification) == classification]
    xyz = xyz[np.isfinite(xyz).all(axis=1)]
    if len(xyz) == 0:
        raise ValueError("no LiDAR points remain after filtering")
    return xyz


def _footprint_ring_local(footprint: dict[str, Any]) -> tuple[tuple[float, float], ...]:
    polygons = footprint.get("polygons_local_xy")
    if not isinstance(polygons, list) or len(polygons) != 1:
        raise ValueError("high-structure stage currently requires one simple footprint polygon")
    ring = polygons[0]
    if not isinstance(ring, list) or len(ring) < 3:
        raise ValueError("invalid local footprint polygon")
    return tuple((float(point[0]), float(point[1])) for point in ring)


def _validate_georeference(
    roof: dict[str, Any],
    refined: dict[str, Any],
    footprint: dict[str, Any],
) -> tuple[float, float, float, str, str]:
    roof_geo = roof.get("georeference")
    refined_geo = refined.get("georeference")
    if not isinstance(roof_geo, dict) or not isinstance(refined_geo, dict):
        raise ValueError("roof/refined JSON missing georeference")

    origin_x = float(roof_geo["origin_x"])
    origin_y = float(roof_geo["origin_y"])
    ground_z = float(roof_geo["ground_z"])
    crs = str(roof_geo["horizontal_crs"])
    datum = str(roof_geo["vertical_datum"])

    if abs(float(refined_geo["origin_x"]) - origin_x) > 1e-3:
        raise ValueError("refined origin_x mismatch")
    if abs(float(refined_geo["origin_y"]) - origin_y) > 1e-3:
        raise ValueError("refined origin_y mismatch")
    if abs(float(refined_geo["ground_z"]) - ground_z) > 1e-3:
        raise ValueError("refined ground_z mismatch")
    if str(refined_geo["horizontal_crs"]) != crs:
        raise ValueError("refined horizontal CRS mismatch")

    if "origin_x" in footprint and abs(float(footprint["origin_x"]) - origin_x) > 1e-3:
        raise ValueError("footprint origin_x mismatch")
    if "origin_y" in footprint and abs(float(footprint["origin_y"]) - origin_y) > 1e-3:
        raise ValueError("footprint origin_y mismatch")
    if "target_crs" in footprint and str(footprint["target_crs"]) != crs:
        raise ValueError("footprint CRS mismatch")

    return origin_x, origin_y, ground_z, crs, datum


def _expected_roof_surface(
    local_xy: np.ndarray,
    *,
    refined: dict[str, Any],
    planes: dict[int, tuple[float, float, float]],
) -> tuple[np.ndarray, np.ndarray]:
    expected_z_abs = np.full(len(local_xy), np.nan, dtype=np.float64)
    source_plane = np.full(len(local_xy), -1, dtype=np.int32)

    for region in refined.get("regions", []):
        vertices = region.get("vertices_local_xyz", [])
        if not isinstance(vertices, list) or len(vertices) < 3:
            continue
        plane_index = int(region["plane_index"])
        if plane_index not in planes:
            continue

        polygon = tuple((float(v[0]), float(v[1])) for v in vertices)
        xs = [p[0] for p in polygon]
        ys = [p[1] for p in polygon]
        candidate = np.flatnonzero(
            (local_xy[:, 0] >= min(xs) - 1e-9)
            & (local_xy[:, 0] <= max(xs) + 1e-9)
            & (local_xy[:, 1] >= min(ys) - 1e-9)
            & (local_xy[:, 1] <= max(ys) + 1e-9)
        )
        if not len(candidate):
            continue
        rows = candidate[_points_in_ring(local_xy[candidate], polygon)]
        if not len(rows):
            continue

        a, b, c = planes[plane_index]
        predicted = a * local_xy[rows, 0] + b * local_xy[rows, 1] + c
        empty = ~np.isfinite(expected_z_abs[rows])
        if np.any(empty):
            target = rows[empty]
            expected_z_abs[target] = predicted[empty]
            source_plane[target] = plane_index

        overlap = ~empty
        if np.any(overlap):
            target = rows[overlap]
            replacement = predicted[overlap] > expected_z_abs[target]
            target = target[replacement]
            if len(target):
                expected_z_abs[target] = predicted[overlap][replacement]
                source_plane[target] = plane_index

    return expected_z_abs, source_plane


def _cluster_seed_points(xy: np.ndarray, *, cell_size_m: float) -> np.ndarray:
    if len(xy) == 0:
        return np.empty(0, dtype=np.int32)
    if cell_size_m <= 0.0:
        raise ValueError("cluster_cell_m must be > 0")

    origin = np.min(xy, axis=0)
    cells = np.floor((xy - origin) / cell_size_m).astype(np.int64)
    unique_cells, inverse = np.unique(cells, axis=0, return_inverse=True)
    lookup = {(int(a), int(b)): i for i, (a, b) in enumerate(unique_cells)}
    labels = np.full(len(unique_cells), -1, dtype=np.int32)

    component = 0
    for start in range(len(unique_cells)):
        if labels[start] != -1:
            continue
        labels[start] = component
        queue: deque[int] = deque([start])
        while queue:
            current = queue.popleft()
            cx, cy = unique_cells[current]
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    neighbor = lookup.get((int(cx + dx), int(cy + dy)))
                    if neighbor is None or labels[neighbor] != -1:
                        continue
                    labels[neighbor] = component
                    queue.append(neighbor)
        component += 1

    return labels[inverse]


def _component_payload(
    component_id: int,
    rows: np.ndarray,
    *,
    local_xyz: np.ndarray,
    excess: np.ndarray,
    source_plane: np.ndarray,
    ground_z: float,
) -> dict[str, Any]:
    xyz = local_xyz[rows]
    finite_excess = excess[rows][np.isfinite(excess[rows])]
    plane_values = source_plane[rows]
    plane_values = plane_values[plane_values >= 0]

    return {
        "component_id": int(component_id),
        "point_count": int(len(rows)),
        "local_center_xyz_m": [
            round(float(np.median(xyz[:, 0])), 4),
            round(float(np.median(xyz[:, 1])), 4),
            round(float(np.median(xyz[:, 2])), 4),
        ],
        "local_bounds_m": {
            "min_x": round(float(np.min(xyz[:, 0])), 4),
            "max_x": round(float(np.max(xyz[:, 0])), 4),
            "min_y": round(float(np.min(xyz[:, 1])), 4),
            "max_y": round(float(np.max(xyz[:, 1])), 4),
            "min_z": round(float(np.min(xyz[:, 2])), 4),
            "max_z": round(float(np.max(xyz[:, 2])), 4),
            "width_x": round(float(np.ptp(xyz[:, 0])), 4),
            "depth_y": round(float(np.ptp(xyz[:, 1])), 4),
            "height_z": round(float(np.ptp(xyz[:, 2])), 4),
        },
        "height_above_ground_m": {
            "min": round(float(np.min(xyz[:, 2])), 4),
            "median": round(float(np.median(xyz[:, 2])), 4),
            "max": round(float(np.max(xyz[:, 2])), 4),
        },
        "excess_above_resolved_roof_m": {
            "available_point_count": int(len(finite_excess)),
            "min": round(float(np.min(finite_excess)), 4) if len(finite_excess) else None,
            "median": round(float(np.median(finite_excess)), 4) if len(finite_excess) else None,
            "max": round(float(np.max(finite_excess)), 4) if len(finite_excess) else None,
        },
        "supporting_plane_indices": sorted({int(value) for value in plane_values.tolist()}),
        "absolute_center_z_m": round(float(ground_z + np.median(xyz[:, 2])), 4),
    }


def detect_high_structures(
    xyz: np.ndarray,
    *,
    roof: dict[str, Any],
    refined: dict[str, Any],
    footprint: dict[str, Any],
    min_excess_m: float = 0.8,
    global_seed_excess_m: float = 0.75,
    cluster_cell_m: float = 0.5,
    min_component_points: int = 6,
) -> dict[str, Any]:
    """Detect compact LiDAR structures protruding above the reconstructed main roof.

    This detector is building-agnostic: it uses roof-relative excess, not an
    absolute building-specific height. The fallback only applies where the roof is
    unresolved and compares against the highest validated main-roof vertex.
    Components remain semantic-neutral candidates: no chimney/steeple/antenna
    label is invented here.
    """

    if min_excess_m <= 0.0 or global_seed_excess_m <= 0.0:
        raise ValueError("excess thresholds must be > 0")
    if min_component_points < 1:
        raise ValueError("min_component_points must be >= 1")

    origin_x, origin_y, ground_z, crs, datum = _validate_georeference(
        roof, refined, footprint
    )
    points = np.asarray(xyz, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("xyz must be an Nx3 array")
    points = points[np.isfinite(points).all(axis=1)]
    if len(points) == 0:
        raise ValueError("no finite LiDAR points")

    local_xyz = points.copy()
    local_xyz[:, 0] -= origin_x
    local_xyz[:, 1] -= origin_y
    local_xyz[:, 2] -= ground_z

    footprint_ring = _footprint_ring_local(footprint)
    inside = _points_in_ring(local_xyz[:, :2], footprint_ring)
    if not np.count_nonzero(inside):
        raise ValueError("no LiDAR points inside authoritative footprint")

    planes = _plane_lookup(roof)
    expected_abs, source_plane = _expected_roof_surface(
        local_xyz[:, :2], refined=refined, planes=planes
    )
    excess = points[:, 2] - expected_abs

    roof_vertex_heights = [
        float(vertex[2])
        for region in refined.get("regions", [])
        for vertex in region.get("vertices_local_xyz", [])
        if len(vertex) >= 3 and math.isfinite(float(vertex[2]))
    ]
    if not roof_vertex_heights:
        raise ValueError("refined roof contains no usable vertices")
    main_roof_ceiling_local = float(max(roof_vertex_heights))

    primary_seed = inside & np.isfinite(excess) & (excess >= min_excess_m)
    fallback_seed = (
        inside
        & ~np.isfinite(excess)
        & (local_xyz[:, 2] >= main_roof_ceiling_local + global_seed_excess_m)
    )
    seed_mask = primary_seed | fallback_seed
    seed_rows = np.flatnonzero(seed_mask)

    components: list[dict[str, Any]] = []
    point_records: list[dict[str, Any]] = []

    if len(seed_rows):
        labels = _cluster_seed_points(local_xyz[seed_rows, :2], cell_size_m=cluster_cell_m)
        next_component_id = 1
        for raw_label in sorted(set(int(value) for value in labels.tolist())):
            rows = seed_rows[labels == raw_label]
            if len(rows) < min_component_points:
                continue
            component_id = next_component_id
            next_component_id += 1
            components.append(
                _component_payload(
                    component_id,
                    rows,
                    local_xyz=local_xyz,
                    excess=excess,
                    source_plane=source_plane,
                    ground_z=ground_z,
                )
            )
            for row in rows:
                point_records.append(
                    {
                        "component_id": component_id,
                        "x": round(float(local_xyz[row, 0]), 5),
                        "y": round(float(local_xyz[row, 1]), 5),
                        "z": round(float(local_xyz[row, 2]), 5),
                        "height_above_ground_m": round(float(local_xyz[row, 2]), 5),
                        "excess_above_resolved_roof_m": (
                            round(float(excess[row]), 5)
                            if math.isfinite(float(excess[row]))
                            else None
                        ),
                        "supporting_plane_index": (
                            int(source_plane[row]) if source_plane[row] >= 0 else None
                        ),
                        "seed_source": (
                            "roof_relative" if primary_seed[row]
                            else "global_roof_ceiling_fallback"
                        ),
                    }
                )

    components.sort(
        key=lambda item: (
            -int(item["point_count"]),
            -float(item["height_above_ground_m"]["max"]),
            int(item["component_id"]),
        )
    )
    id_remap = {
        int(item["component_id"]): index + 1
        for index, item in enumerate(components)
    }
    for item in components:
        item["component_id"] = id_remap[int(item["component_id"])]
    for record in point_records:
        record["component_id"] = id_remap[int(record["component_id"])]
    point_records.sort(
        key=lambda item: (
            int(item["component_id"]),
            float(item["x"]), float(item["y"]), float(item["z"]),
        )
    )

    return {
        "schema_version": 1,
        "method": "roof-relative LiDAR high-structure detection",
        "georeference": {
            "origin_x": origin_x,
            "origin_y": origin_y,
            "ground_z": ground_z,
            "horizontal_crs": crs,
            "vertical_datum": datum,
            "local_axes": "X east / Y north / Z up",
        },
        "parameters": {
            "min_excess_m": min_excess_m,
            "global_seed_excess_m": global_seed_excess_m,
            "cluster_cell_m": cluster_cell_m,
            "min_component_points": min_component_points,
        },
        "source_point_count": int(len(points)),
        "inside_footprint_point_count": int(np.count_nonzero(inside)),
        "main_roof_ceiling_height_m": round(main_roof_ceiling_local, 4),
        "primary_seed_count": int(np.count_nonzero(primary_seed)),
        "fallback_seed_count": int(np.count_nonzero(fallback_seed)),
        "seed_point_count": int(len(seed_rows)),
        "component_count": len(components),
        "components": components,
        "point_records": point_records,
    }


def write_high_structure_ply(path: Path, result: dict[str, Any]) -> None:
    records = result.get("point_records", [])
    lines = [
        "ply",
        "format ascii 1.0",
        "comment BatiForge roof-relative high-structure evidence; X east, Y north, Z up",
        f"element vertex {len(records)}",
        "property float x",
        "property float y",
        "property float z",
        "property int component_id",
        "property float height_above_ground_m",
        "property float excess_above_resolved_roof_m",
        "end_header",
    ]
    for record in records:
        excess = record["excess_above_resolved_roof_m"]
        excess_value = float(excess) if excess is not None else -9999.0
        lines.append(
            f"{float(record['x']):.6f} {float(record['y']):.6f} {float(record['z']):.6f} "
            f"{int(record['component_id'])} {float(record['height_above_ground_m']):.6f} "
            f"{excess_value:.6f}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_high_structure_obj(path: Path, result: dict[str, Any]) -> None:
    """Write diagnostic component bounding boxes, not production geometry."""

    lines = [
        "# BatiForge high-structure diagnostic OBJ",
        "# IMPORTANT: component bounding boxes only; NOT production reconstruction",
        "# axes: X east / Y north / Z up",
    ]
    vertex_offset = 1
    for component in result.get("components", []):
        bounds = component["local_bounds_m"]
        x0, x1 = float(bounds["min_x"]), float(bounds["max_x"])
        y0, y1 = float(bounds["min_y"]), float(bounds["max_y"])
        z0, z1 = float(bounds["min_z"]), float(bounds["max_z"])
        corners = [
            (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
            (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
        ]
        lines.append(f"o high_structure_candidate_{int(component['component_id']):02d}")
        lines.append(
            f"# points={int(component['point_count'])} "
            f"max_height_m={float(component['height_above_ground_m']['max']):.4f}"
        )
        lines.extend(f"v {x:.6f} {y:.6f} {z:.6f}" for x, y, z in corners)
        edges = (
            (0, 1), (1, 2), (2, 3), (3, 0),
            (4, 5), (5, 6), (6, 7), (7, 4),
            (0, 4), (1, 5), (2, 6), (3, 7),
        )
        for a, b in edges:
            lines.append(f"l {vertex_offset + a} {vertex_offset + b}")
        vertex_offset += 8
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Detect generic LiDAR high structures relative to the reconstructed main roof."
    )
    parser.add_argument("--lidar", type=Path, required=True)
    parser.add_argument("--roof-json", type=Path, required=True)
    parser.add_argument("--refined-json", type=Path, required=True)
    parser.add_argument("--footprint-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-ply", type=Path)
    parser.add_argument("--output-obj", type=Path)
    parser.add_argument("--classification", type=int, default=6)
    parser.add_argument("--all-classes", action="store_true")
    parser.add_argument("--min-excess-m", type=float, default=0.8)
    parser.add_argument("--global-seed-excess-m", type=float, default=0.75)
    parser.add_argument("--cluster-cell-m", type=float, default=0.5)
    parser.add_argument("--min-component-points", type=int, default=6)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        roof = _load_json(args.roof_json)
        refined = _load_json(args.refined_json)
        footprint = _load_json(args.footprint_json)
        xyz = _load_las_xyz(
            args.lidar,
            None if args.all_classes else args.classification,
        )
        result = detect_high_structures(
            xyz,
            roof=roof,
            refined=refined,
            footprint=footprint,
            min_excess_m=args.min_excess_m,
            global_seed_excess_m=args.global_seed_excess_m,
            cluster_cell_m=args.cluster_cell_m,
            min_component_points=args.min_component_points,
        )
    except (OSError, ValueError, json.JSONDecodeError, laspy.errors.LaspyException) as exc:
        print(f"BatiForge high-structure detection failed: {exc}")
        return 2

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if args.output_ply:
        write_high_structure_ply(args.output_ply, result)
    if args.output_obj:
        write_high_structure_obj(args.output_obj, result)

    print(
        "high structures: "
        f"inside={result['inside_footprint_point_count']} "
        f"seeds={result['seed_point_count']} "
        f"components={result['component_count']} "
        f"roof_ceiling={result['main_roof_ceiling_height_m']:.2f}m"
    )
    for component in result["components"]:
        bounds = component["local_bounds_m"]
        print(
            f"  #{component['component_id']}: points={component['point_count']} "
            f"xy={bounds['width_x']:.2f}x{bounds['depth_y']:.2f}m "
            f"z={component['height_above_ground_m']['min']:.2f}"
            f"..{component['height_above_ground_m']['max']:.2f}m"
        )
    print(f"json: {args.output_json}")
    if args.output_ply:
        print(f"ply: {args.output_ply}")
    if args.output_obj:
        print(f"diagnostic obj: {args.output_obj}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
