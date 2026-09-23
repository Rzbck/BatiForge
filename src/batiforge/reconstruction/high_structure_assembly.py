from __future__ import annotations

import argparse
import json
from collections import deque
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def _bounds(component: dict[str, Any]) -> tuple[float, float, float, float, float, float]:
    box = component.get("local_bounds_m")
    if not isinstance(box, dict):
        raise ValueError("component missing local_bounds_m")
    return (
        float(box["min_x"]),
        float(box["max_x"]),
        float(box["min_y"]),
        float(box["max_y"]),
        float(box["min_z"]),
        float(box["max_z"]),
    )


def _xy_overlap_ratio(a: dict[str, Any], b: dict[str, Any]) -> float:
    ax0, ax1, ay0, ay1, _, _ = _bounds(a)
    bx0, bx1, by0, by1, _, _ = _bounds(b)
    ix = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0.0, min(ay1, by1) - max(ay0, by0))
    intersection = ix * iy
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    denom = min(area_a, area_b)
    return intersection / denom if denom > 0.0 else 0.0


def _vertical_gap_m(a: dict[str, Any], b: dict[str, Any]) -> float:
    *_, az0, az1 = _bounds(a)
    *_, bz0, bz1 = _bounds(b)
    if az1 < bz0:
        return bz0 - az1
    if bz1 < az0:
        return az0 - bz1
    return 0.0


def assemble_high_structures(
    refined: dict[str, Any],
    *,
    min_xy_overlap_ratio: float = 0.65,
    max_vertical_gap_m: float = 1.75,
) -> dict[str, Any]:
    """Assemble vertically split strong evidence without erasing raw components.

    The 3D refinement stage deliberately separates disconnected vertical evidence.
    A sparse LiDAR return can therefore split one physical roof protrusion into two
    stacked components. This stage reconnects only strong components that come from
    the same original XY component, substantially overlap in XY, and are separated
    by a bounded vertical evidence gap. The gap is recorded explicitly; it is not
    silently filled or claimed as measured geometry.
    """

    if not 0.0 <= min_xy_overlap_ratio <= 1.0:
        raise ValueError("min_xy_overlap_ratio must be between 0 and 1")
    if max_vertical_gap_m < 0.0:
        raise ValueError("max_vertical_gap_m must be >= 0")

    components = refined.get("components", [])
    records = refined.get("point_records", [])
    if not isinstance(components, list) or not isinstance(records, list):
        raise ValueError("components and point_records must be lists")

    strong = [item for item in components if bool(item.get("reconstruction_gate"))]
    residual = [item for item in components if not bool(item.get("reconstruction_gate"))]
    by_id = {int(item["component_id"]): item for item in strong}
    ids = sorted(by_id)

    adjacency: dict[int, set[int]] = {component_id: set() for component_id in ids}
    links: list[dict[str, Any]] = []
    for index, left_id in enumerate(ids):
        left = by_id[left_id]
        for right_id in ids[index + 1 :]:
            right = by_id[right_id]
            if int(left.get("parent_xy_component_id", -1)) != int(
                right.get("parent_xy_component_id", -2)
            ):
                continue
            overlap = _xy_overlap_ratio(left, right)
            gap = _vertical_gap_m(left, right)
            if overlap < min_xy_overlap_ratio or gap > max_vertical_gap_m:
                continue
            adjacency[left_id].add(right_id)
            adjacency[right_id].add(left_id)
            links.append(
                {
                    "component_a": left_id,
                    "component_b": right_id,
                    "xy_overlap_ratio": round(overlap, 6),
                    "vertical_gap_m": round(gap, 4),
                }
            )

    groups: list[list[int]] = []
    visited: set[int] = set()
    for start in ids:
        if start in visited:
            continue
        queue: deque[int] = deque([start])
        visited.add(start)
        group: list[int] = []
        while queue:
            current = queue.popleft()
            group.append(current)
            for neighbor in sorted(adjacency[current]):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                queue.append(neighbor)
        groups.append(sorted(group))

    record_by_component: dict[int, list[dict[str, Any]]] = {}
    for record in records:
        component_id = int(record["component_id"])
        record_by_component.setdefault(component_id, []).append(record)

    assemblies: list[dict[str, Any]] = []
    output_records: list[dict[str, Any]] = []
    for assembly_id, member_ids in enumerate(groups, start=1):
        members = [by_id[item] for item in member_ids]
        boxes = [_bounds(item) for item in members]
        x0 = min(item[0] for item in boxes)
        x1 = max(item[1] for item in boxes)
        y0 = min(item[2] for item in boxes)
        y1 = max(item[3] for item in boxes)
        z0 = min(item[4] for item in boxes)
        z1 = max(item[5] for item in boxes)

        ordered = sorted(members, key=lambda item: _bounds(item)[4])
        vertical_gaps: list[float] = []
        for lower, upper in zip(ordered, ordered[1:], strict=False):
            vertical_gaps.append(_vertical_gap_m(lower, upper))

        member_records = [
            record
            for component_id in member_ids
            for record in record_by_component.get(component_id, [])
        ]
        for record in member_records:
            copied = dict(record)
            copied["assembly_id"] = assembly_id
            output_records.append(copied)

        assemblies.append(
            {
                "assembly_id": assembly_id,
                "member_component_ids": member_ids,
                "member_count": len(member_ids),
                "parent_xy_component_ids": sorted(
                    {int(item.get("parent_xy_component_id", -1)) for item in members}
                ),
                "point_count": len(member_records),
                "reconstruction_gate": True,
                "evidence_class": "strong_structure_assembly",
                "local_bounds_m": {
                    "min_x": round(x0, 4),
                    "max_x": round(x1, 4),
                    "min_y": round(y0, 4),
                    "max_y": round(y1, 4),
                    "min_z": round(z0, 4),
                    "max_z": round(z1, 4),
                    "width_x": round(x1 - x0, 4),
                    "depth_y": round(y1 - y0, 4),
                    "height_z": round(z1 - z0, 4),
                },
                "observed_vertical_gaps_m": [round(value, 4) for value in vertical_gaps],
                "max_observed_vertical_gap_m": round(max(vertical_gaps), 4)
                if vertical_gaps
                else 0.0,
                "evidence_gap_is_inferred": any(value > 0.0 for value in vertical_gaps),
            }
        )

    output_records.sort(
        key=lambda item: (
            int(item["assembly_id"]),
            int(item["component_id"]),
            float(item["x"]),
            float(item["y"]),
            float(item["z"]),
        )
    )
    assemblies.sort(key=lambda item: (-int(item["point_count"]), int(item["assembly_id"])))
    assembly_id_remap = {
        int(item["assembly_id"]): index + 1 for index, item in enumerate(assemblies)
    }
    for item in assemblies:
        item["assembly_id"] = assembly_id_remap[int(item["assembly_id"])]
    for record in output_records:
        record["assembly_id"] = assembly_id_remap[int(record["assembly_id"])]

    return {
        "schema_version": 1,
        "method": "vertical evidence-gap assembly of strong high-structure components",
        "georeference": refined.get("georeference", {}),
        "source_refinement_schema_version": refined.get("schema_version"),
        "parameters": {
            "min_xy_overlap_ratio": min_xy_overlap_ratio,
            "max_vertical_gap_m": max_vertical_gap_m,
            "same_parent_xy_component_required": True,
        },
        "input_component_count": len(components),
        "strong_input_component_count": len(strong),
        "residual_component_count": len(residual),
        "assembly_count": len(assemblies),
        "merged_assembly_count": sum(1 for item in assemblies if int(item["member_count"]) > 1),
        "link_count": len(links),
        "links": links,
        "assemblies": assemblies,
        "residual_components": residual,
        "point_records": output_records,
    }


