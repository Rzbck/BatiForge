from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from .high_structure_mesh import (
    _adaptive_quantile_sections,
    _fixed_section_records,
    _load_json,
    build_high_structure_mesh,
    write_composite_obj,
    write_high_structure_obj,
)


def _bbox_overlap_ratio(a: dict[str, Any], b: dict[str, Any]) -> float:
    ax = [float(point[0]) for point in a["ring_xy"]]
    ay = [float(point[1]) for point in a["ring_xy"]]
    bx = [float(point[0]) for point in b["ring_xy"]]
    by = [float(point[1]) for point in b["ring_xy"]]
    aminx, amaxx, aminy, amaxy = min(ax), max(ax), min(ay), max(ay)
    bminx, bmaxx, bminy, bmaxy = min(bx), max(bx), min(by), max(by)
    iw = max(0.0, min(amaxx, bmaxx) - max(aminx, bminx))
    ih = max(0.0, min(amaxy, bmaxy) - max(aminy, bminy))
    intersection = iw * ih
    area_a = max(1e-9, (amaxx - aminx) * (amaxy - aminy))
    area_b = max(1e-9, (bmaxx - bminx) * (bmaxy - bminy))
    return intersection / min(area_a, area_b)


def _largest_gap(sections: list[dict[str, Any]]) -> tuple[float, int]:
    if len(sections) < 2:
        return 0.0, -1
    gaps = [
        float(sections[index + 1]["z_m"]) - float(sections[index]["z_m"])
        for index in range(len(sections) - 1)
    ]
    gap_index = int(np.argmax(np.asarray(gaps, dtype=np.float64)))
    return float(gaps[gap_index]), gap_index


def _weakest_gap_overlap(sections: list[dict[str, Any]]) -> tuple[float, float]:
    gap, gap_index = _largest_gap(sections)
    if gap_index < 0:
        return 0.0, 0.0
    overlap = _bbox_overlap_ratio(sections[gap_index], sections[gap_index + 1])
    return gap, float(overlap)


def _assembly_link_support(
    assembly: dict[str, Any],
    candidate: dict[str, Any],
) -> tuple[bool, int, float]:
    member_ids = {int(value) for value in candidate.get("member_component_ids", [])}
    if len(member_ids) < 2:
        return False, 0, 0.0

    links = []
    for link in assembly.get("links", []):
        left = int(link.get("component_a", -1))
        right = int(link.get("component_b", -1))
        if left in member_ids and right in member_ids:
            links.append(link)

    if not links:
        return False, 0, 0.0

    adjacency: dict[int, set[int]] = {component_id: set() for component_id in member_ids}
    for link in links:
        left = int(link["component_a"])
        right = int(link["component_b"])
        adjacency[left].add(right)
        adjacency[right].add(left)

    start = next(iter(member_ids))
    stack = [start]
    visited: set[int] = set()
    while stack:
        current = stack.pop()
        if current in visited:
            continue
        visited.add(current)
        stack.extend(adjacency[current] - visited)

    connected = visited == member_ids
    min_overlap = min(float(link.get("xy_overlap_ratio", 0.0)) for link in links)
    return connected, len(links), min_overlap


