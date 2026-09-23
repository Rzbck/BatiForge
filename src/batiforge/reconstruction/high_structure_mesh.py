from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from .roof_regions import _ear_clip


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def _cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _convex_hull(points: np.ndarray) -> list[tuple[float, float]]:
    unique = sorted({(round(float(x), 6), round(float(y), 6)) for x, y in points})
    if len(unique) < 3:
        return []
    lower: list[tuple[float, float]] = []
    for point in unique:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], point) <= 0.0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(unique):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], point) <= 0.0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def _polygon_area(poly: list[tuple[float, float]]) -> float:
    if len(poly) < 3:
        return 0.0
    return 0.5 * abs(
        sum(
            poly[i][0] * poly[(i + 1) % len(poly)][1]
            - poly[(i + 1) % len(poly)][0] * poly[i][1]
            for i in range(len(poly))
        )
    )


def _signed_area(poly: list[tuple[float, float]]) -> float:
    return 0.5 * sum(
        poly[i][0] * poly[(i + 1) % len(poly)][1]
        - poly[(i + 1) % len(poly)][0] * poly[i][1]
        for i in range(len(poly))
    )


def _resample_closed(poly: list[tuple[float, float]], count: int) -> list[tuple[float, float]]:
    if len(poly) < 3 or count < 3:
        raise ValueError("closed polygon resampling requires >=3 vertices")
    if _signed_area(poly) < 0.0:
        poly = list(reversed(poly))
    lengths: list[float] = []
    perimeter = 0.0
    for i in range(len(poly)):
        a = poly[i]
        b = poly[(i + 1) % len(poly)]
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        lengths.append(length)
        perimeter += length
    if perimeter <= 1e-9:
        raise ValueError("degenerate polygon perimeter")
    samples: list[tuple[float, float]] = []
    edge = 0
    edge_start_distance = 0.0
    for sample_index in range(count):
        target = perimeter * sample_index / count
        while edge < len(poly) - 1 and target > edge_start_distance + lengths[edge]:
            edge_start_distance += lengths[edge]
            edge += 1
        a = poly[edge]
        b = poly[(edge + 1) % len(poly)]
        denom = max(lengths[edge], 1e-12)
        t = (target - edge_start_distance) / denom
        samples.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
    return samples