def write_ply(path: Path, result: dict[str, Any]) -> None:
    records = result.get("point_records", [])
    lines = [
        "ply",
        "format ascii 1.0",
        "comment BatiForge assembled high-structure evidence; gaps remain explicit",
        f"element vertex {len(records)}",
        "property float x",
        "property float y",
        "property float z",
        "property int assembly_id",
        "property int source_component_id",
        "end_header",
    ]
    for record in records:
        lines.append(
            f"{float(record['x']):.6f} {float(record['y']):.6f} {float(record['z']):.6f} "
            f"{int(record['assembly_id'])} {int(record['component_id'])}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_obj(path: Path, result: dict[str, Any]) -> None:
    lines = [
        "# BatiForge assembled high-structure diagnostic OBJ",
        "# One box per assembled candidate; NOT production geometry",
        "# axes: X east / Y north / Z up",
    ]
    vertex_offset = 1
    for assembly in result.get("assemblies", []):
        box = assembly["local_bounds_m"]
        x0, x1 = float(box["min_x"]), float(box["max_x"])
        y0, y1 = float(box["min_y"]), float(box["max_y"])
        z0, z1 = float(box["min_z"]), float(box["max_z"])
        corners = [
            (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
            (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
        ]
        lines.append(f"o high_structure_assembly_{int(assembly['assembly_id']):02d}")
        lines.append(
            f"# members={','.join(str(value) for value in assembly['member_component_ids'])} "
            f"points={int(assembly['point_count'])} "
            f"max_evidence_gap_m={float(assembly['max_observed_vertical_gap_m']):.4f}"
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
        description="Assemble vertically split strong high-structure LiDAR evidence."
    )
    parser.add_argument("--input-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-ply", type=Path)
    parser.add_argument("--output-obj", type=Path)
    parser.add_argument("--min-xy-overlap-ratio", type=float, default=0.65)
    parser.add_argument("--max-vertical-gap-m", type=float, default=1.75)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        refined = _load_json(args.input_json)
        result = assemble_high_structures(
            refined,
            min_xy_overlap_ratio=args.min_xy_overlap_ratio,
            max_vertical_gap_m=args.max_vertical_gap_m,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"BatiForge high-structure assembly failed: {exc}")
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
        "high-structure assembly: "
        f"strong_components={result['strong_input_component_count']} "
        f"assemblies={result['assembly_count']} merged={result['merged_assembly_count']}"
    )
    for assembly in result["assemblies"]:
        box = assembly["local_bounds_m"]
        print(
            f"  #{assembly['assembly_id']}: members={assembly['member_component_ids']} "
            f"points={assembly['point_count']} "
            f"xy={box['width_x']:.2f}x{box['depth_y']:.2f}m "
            f"z={box['min_z']:.2f}..{box['max_z']:.2f}m "
            f"gap={assembly['max_observed_vertical_gap_m']:.2f}m"
        )
    print(f"json: {args.output_json}")
    if args.output_ply:
        print(f"ply: {args.output_ply}")
    if args.output_obj:
        print(f"diagnostic obj: {args.output_obj}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