def _make_mesh(
    candidate: dict[str, Any],
    candidate_records: list[dict[str, Any]],
    sections: list[dict[str, Any]],
    *,
    section_mode: str,
    fixed_section_count: int,
    ring_vertices: int,
    max_bridge_gap_m: float,
    overlap: float,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    max_gap, _ = _largest_gap(sections)
    mesh = {
        "assembly_id": int(candidate["assembly_id"]),
        "point_count": int(candidate.get("point_count", len(candidate_records))),
        "section_count": len(sections),
        "section_mode": section_mode,
        "fixed_section_count_before_fallback": fixed_section_count,
        "ring_vertices": ring_vertices,
        "max_section_gap_m": round(max_gap, 4),
        "bridged_evidence_gap": max_gap > max_bridge_gap_m,
        "recovery_xy_overlap_ratio": round(overlap, 4),
        "sections": sections,
    }
    if extra:
        mesh.update(extra)
    return mesh


def build_high_structure_mesh_with_recovery(
    assembly: dict[str, Any],
    *,
    slice_height_m: float = 1.0,
    min_slice_points: int = 8,
    min_section_area_m2: float = 0.20,
    ring_vertices: int = 12,
    max_bridge_gap_m: float = 2.0,
    adaptive_target_sections: int = 8,
    adaptive_max_band_height_m: float = 4.0,
    recovery_gap_factor: float = 1.30,
    min_gap_xy_overlap_ratio: float = 0.55,
    max_assembly_evidence_gap_m: float = 1.75,
    min_assembly_link_overlap_ratio: float = 0.65,
) -> dict[str, Any]:
    if recovery_gap_factor < 1.0:
        raise ValueError("recovery_gap_factor must be >= 1")
    if not 0.0 <= min_gap_xy_overlap_ratio <= 1.0:
        raise ValueError("min_gap_xy_overlap_ratio must be in [0, 1]")
    if max_assembly_evidence_gap_m < 0.0:
        raise ValueError("max_assembly_evidence_gap_m must be >= 0")
    if not 0.0 <= min_assembly_link_overlap_ratio <= 1.0:
        raise ValueError("min_assembly_link_overlap_ratio must be in [0, 1]")

    result = build_high_structure_mesh(
        assembly,
        slice_height_m=slice_height_m,
        min_slice_points=min_slice_points,
        min_section_area_m2=min_section_area_m2,
        ring_vertices=ring_vertices,
        max_bridge_gap_m=max_bridge_gap_m,
        adaptive_target_sections=adaptive_target_sections,
        adaptive_max_band_height_m=adaptive_max_band_height_m,
    )

    records = assembly.get("point_records", [])
    by_assembly: dict[int, list[dict[str, Any]]] = {}
    for record in records:
        by_assembly.setdefault(int(record["assembly_id"]), []).append(record)

    candidate_by_id = {
        int(candidate["assembly_id"]): candidate
        for candidate in assembly.get("assemblies", [])
    }

    recovered: list[dict[str, Any]] = []
    remaining_skipped: list[dict[str, Any]] = []
    recovery_limit = max_bridge_gap_m * recovery_gap_factor

    for skipped in result.get("skipped", []):
        if skipped.get("reason") != "vertical_section_gap_too_large":
            remaining_skipped.append(skipped)
            continue

        assembly_id = int(skipped["assembly_id"])
        candidate = candidate_by_id.get(assembly_id, {})
        candidate_records = by_assembly.get(assembly_id, [])
        xyz = np.asarray(
            [[float(row["x"]), float(row["y"]), float(row["z"])] for row in candidate_records],
            dtype=np.float64,
        )
        if len(xyz) < min_slice_points * 2:
            rejected = dict(skipped)
            rejected["recovery_attempted"] = True
            rejected["recovery_reason"] = "insufficient_points"
            remaining_skipped.append(rejected)
            continue

        fixed = _fixed_section_records(
            xyz,
            slice_height_m=slice_height_m,
            min_slice_points=min_slice_points,
            min_section_area_m2=min_section_area_m2,
            ring_vertices=ring_vertices,
        )
        adaptive = _adaptive_quantile_sections(
            xyz,
            min_slice_points=min_slice_points,
            min_section_area_m2=min_section_area_m2,
            ring_vertices=ring_vertices,
            target_section_count=adaptive_target_sections,
            max_band_height_m=adaptive_max_band_height_m,
        )

        adaptive_gap, adaptive_overlap = _weakest_gap_overlap(adaptive)

        if (
            len(adaptive) >= 2
            and adaptive_gap <= recovery_limit
            and adaptive_overlap >= min_gap_xy_overlap_ratio
        ):
            mesh = _make_mesh(
                candidate,
                candidate_records,
                adaptive,
                section_mode="adaptive_gap_recovery",
                fixed_section_count=len(fixed),
                ring_vertices=ring_vertices,
                max_bridge_gap_m=max_bridge_gap_m,
                overlap=adaptive_overlap,
            )
            result["meshes"].append(mesh)
            recovered.append(
                {
                    "assembly_id": assembly_id,
                    "recovery_mode": "adaptive_gap_recovery",
                    "section_count": len(adaptive),
                    "max_section_gap_m": round(adaptive_gap, 4),
                    "xy_overlap_ratio_at_largest_gap": round(adaptive_overlap, 4),
                }
            )
            continue

        connected, internal_link_count, min_link_overlap = _assembly_link_support(
            assembly, candidate
        )
        assembly_gap = float(candidate.get("max_observed_vertical_gap_m", float("inf")))

        section_candidates: list[tuple[float, list[dict[str, Any]], str]] = []
        for sections, mode in (
            (fixed, "fixed_height_bins"),
            (adaptive, "adaptive_equal_support_bands"),
        ):
            if len(sections) < 2:
                continue
            gap, _ = _largest_gap(sections)
            if gap <= recovery_limit:
                section_candidates.append((gap, sections, mode))
        section_candidates.sort(key=lambda item: (item[0], -len(item[1])))

        assembly_supported = (
            bool(candidate.get("reconstruction_gate"))
            and int(candidate.get("member_count", 1)) >= 2
            and connected
            and assembly_gap <= max_assembly_evidence_gap_m
            and min_link_overlap >= min_assembly_link_overlap_ratio
            and bool(section_candidates)
        )

        if assembly_supported:
            chosen_gap, chosen_sections, source_mode = section_candidates[0]
            mesh = _make_mesh(
                candidate,
                candidate_records,
                chosen_sections,
                section_mode="assembly_link_gap_recovery",
                fixed_section_count=len(fixed),
                ring_vertices=ring_vertices,
                max_bridge_gap_m=max_bridge_gap_m,
                overlap=min_link_overlap,
                extra={
                    "source_section_mode": source_mode,
                    "assembly_observed_vertical_gap_m": round(assembly_gap, 4),
                    "assembly_internal_link_count": internal_link_count,
                    "assembly_min_link_xy_overlap_ratio": round(min_link_overlap, 4),
                },
            )
            result["meshes"].append(mesh)
            recovered.append(
                {
                    "assembly_id": assembly_id,
                    "recovery_mode": "assembly_link_gap_recovery",
                    "section_count": len(chosen_sections),
                    "max_section_gap_m": round(chosen_gap, 4),
                    "assembly_observed_vertical_gap_m": round(assembly_gap, 4),
                    "assembly_min_link_xy_overlap_ratio": round(min_link_overlap, 4),
                }
            )
            continue

        rejected = dict(skipped)
        rejected["recovery_attempted"] = True
        rejected["recovery_gap_limit_m"] = round(recovery_limit, 4)
        rejected["adaptive_section_count"] = len(adaptive)
        rejected["adaptive_max_gap_m"] = round(adaptive_gap, 4)
        rejected["adaptive_xy_overlap_ratio"] = round(adaptive_overlap, 4)
        rejected["fixed_section_count"] = len(fixed)
        rejected["assembly_member_count"] = int(candidate.get("member_count", 1))
        rejected["assembly_observed_vertical_gap_m"] = (
            round(assembly_gap, 4) if np.isfinite(assembly_gap) else None
        )
        rejected["assembly_link_connected"] = connected
        rejected["assembly_internal_link_count"] = internal_link_count
        rejected["assembly_min_link_xy_overlap_ratio"] = round(min_link_overlap, 4)
        remaining_skipped.append(rejected)

    result["meshes"].sort(key=lambda item: int(item["assembly_id"]))
    result["skipped"] = remaining_skipped
    result["mesh_count"] = len(result["meshes"])
    result["skipped_count"] = len(remaining_skipped)
    result["schema_version"] = 4
    result["method"] = (
        "fixed-height LiDAR sections with guarded adaptive and assembly-link gap recovery"
    )
    result["recovery"] = {
        "recovered_count": len(recovered),
        "max_gap_factor": recovery_gap_factor,
        "min_gap_xy_overlap_ratio": min_gap_xy_overlap_ratio,
        "max_assembly_evidence_gap_m": max_assembly_evidence_gap_m,
        "min_assembly_link_overlap_ratio": min_assembly_link_overlap_ratio,
        "recovered": recovered,
    }
    result.setdefault("notes", []).extend(
        [
            "A section gap is never relaxed by threshold alone.",
            "First recovery path requires an independent equal-support reconstruction with XY continuity.",
            "Second recovery path reuses upstream assembly evidence only when strong components are graph-connected, overlap in XY, and their measured evidence gap remains bounded.",
            "Recovered lofts remain evidence envelopes and are not production geometry claims.",
        ]
    )
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Recover sparse vertical gaps in LiDAR high-structure lofts using independent section and assembly evidence."
    )
    parser.add_argument("--assembly-json", type=Path, required=True)
    parser.add_argument("--shell-json", type=Path)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-obj", type=Path, required=True)
    parser.add_argument("--output-composite-obj", type=Path)
    parser.add_argument("--slice-height-m", type=float, default=1.0)
    parser.add_argument("--min-slice-points", type=int, default=8)
    parser.add_argument("--min-section-area-m2", type=float, default=0.20)
    parser.add_argument("--ring-vertices", type=int, default=12)
    parser.add_argument("--max-bridge-gap-m", type=float, default=2.0)
    parser.add_argument("--adaptive-target-sections", type=int, default=8)
    parser.add_argument("--adaptive-max-band-height-m", type=float, default=4.0)
    parser.add_argument("--recovery-gap-factor", type=float, default=1.30)
    parser.add_argument("--min-gap-xy-overlap-ratio", type=float, default=0.55)
    parser.add_argument("--max-assembly-evidence-gap-m", type=float, default=1.75)
    parser.add_argument("--min-assembly-link-overlap-ratio", type=float, default=0.65)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        assembly = _load_json(args.assembly_json)
        result = build_high_structure_mesh_with_recovery(
            assembly,
            slice_height_m=args.slice_height_m,
            min_slice_points=args.min_slice_points,
            min_section_area_m2=args.min_section_area_m2,
            ring_vertices=args.ring_vertices,
            max_bridge_gap_m=args.max_bridge_gap_m,
            adaptive_target_sections=args.adaptive_target_sections,
            adaptive_max_band_height_m=args.adaptive_max_band_height_m,
            recovery_gap_factor=args.recovery_gap_factor,
            min_gap_xy_overlap_ratio=args.min_gap_xy_overlap_ratio,
            max_assembly_evidence_gap_m=args.max_assembly_evidence_gap_m,
            min_assembly_link_overlap_ratio=args.min_assembly_link_overlap_ratio,
        )
        shell = _load_json(args.shell_json) if args.shell_json else None
        if args.output_composite_obj and shell is None:
            raise ValueError("--output-composite-obj requires --shell-json")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"BatiForge high-structure recovery failed: {exc}")
        return 2

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    write_high_structure_obj(args.output_obj, result)
    if args.output_composite_obj and shell is not None:
        write_composite_obj(args.output_composite_obj, shell, result)

    print(
        "high-structure recovery: "
        f"assemblies={result['assembly_count']} meshes={result['mesh_count']} "
        f"recovered={result['recovery']['recovered_count']} skipped={result['skipped_count']}"
    )
    for mesh in result["meshes"]:
        print(
            f"  #{mesh['assembly_id']}: mode={mesh['section_mode']} "
            f"sections={mesh['section_count']} max_gap={mesh['max_section_gap_m']:.2f}m "
            f"xy={mesh.get('recovery_xy_overlap_ratio', 0.0):.3f}"
        )
    for item in result["skipped"]:
        print(
            f"  skipped #{item['assembly_id']}: reason={item['reason']} "
            f"adaptive_gap={item.get('adaptive_max_gap_m')} "
            f"adaptive_xy={item.get('adaptive_xy_overlap_ratio')} "
            f"assembly_gap={item.get('assembly_observed_vertical_gap_m')} "
            f"assembly_xy={item.get('assembly_min_link_xy_overlap_ratio')}"
        )
    print(f"json: {args.output_json}")
    print(f"obj: {args.output_obj}")
    if args.output_composite_obj:
        print(f"composite obj: {args.output_composite_obj}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
