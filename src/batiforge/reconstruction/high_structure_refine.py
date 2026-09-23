from __future__ import annotations

import argparse
import json
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def _cluster_3d(points: np.ndarray, *, xy_cell_m: float, z_cell_m: float) -> np.ndarray:
    if len(points) == 0:
        return np.empty(0, dtype=np.int32)
    if xy_cell_m <= 0.0 or z_cell_m <= 0.0:
        raise ValueError("xy_cell_m and z_cell_m must be > 0")

    origin = np.min(points, axis=0)
    scaled = np.column_stack(
        (
            (points[:, 0] - origin[0]) / xy_cell_m,
            (points[:, 1] - origin[1]) / xy_cell_m,
            (points[:, 2] - origin[2]) / z_cell_m,
        )
    )
    cells = np.floor(scaled).astype(np.int64)
    unique_cells, inverse = np.unique(cells, axis=0, return_inverse=True)
    lookup = {
        (int(x), int(y), int(z)): index
        for index, (x, y, z) in enumerate(unique_cells)
    }
    labels = np.full(len(unique_cells), -1, dtype=np.int32)

    component = 0
    for start in range(len(unique_cells)):
        if labels[start] != -1:
            continue
        labels[start] = component
        queue: deque[int] = deque([start])
        while queue:
            current = queue.popleft()
            cx, cy, cz = unique_cells[current]
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        if dx == 0 and dy == 0 and dz == 0:
                            continue
                        neighbor = lookup.get((int(cx + dx), int(cy + dy), int(cz + dz)))
                        if neighbor is None or labels[neighbor] != -1:
                            continue
                        labels[neighbor] = component
                        queue.append(neighbor)
        component += 1

    return labels[inverse]


def _component_payload(
    component_id: int,
    parent_component_id: int,
    records: list[dict[str, Any]],
    *,
    roof_ceiling_m: float,
    global_ceiling_margin_m: float,
    min_vertical_span_m: float,
    min_median_excess_m: float,
) -> dict[str, Any]:
    xyz = np.asarray(
        [[float(r["x"]), float(r["y"]), float(r["z"])] for r in records],
        dtype=np.float64,
    )
    finite_excess = np.asarray(
        [
            float(r["excess_above_resolved_roof_m"])
            for r in records
            if r.get("excess_above_resolved_roof_m") is not None
        ],
        dtype=np.float64,
    )
    widths = np.ptp(xyz, axis=0)
    center = np.median(xyz, axis=0)
    max_above_ceiling = float(np.max(xyz[:, 2]) - roof_ceiling_m)
    median_excess = float(np.median(finite_excess)) if len(finite_excess) else None

    strong_global = max_above_ceiling >= global_ceiling_margin_m
    strong_vertical = (
        float(widths[2]) >= min_vertical_span_m
        and median_excess is not None
        and median_excess >= min_median_excess_m
    )
    if strong_global or strong_vertical:
        evidence_class = "strong_protrusion_candidate"
        reconstruction_gate = True
    elif median_excess is not None and median_excess >= min_median_excess_m:
        evidence_class = "local_protrusion_candidate"
        reconstruction_gate = False
    else:
        evidence_class = "thin_or_ambiguous_residual"
        reconstruction_gate = False

    return {
        "component_id": int(component_id),
        "parent_xy_component_id": int(parent_component_id),
        "point_count": int(len(records)),
        "evidence_class": evidence_class,
        "reconstruction_gate": reconstruction_gate,
        "local_center_xyz_m": [round(float(value), 4) for value in center],
        "local_bounds_m": {
            "min_x": round(float(np.min(xyz[:, 0])), 4),
            "max_x": round(float(np.max(xyz[:, 0])), 4),
            "min_y": round(float(np.min(xyz[:, 1])), 4),
            "max_y": round(float(np.max(xyz[:, 1])), 4),
            "min_z": round(float(np.min(xyz[:, 2])), 4),
            "max_z": round(float(np.max(xyz[:, 2])), 4),
            "width_x": round(float(widths[0]), 4),
            "depth_y": round(float(widths[1]), 4),
            "height_z": round(float(widths[2]), 4),
        },
        "height_above_ground_m": {
            "min": round(float(np.min(xyz[:, 2])), 4),
            "median": round(float(np.median(xyz[:, 2])), 4),
            "max": round(float(np.max(xyz[:, 2])), 4),
        },
        "height_above_main_roof_ceiling_m": {
            "max": round(max_above_ceiling, 4),
        },
        "excess_above_resolved_roof_m": {
            "available_point_count": int(len(finite_excess)),
            "min": round(float(np.min(finite_excess)), 4) if len(finite_excess) else None,
            "median": round(median_excess, 4) if median_excess is not None else None,
            "max": round(float(np.max(finite_excess)), 4) if len(finite_excess) else None,
        },
    }