def _align_ring(previous: list[tuple[float, float]], current: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if len(previous) != len(current):
        raise ValueError("ring sizes must match")
    best_shift = 0
    best_score = math.inf
    n = len(current)
    for shift in range(n):
        score = 0.0
        for i, point in enumerate(previous):
            candidate = current[(i + shift) % n]
            score += (point[0] - candidate[0]) ** 2 + (point[1] - candidate[1]) ** 2
        if score < best_score:
            best_score = score
            best_shift = shift
    return [current[(i + best_shift) % n] for i in range(n)]


def _section_records(
    records: list[dict[str, Any]],
    *,
    slice_height_m: float,
    min_slice_points: int,
    min_section_area_m2: float,
    ring_vertices: int,
) -> list[dict[str, Any]]:
    if slice_height_m <= 0.0:
        raise ValueError("slice_height_m must be > 0")
    xyz = np.asarray(
        [[float(r["x"]), float(r["y"]), float(r["z"])] for r in records],
        dtype=np.float64,
    )
    if len(xyz) < min_slice_points:
        return []
    z0 = float(np.min(xyz[:, 2]))
    bins = np.floor((xyz[:, 2] - z0) / slice_height_m).astype(np.int64)
    sections: list[dict[str, Any]] = []
    for bin_index in sorted(set(int(value) for value in bins.tolist())):
        rows = np.flatnonzero(bins == bin_index)
        if len(rows) < min_slice_points:
            continue
        hull = _convex_hull(xyz[rows, :2])
        if len(hull) < 3:
            continue
        area = _polygon_area(hull)
        if area < min_section_area_m2:
            continue
        ring = _resample_closed(hull, ring_vertices)
        z = float(np.median(xyz[rows, 2]))
        center_x = float(np.median(xyz[rows, 0]))
        center_y = float(np.median(xyz[rows, 1]))
        sections.append(
            {
                "source_bin": bin_index,
                "point_count": int(len(rows)),
                "z_m": round(z, 5),
                "area_xy_m2": round(area, 4),
                "center_xy_m": [round(center_x, 5), round(center_y, 5)],
                "ring_xy": [[round(x, 5), round(y, 5)] for x, y in ring],
            }
        )
    sections.sort(key=lambda item: float(item["z_m"]))
    for index in range(1, len(sections)):
        previous = [(float(x), float(y)) for x, y in sections[index - 1]["ring_xy"]]
        current = [(float(x), float(y)) for x, y in sections[index]["ring_xy"]]
        aligned = _align_ring(previous, current)
        sections[index]["ring_xy"] = [[round(x, 5), round(y, 5)] for x, y in aligned]
    return sections


def build_high_structure_mesh(
    assembly: dict[str, Any],
    *,
    slice_height_m: float = 1.0,
    min_slice_points: int = 8,
    min_section_area_m2: float = 0.20,
    ring_vertices: int = 12,
    max_bridge_gap_m: float = 2.0,
) -> dict[str, Any]:
    if min_slice_points < 3:
        raise ValueError("min_slice_points must be >= 3")
    if ring_vertices < 4:
        raise ValueError("ring_vertices must be >= 4")
    if max_bridge_gap_m <= 0.0:
        raise ValueError("max_bridge_gap_m must be > 0")

    records = assembly.get("point_records", [])
    assemblies = assembly.get("assemblies", [])
    if not isinstance(records, list) or not isinstance(assemblies, list):
        raise ValueError("assembly JSON missing lists")
    by_assembly: dict[int, list[dict[str, Any]]] = {}
    for record in records:
        by_assembly.setdefault(int(record["assembly_id"]), []).append(record)

    meshes: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for candidate in assemblies:
        assembly_id = int(candidate["assembly_id"])
        candidate_records = by_assembly.get(assembly_id, [])
        sections = _section_records(
            candidate_records,
            slice_height_m=slice_height_m,
            min_slice_points=min_slice_points,
            min_section_area_m2=min_section_area_m2,
            ring_vertices=ring_vertices,
        )
        if len(sections) < 2:
            skipped.append({"assembly_id": assembly_id, "reason": "insufficient_supported_sections"})
            continue
        gaps = [
            float(sections[index + 1]["z_m"]) - float(sections[index]["z_m"])
            for index in range(len(sections) - 1)
        ]
        if gaps and max(gaps) > max_bridge_gap_m:
            skipped.append(
                {
                    "assembly_id": assembly_id,
                    "reason": "vertical_section_gap_too_large",
                    "max_section_gap_m": round(max(gaps), 4),
                }
            )
            continue
        meshes.append(
            {
                "assembly_id": assembly_id,
                "point_count": int(candidate.get("point_count", len(candidate_records))),
                "section_count": len(sections),
                "ring_vertices": ring_vertices,
                "max_section_gap_m": round(max(gaps) if gaps else 0.0, 4),
                "bridged_evidence_gap": bool(gaps and max(gaps) > slice_height_m * 1.35),
                "sections": sections,
            }
        )

    return {
        "schema_version": 1,
        "method": "adaptive horizontal-section convex-hull loft from assembled LiDAR evidence",
        "georeference": assembly.get("georeference", {}),
        "parameters": {
            "slice_height_m": slice_height_m,
            "min_slice_points": min_slice_points,
            "min_section_area_m2": min_section_area_m2,
            "ring_vertices": ring_vertices,
            "max_bridge_gap_m": max_bridge_gap_m,
        },
        "assembly_count": len(assemblies),
        "mesh_count": len(meshes),
        "skipped_count": len(skipped),
        "meshes": meshes,
        "skipped": skipped,
        "production_claim": False,
        "notes": [
            "Geometry is an evidence envelope, not a semantic chimney/steeple classification.",
            "Section gaps are bridged only below the configured maximum and remain reported.",
            "No boolean union with the main shell is claimed at this stage.",
        ],
    }


def _append_polygon(lines: list[str], vertices: list[list[float]], offset: int) -> int:
    if len(vertices) < 3:
        return offset
    for x, y, z in vertices:
        lines.append(f"v {float(x):.6f} {float(y):.6f} {float(z):.6f}")
    lines.append("f " + " ".join(str(offset + i) for i in range(len(vertices))))
    return offset + len(vertices)


def _append_shell(lines: list[str], shell: dict[str, Any], offset: int) -> int:
    for region in shell.get("roof_regions", []):
        lines.append(f"o shell_roof_r{int(region.get('region_index', 0)):03d}")
        offset = _append_polygon(lines, region.get("vertices_local_xyz", []), offset)
    for index, wall in enumerate(shell.get("perimeter_walls", []), start=1):
        lines.append(f"o shell_wall_{index:03d}_{wall.get('provenance', 'unknown')}")
        offset = _append_polygon(lines, wall.get("vertices_local_xyz", []), offset)
    for index, step in enumerate(shell.get("height_step_faces", []), start=1):
        lines.append(f"o shell_height_step_{index:03d}")
        offset = _append_polygon(lines, step.get("vertices_local_xyz", []), offset)

    floor = [(float(x), float(y)) for x, y in shell.get("floor_polygon_local_xy", [])]
    if len(floor) >= 3:
        lines.append("o shell_ground_floor")
        for triangle in _ear_clip(tuple(floor)):
            raw = [[float(x), float(y), 0.0] for x, y in triangle]
            offset = _append_polygon(lines, raw, offset)
    return offset


def _append_loft(lines: list[str], mesh: dict[str, Any], offset: int) -> int:
    sections = mesh["sections"]
    rings: list[list[int]] = []
    lines.append(f"o high_structure_{int(mesh['assembly_id']):02d}")
    for section in sections:
        z = float(section["z_m"])
        ring_ids: list[int] = []
        for x, y in section["ring_xy"]:
            lines.append(f"v {float(x):.6f} {float(y):.6f} {z:.6f}")
            ring_ids.append(offset)
            offset += 1
        rings.append(ring_ids)

    for lower, upper in zip(rings, rings[1:], strict=False):
        n = len(lower)
        for i in range(n):
            j = (i + 1) % n
            lines.append(f"f {lower[i]} {lower[j]} {upper[j]} {upper[i]}")

    if rings:
        lines.append("f " + " ".join(str(value) for value in reversed(rings[0])))
        lines.append("f " + " ".join(str(value) for value in rings[-1]))
    return offset


def write_composite_obj(path: Path, shell: dict[str, Any], result: dict[str, Any]) -> None:
    geo = result.get("georeference", {})
    lines = [
        "# BatiForge composite shell + LiDAR high-structure evidence preview",
        "# X east / Y north / Z up",
        "# shell floor uses ear-clipped triangles; no first-vertex fan",
        "# high structure is an adaptive section loft; not yet boolean-unioned",
        "s off",
        f"# horizontal_crs={geo.get('horizontal_crs')}",
        f"# vertical_datum={geo.get('vertical_datum')}",
    ]
    offset = 1
    offset = _append_shell(lines, shell, offset)
    for mesh in result.get("meshes", []):
        offset = _append_loft(lines, mesh, offset)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_high_structure_obj(path: Path, result: dict[str, Any]) -> None:
    lines = [
        "# BatiForge LiDAR high-structure evidence loft",
        "# X east / Y north / Z up",
        "# NOT production geometry; no boolean union claimed",
        "s off",
    ]
    offset = 1
    for mesh in result.get("meshes", []):
        offset = _append_loft(lines, mesh, offset)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build an adaptive LiDAR evidence loft for assembled high structures and optionally a composite shell preview."
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        assembly = _load_json(args.assembly_json)
        result = build_high_structure_mesh(
            assembly,
            slice_height_m=args.slice_height_m,
            min_slice_points=args.min_slice_points,
            min_section_area_m2=args.min_section_area_m2,
            ring_vertices=args.ring_vertices,
            max_bridge_gap_m=args.max_bridge_gap_m,
        )
        shell = _load_json(args.shell_json) if args.shell_json else None
        if args.output_composite_obj and shell is None:
            raise ValueError("--output-composite-obj requires --shell-json")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"BatiForge high-structure mesh failed: {exc}")
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
        "high-structure mesh: "
        f"assemblies={result['assembly_count']} meshes={result['mesh_count']} skipped={result['skipped_count']}"
    )
    for mesh in result["meshes"]:
        sections = mesh["sections"]
        print(
            f"  #{mesh['assembly_id']}: points={mesh['point_count']} sections={mesh['section_count']} "
            f"z={sections[0]['z_m']:.2f}..{sections[-1]['z_m']:.2f}m "
            f"max_gap={mesh['max_section_gap_m']:.2f}m"
        )
    print(f"json: {args.output_json}")
    print(f"obj: {args.output_obj}")
    if args.output_composite_obj:
        print(f"composite obj: {args.output_composite_obj}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
