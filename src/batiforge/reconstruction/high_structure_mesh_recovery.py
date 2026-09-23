from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from .high_structure_mesh import (
    _adaptive_quantile_sections,
    _load_json,
    build_high_structure_mesh,
    write_composite_obj,
    write_high_structure_obj,
)


def _max_gap(sections: list[dict[str, Any]]) -> float:
    if len(sections) < 2:
        return 0.0
    return max(
        float(sections[index + 1]["z_m"]) - float(sections[index]["z_m"])
        for index in range(len(sections) - 1)
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


def _weakest_gap_overlap(sections: list[dict[str, Any]]) -> tuple[float, float]:
    if len(sections) < 2:
        return 0.0, 0.0
    gaps = [
        float(sections[index + 1]["z_m"]) - float(sections[index]["z_m"])
        for index in range(len(sections) - 1)
    ]
    gap_index = int(np.argmax(np.asarray(gaps, dtype=np.float64)))
    overlap = _bbox_overlap_ratio(sections[gap_index], sections[gap_index + 1])
    return float(gaps[gap_index]), float(overlap)


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
) -> dict[str, Any]:
    if recovery_gap_factor < 1.0:
        raise ValueError("recovery_gap_factor must be >= 1")
    if not 0.0 <= min_gap_xy_overlap_ratio <= 1.0:
        raise ValueError("min_gap_xy_overlap_ratio must be in [0, 1]")

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
        candidate_records = by_assembly.get(assembly_id, [])
        xyz = np.asarray(
            [[float(row["x"]), float(row["y"]), float(row["z"])] for row in candidate_records],
            dtype=np.float64,
        )
        if len(xyz) < min_slice_points * 2:
            remaining_skipped.append(skipped)
            continue

        adaptive = _adaptive_quantile_sections(
            xyz,
            min_slice_points=min_slice_points,
            min_section_area_m2=min_section_area_m2,
            ring_vertices=ring_vertices,
            target_section_count=adaptive_target_sections,
            max_band_height_m=adaptive_max_band_height_m,
        )
        adaptive_gap, overlap = _weakest_gap_overlap(adaptive)

        if (
            len(adaptive) < 2
            or adaptive_gap > recovery_limit
            or overlap < min_gap_xy_overlap_ratio
        ):
            rejected = dict(skipped)
            rejected["recovery_attempted"] = True
            rejected["recovery_section_count"] = len(adaptive)
            rejected["recovery_max_gap_m"] = round(adaptive_gap, 4)
            rejected["recovery_gap_limit_m"] = round(recovery_limit, 4)
            rejected["recovery_xy_overlap_ratio"] = round(overlap, 4)
            remaining_skipped.append(rejected)
            continue

        candidate = candidate_by_id.get(assembly_id, {})
        mesh = {
            "assembly_id": assembly_id,
            "point_count": int(candidate.get("point_count", len(candidate_records))),
            "section_count": len(adaptive),
            "section_mode": "adaptive_gap_recovery",
            "fixed_section_count_before_fallback": int(skipped.get("fixed_section_count", 0)),
            "ring_vertices": ring_vertices,
            "max_section_gap_m": round(adaptive_gap, 4),
            "bridged_evidence_gap": adaptive_gap > max_bridge_gap_m,
            "recovery_xy_overlap_ratio": round(overlap, 4),
            "sections": adaptive,
        }
        result["meshes"].append(mesh)
        recovered.append(
            {
                "assembly_id": assembly_id,
                "section_count": len(adaptive),
                "max_section_gap_m": round(adaptive_gap, 4),
                "xy_overlap_ratio_at_largest_gap": round(overlap, 4),
            }
        )

    result["meshes"].sort(key=lambda item: int(item["assembly_id"]))
    result["skipped"] = remaining_skipped
    result["mesh_count"] = len(result["meshes"])
    result["skipped_count"] = len(remaining_skipped)
    result["schema_version"] = 3
    result["method"] = "fixed-height LiDAR sections with guarded adaptive gap recovery"
    result["recovery"] = {
        "recovered_count": len(recovered),
        "max_gap_factor": recovery_gap_factor,
        "min_gap_xy_overlap_ratio": min_gap_xy_overlap_ratio,
        "recovered": recovered,
    }
    result.setdefault("notes", []).extend(
        [
            "A fixed-section vertical gap is never relaxed by threshold alone.",
            "Recovery requires an independent equal-support reconstruction and strong XY overlap across its largest gap.",
            "Recovered lofts remain evidence envelopes and are not production geometry claims.",
        ]
    )
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Recover sparse vertical gaps in LiDAR high-structure lofts using an independent adaptive support test."
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
        )
        shell = _load_json(args.shell_json) if args.shell_json else None
        if args.output_composite_obj and shell is None:
            raise ValueError("--output-composite-obj requires --shell-json")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"BatiForge high-structure recovery failed: {exc}")
        return 2

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
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
            f"  #{mesh['assembly_id']}: mode={mesh['section_mode']} sections={mesh['section_count']} "
            f"max_gap={mesh['max_section_gap_m']:.2f}m"
        )
    for item in result["skipped"]:
        print(f"  skipped #{item['assembly_id']}: reason={item['reason']}")
    print(f"json: {args.output_json}")
    print(f"obj: {args.output_obj}")
    if args.output_composite_obj:
        print(f"composite obj: {args.output_composite_obj}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