def refine_high_structures(
    detected: dict[str, Any],
    *,
    xy_cell_m: float = 0.5,
    z_cell_m: float = 0.75,
    min_component_points: int = 6,
    global_ceiling_margin_m: float = 0.75,
    min_vertical_span_m: float = 0.8,
    min_median_excess_m: float = 0.8,
) -> dict[str, Any]:
    """Split XY-overmerged LiDAR residuals with 3D connectivity.

    The stage is building-agnostic. It preserves every sufficiently supported 3D
    component and only marks strong reconstruction candidates when the evidence is
    vertically substantial or rises above the validated main-roof ceiling.
    """

    if min_component_points < 1:
        raise ValueError("min_component_points must be >= 1")
    if global_ceiling_margin_m <= 0.0 or min_vertical_span_m <= 0.0:
        raise ValueError("evidence thresholds must be > 0")

    roof_ceiling_m = float(detected["main_roof_ceiling_height_m"])
    raw_records = detected.get("point_records", [])
    if not isinstance(raw_records, list):
        raise ValueError("point_records must be a list")

    by_parent: dict[int, list[dict[str, Any]]] = {}
    for record in raw_records:
        parent = int(record["component_id"])
        by_parent.setdefault(parent, []).append(record)

    components: list[dict[str, Any]] = []
    refined_records: list[dict[str, Any]] = []
    next_id = 1

    for parent_id in sorted(by_parent):
        records = by_parent[parent_id]
        xyz = np.asarray(
            [[float(r["x"]), float(r["y"]), float(r["z"])] for r in records],
            dtype=np.float64,
        )
        labels = _cluster_3d(xyz, xy_cell_m=xy_cell_m, z_cell_m=z_cell_m)
        for raw_label in sorted(set(int(value) for value in labels.tolist())):
            rows = np.flatnonzero(labels == raw_label)
            if len(rows) < min_component_points:
                continue
            subset = [records[int(row)] for row in rows]
            payload = _component_payload(
                next_id,
                parent_id,
                subset,
                roof_ceiling_m=roof_ceiling_m,
                global_ceiling_margin_m=global_ceiling_margin_m,
                min_vertical_span_m=min_vertical_span_m,
                min_median_excess_m=min_median_excess_m,
            )
            components.append(payload)
            for record in subset:
                copied = dict(record)
                copied["parent_xy_component_id"] = parent_id
                copied["component_id"] = next_id
                copied["evidence_class"] = payload["evidence_class"]
                refined_records.append(copied)
            next_id += 1

    components.sort(
        key=lambda item: (
            not bool(item["reconstruction_gate"]),
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
    for record in refined_records:
        record["component_id"] = id_remap[int(record["component_id"])]
    refined_records.sort(
        key=lambda item: (
            int(item["component_id"]),
            float(item["x"]),
            float(item["y"]),
            float(item["z"]),
        )
    )

    strong = [item for item in components if item["reconstruction_gate"]]
    return {
        "schema_version": 1,
        "method": "vertical-aware 3D refinement of roof-relative LiDAR residuals",
        "georeference": detected.get("georeference", {}),
        "source_detector_schema_version": detected.get("schema_version"),
        "main_roof_ceiling_height_m": roof_ceiling_m,
        "parameters": {
            "xy_cell_m": xy_cell_m,
            "z_cell_m": z_cell_m,
            "min_component_points": min_component_points,
            "global_ceiling_margin_m": global_ceiling_margin_m,
            "min_vertical_span_m": min_vertical_span_m,
            "min_median_excess_m": min_median_excess_m,
        },
        "input_point_record_count": len(raw_records),
        "input_xy_component_count": int(detected.get("component_count", 0)),
        "component_count": len(components),
        "strong_candidate_count": len(strong),
        "strong_candidate_point_count": int(sum(int(item["point_count"]) for item in strong)),
        "components": components,
        "point_records": refined_records,
    }


def write_ply(path: Path, result: dict[str, Any]) -> None:
    records = result.get("point_records", [])
    lines = [
        "ply",
        "format ascii 1.0",
        "comment BatiForge vertical-aware high-structure evidence",
        f"element vertex {len(records)}",
        "property float x",
        "property float y",
        "property float z",
        "property int component_id",
        "end_header",
    ]
    for record in records:
        lines.append(
            f"{float(record['x']):.6f} {float(record['y']):.6f} {float(record['z']):.6f} "
            f"{int(record['component_id'])}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_obj(path: Path, result: dict[str, Any]) -> None:
    lines = [
        "# BatiForge vertical-aware high-structure diagnostic OBJ",
        "# Bounding boxes only; NOT production geometry",
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
        lines.append(
            f"o high_structure_refined_{int(component['component_id']):02d}_"
            f"{component['evidence_class']}"
        )
        lines.extend(f"v {x:.6f} {y:.6f} {z:.6f}" for x, y, z in corners)
        for a, b in (
            (0, 1), (1, 2), (2, 3), (3, 0),
            (4, 5), (5, 6), (6, 7), (7, 4),
            (0, 4), (1, 5), (2, 6), (3, 7),
        ):
            lines.append(f"l {vertex_offset + a} {vertex_offset + b}")
        vertex_offset += 8
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Refine generic high-structure evidence with vertical-aware 3D connectivity."
    )
    parser.add_argument("--input-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-ply", type=Path)
    parser.add_argument("--output-obj", type=Path)
    parser.add_argument("--xy-cell-m", type=float, default=0.5)
    parser.add_argument("--z-cell-m", type=float, default=0.75)
    parser.add_argument("--min-component-points", type=int, default=6)
    parser.add_argument("--global-ceiling-margin-m", type=float, default=0.75)
    parser.add_argument("--min-vertical-span-m", type=float, default=0.8)
    parser.add_argument("--min-median-excess-m", type=float, default=0.8)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        detected = _load_json(args.input_json)
        result = refine_high_structures(
            detected,
            xy_cell_m=args.xy_cell_m,
            z_cell_m=args.z_cell_m,
            min_component_points=args.min_component_points,
            global_ceiling_margin_m=args.global_ceiling_margin_m,
            min_vertical_span_m=args.min_vertical_span_m,
            min_median_excess_m=args.min_median_excess_m,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"BatiForge high-structure refinement failed: {exc}")
        return 2

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if args.output_ply:
        write_ply(args.output_ply, result)
    if args.output_obj:
        write_obj(args.output_obj, result)

    print(
        "high-structure refine: "
        f"xy_components={result['input_xy_component_count']} "
        f"components_3d={result['component_count']} "
        f"strong={result['strong_candidate_count']}"
    )
    for component in result["components"]:
        bounds = component["local_bounds_m"]
        print(
            f"  #{component['component_id']}: {component['evidence_class']} "
            f"points={component['point_count']} "
            f"xy={bounds['width_x']:.2f}x{bounds['depth_y']:.2f}m "
            f"z={bounds['min_z']:.2f}..{bounds['max_z']:.2f}m"
        )
    print(f"json: {args.output_json}")
    if args.output_ply:
        print(f"ply: {args.output_ply}")
    if args.output_obj:
        print(f"diagnostic obj: {args.output_obj}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
