from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterable

import laspy
import numpy as np


def _fill_ground_cells(
    measured: dict[int, float],
    *,
    nx: int,
    ny: int,
    radius_cells: int,
    min_neighbors: int,
    min_directions: int,
    max_z_span_m: float,
) -> dict[int, float]:
    if radius_cells <= 0:
        return {}
    if min_neighbors < 3:
        raise ValueError("fill_min_neighbors must be >= 3")
    if min_directions < 1 or min_directions > 4:
        raise ValueError("fill_min_directions must be between 1 and 4")
    if max_z_span_m <= 0:
        raise ValueError("fill_max_z_span_m must be > 0")

    filled: dict[int, float] = {}
    radius_sq = float(radius_cells * radius_cells) + 1e-9

    for row in range(ny):
        for col in range(nx):
            key = row * nx + col
            if key in measured:
                continue

            samples: list[tuple[float, float, float]] = []
            has_left = has_right = has_down = has_up = False
            r0 = max(0, row - radius_cells)
            r1 = min(ny - 1, row + radius_cells)
            c0 = max(0, col - radius_cells)
            c1 = min(nx - 1, col + radius_cells)

            for rr in range(r0, r1 + 1):
                for cc in range(c0, c1 + 1):
                    if rr == row and cc == col:
                        continue
                    dr = rr - row
                    dc = cc - col
                    if float(dr * dr + dc * dc) > radius_sq:
                        continue
                    neighbor_key = rr * nx + cc
                    z = measured.get(neighbor_key)
                    if z is None:
                        continue
                    samples.append((float(dc), float(dr), float(z)))
                    if dc < 0:
                        has_left = True
                    elif dc > 0:
                        has_right = True
                    if dr < 0:
                        has_down = True
                    elif dr > 0:
                        has_up = True

            if len(samples) < min_neighbors:
                continue
            if sum((has_left, has_right, has_down, has_up)) < min_directions:
                continue

            z_values = np.asarray([sample[2] for sample in samples], dtype=np.float64)
            if float(z_values.max() - z_values.min()) > max_z_span_m:
                continue

            design = np.asarray(
                [[sample[0], sample[1], 1.0] for sample in samples],
                dtype=np.float64,
            )
            try:
                coeffs, *_ = np.linalg.lstsq(design, z_values, rcond=None)
            except np.linalg.LinAlgError:
                continue
            predicted = float(coeffs[2])
            if not math.isfinite(predicted):
                continue

            tolerance = 0.05
            if predicted < float(z_values.min()) - tolerance:
                continue
            if predicted > float(z_values.max()) + tolerance:
                continue
            filled[key] = predicted

    return filled


def build_ground_grid(
    xyz: np.ndarray,
    classifications: np.ndarray,
    *,
    crop: tuple[float, float, float, float],
    origin_x: float,
    origin_y: float,
    ground_z: float,
    ground_classes: tuple[int, ...] = (2,),
    cell_size_m: float = 0.5,
    min_points_per_cell: int = 1,
    fill_radius_cells: int = 0,
    fill_min_neighbors: int = 4,
    fill_min_directions: int = 3,
    fill_max_z_span_m: float = 0.6,
) -> tuple[np.ndarray, np.ndarray, dict]:
    if cell_size_m <= 0:
        raise ValueError("cell_size_m must be > 0")
    if min_points_per_cell < 1:
        raise ValueError("min_points_per_cell must be >= 1")
    pts = np.asarray(xyz, dtype=np.float64)
    cls = np.asarray(classifications)
    if pts.ndim != 2 or pts.shape[1] != 3 or len(pts) != len(cls):
        raise ValueError("xyz must be Nx3 and classifications must match")

    min_x, min_y, max_x, max_y = map(float, crop)
    mask = (
        np.isfinite(pts).all(axis=1)
        & (pts[:, 0] >= min_x)
        & (pts[:, 0] <= max_x)
        & (pts[:, 1] >= min_y)
        & (pts[:, 1] <= max_y)
        & np.isin(cls.astype(np.int64), np.asarray(ground_classes, dtype=np.int64))
    )
    ground = pts[mask]
    if not len(ground):
        raise ValueError("no ground-class points found in crop")

    nx = max(1, int(math.ceil((max_x - min_x) / cell_size_m)))
    ny = max(1, int(math.ceil((max_y - min_y) / cell_size_m)))
    ix = np.clip(
        np.floor((ground[:, 0] - min_x) / cell_size_m).astype(np.int64), 0, nx - 1
    )
    iy = np.clip(
        np.floor((ground[:, 1] - min_y) / cell_size_m).astype(np.int64), 0, ny - 1
    )
    keys = iy * nx + ix
    order = np.argsort(keys, kind="mergesort")
    keys = keys[order]
    zs = ground[:, 2][order]
    unique, starts, counts = np.unique(keys, return_index=True, return_counts=True)

    measured_z: dict[int, float] = {}
    for key, start, count in zip(
        unique.tolist(), starts.tolist(), counts.tolist(), strict=True
    ):
        if count >= min_points_per_cell:
            measured_z[int(key)] = float(np.median(zs[start : start + count]))
    if not measured_z:
        raise ValueError("no occupied cells pass min_points_per_cell")

    inferred_z = _fill_ground_cells(
        measured_z,
        nx=nx,
        ny=ny,
        radius_cells=fill_radius_cells,
        min_neighbors=fill_min_neighbors,
        min_directions=fill_min_directions,
        max_z_span_m=fill_max_z_span_m,
    )
    cell_z = dict(measured_z)
    cell_z.update(inferred_z)

    vertices: list[tuple[float, float, float]] = []
    indices: dict[int, int] = {}
    for key in sorted(cell_z):
        row, col = divmod(key, nx)
        x = min_x + (col + 0.5) * cell_size_m
        y = min_y + (row + 0.5) * cell_size_m
        indices[key] = len(vertices)
        vertices.append((x - origin_x, y - origin_y, cell_z[key] - ground_z))

    faces: list[tuple[int, int, int]] = []
    for row in range(ny - 1):
        for col in range(nx - 1):
            q = (
                row * nx + col,
                row * nx + col + 1,
                (row + 1) * nx + col + 1,
                (row + 1) * nx + col,
            )
            if all(key in indices for key in q):
                a, b, c, d = (indices[key] for key in q)
                faces.extend(((a, b, c), (a, c, d)))

    verts = np.asarray(vertices, dtype=np.float64)
    tris = (
        np.asarray(faces, dtype=np.int64).reshape((-1, 3))
        if faces
        else np.empty((0, 3), dtype=np.int64)
    )
    total_cells = nx * ny
    meta = {
        "ground_point_count": int(len(ground)),
        "grid": {
            "nx": nx,
            "ny": ny,
            "cell_count": total_cells,
            "measured_cell_count": len(measured_z),
            "inferred_cell_count": len(inferred_z),
            "occupied_cell_count": len(vertices),
            "measured_coverage_ratio": len(measured_z) / total_cells,
            "coverage_ratio": len(vertices) / total_cells,
        },
        "mesh": {"vertex_count": len(vertices), "face_count": len(faces)},
    }
    return verts, tris, meta


def _footprint_crop(
    footprint: dict[str, Any], margin_m: float
) -> tuple[float, float, float, float]:
    b = footprint["bounds"]
    return (
        float(b["min_x"]) - margin_m,
        float(b["min_y"]) - margin_m,
        float(b["max_x"]) + margin_m,
        float(b["max_y"]) + margin_m,
    )


def _bounds_overlap_ratio(
    source_bounds: tuple[float, float, float, float],
    crop: tuple[float, float, float, float],
) -> float:
    smin_x, smin_y, smax_x, smax_y = source_bounds
    cmin_x, cmin_y, cmax_x, cmax_y = crop
    width = max(0.0, min(smax_x, cmax_x) - max(smin_x, cmin_x))
    height = max(0.0, min(smax_y, cmax_y) - max(smin_y, cmin_y))
    crop_area = max(0.0, cmax_x - cmin_x) * max(0.0, cmax_y - cmin_y)
    if crop_area <= 0.0:
        return 0.0
    return (width * height) / crop_area


def lidar_header_bounds(lidar: Path) -> tuple[float, float, float, float]:
    with laspy.open(lidar) as reader:
        mins = reader.header.mins
        maxs = reader.header.maxs
        return float(mins[0]), float(mins[1]), float(maxs[0]), float(maxs[1])


def _deduplicate_xyz(xyz: np.ndarray, precision_m: float = 0.001) -> np.ndarray:
    if len(xyz) <= 1:
        return xyz
    quantised = np.rint(xyz / precision_m).astype(np.int64)
    _, first = np.unique(quantised, axis=0, return_index=True)
    return xyz[np.sort(first)]


def build_from_lidars(
    lidars: Iterable[Path],
    footprint_json: Path,
    *,
    ground_z: float,
    margin_m: float,
    cell_size_m: float,
    ground_classes: tuple[int, ...],
    min_points_per_cell: int,
    chunk_size: int,
    fill_radius_cells: int = 0,
    fill_min_neighbors: int = 4,
    fill_min_directions: int = 3,
    fill_max_z_span_m: float = 0.6,
) -> tuple[np.ndarray, np.ndarray, dict]:
    footprint = json.loads(footprint_json.read_text(encoding="utf-8"))
    crop = _footprint_crop(footprint, margin_m)
    min_x, min_y, max_x, max_y = crop

    candidates: list[dict[str, Any]] = []
    for lidar in dict.fromkeys(Path(path) for path in lidars):
        bounds = lidar_header_bounds(lidar)
        overlap_ratio = _bounds_overlap_ratio(bounds, crop)
        candidates.append(
            {"path": lidar, "bounds": bounds, "overlap_ratio": overlap_ratio}
        )

    overlapping = [item for item in candidates if item["overlap_ratio"] > 0.0]
    if not overlapping:
        raise ValueError("no LiDAR source overlaps requested context crop")
    overlapping.sort(
        key=lambda item: (item["overlap_ratio"], item["path"].stat().st_size),
        reverse=True,
    )

    xyz_parts: list[np.ndarray] = []
    histogram: dict[int, int] = {}
    cropped_all = 0
    source_stats: list[dict[str, Any]] = []
    wanted_classes = np.asarray(ground_classes, dtype=np.int64)

    for item in overlapping:
        lidar = item["path"]
        source_histogram: dict[int, int] = {}
        source_cropped_all = 0
        source_ground_parts: list[np.ndarray] = []

        with laspy.open(lidar) as reader:
            for chunk in reader.chunk_iterator(chunk_size):
                x = np.asarray(chunk.x, dtype=np.float64)
                y = np.asarray(chunk.y, dtype=np.float64)
                in_crop = (
                    (x >= min_x)
                    & (x <= max_x)
                    & (y >= min_y)
                    & (y <= max_y)
                )
                if not np.any(in_crop):
                    continue
                z = np.asarray(chunk.z, dtype=np.float64)[in_crop]
                cls = np.asarray(chunk.classification, dtype=np.uint8)[in_crop]
                x = x[in_crop]
                y = y[in_crop]
                source_cropped_all += len(x)
                vals, counts = np.unique(cls.astype(np.int64), return_counts=True)
                for val, count in zip(vals.tolist(), counts.tolist(), strict=True):
                    source_histogram[int(val)] = (
                        source_histogram.get(int(val), 0) + int(count)
                    )
                    histogram[int(val)] = histogram.get(int(val), 0) + int(count)
                keep = np.isin(cls.astype(np.int64), wanted_classes)
                if np.any(keep):
                    source_ground_parts.append(
                        np.column_stack((x[keep], y[keep], z[keep]))
                    )

        cropped_all += source_cropped_all
        if source_ground_parts:
            xyz_parts.extend(source_ground_parts)
        source_stats.append(
            {
                "lidar_path": str(lidar),
                "file_size_bytes": int(lidar.stat().st_size),
                "header_bounds_xy": {
                    "min_x": item["bounds"][0],
                    "min_y": item["bounds"][1],
                    "max_x": item["bounds"][2],
                    "max_y": item["bounds"][3],
                },
                "crop_overlap_ratio": float(item["overlap_ratio"]),
                "cropped_all_point_count": int(source_cropped_all),
                "classification_histogram": {
                    str(k): v for k, v in sorted(source_histogram.items())
                },
            }
        )

    if not xyz_parts:
        raise ValueError("no requested ground classes found in overlapping LiDAR crops")

    xyz_raw = np.concatenate(xyz_parts)
    xyz = _deduplicate_xyz(xyz_raw)
    classes = np.full(len(xyz), ground_classes[0], dtype=np.uint8)

    verts, faces, meta = build_ground_grid(
        xyz,
        classes,
        crop=crop,
        origin_x=float(footprint["origin_x"]),
        origin_y=float(footprint["origin_y"]),
        ground_z=ground_z,
        ground_classes=ground_classes,
        cell_size_m=cell_size_m,
        min_points_per_cell=min_points_per_cell,
        fill_radius_cells=fill_radius_cells,
        fill_min_neighbors=fill_min_neighbors,
        fill_min_directions=fill_min_directions,
        fill_max_z_span_m=fill_max_z_span_m,
    )
    meta.update(
        {
            "schema_version": 3,
            "method": "multi-source ground grid with measured medians and conservative local-plane gap fill",
            "source": {
                "lidar_paths": [str(item["path"]) for item in overlapping],
                "candidate_count": len(candidates),
                "overlapping_source_count": len(overlapping),
                "cropped_all_point_count": int(cropped_all),
                "raw_ground_point_count_before_dedup": int(len(xyz_raw)),
                "deduplicated_ground_point_count": int(len(xyz)),
                "classification_histogram": {
                    str(k): v for k, v in sorted(histogram.items())
                },
                "sources": source_stats,
                "footprint_path": str(footprint_json),
                "horizontal_crs": footprint.get("target_crs"),
            },
            "georeference": {
                "origin_x": float(footprint["origin_x"]),
                "origin_y": float(footprint["origin_y"]),
                "ground_z": ground_z,
                "local_axes": "X east / Y north / Z up",
            },
            "parameters": {
                "margin_m": margin_m,
                "cell_size_m": cell_size_m,
                "ground_classes": list(ground_classes),
                "min_points_per_cell": min_points_per_cell,
                "fill_radius_cells": fill_radius_cells,
                "fill_min_neighbors": fill_min_neighbors,
                "fill_min_directions": fill_min_directions,
                "fill_max_z_span_m": fill_max_z_span_m,
            },
            "crop_abs_xy": {
                "min_x": min_x,
                "min_y": min_y,
                "max_x": max_x,
                "max_y": max_y,
            },
        }
    )
    if len(verts):
        meta["mesh"].update(
            {
                "local_z_min_m": float(verts[:, 2].min()),
                "local_z_max_m": float(verts[:, 2].max()),
            }
        )
    return verts, faces, meta


def build_from_lidar(
    lidar: Path,
    footprint_json: Path,
    *,
    ground_z: float,
    margin_m: float,
    cell_size_m: float,
    ground_classes: tuple[int, ...],
    min_points_per_cell: int,
    chunk_size: int,
    fill_radius_cells: int = 0,
    fill_min_neighbors: int = 4,
    fill_min_directions: int = 3,
    fill_max_z_span_m: float = 0.6,
) -> tuple[np.ndarray, np.ndarray, dict]:
    return build_from_lidars(
        (lidar,),
        footprint_json,
        ground_z=ground_z,
        margin_m=margin_m,
        cell_size_m=cell_size_m,
        ground_classes=ground_classes,
        min_points_per_cell=min_points_per_cell,
        chunk_size=chunk_size,
        fill_radius_cells=fill_radius_cells,
        fill_min_neighbors=fill_min_neighbors,
        fill_min_directions=fill_min_directions,
        fill_max_z_span_m=fill_max_z_span_m,
    )


def write_obj(vertices: np.ndarray, faces: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# BatiForge context ground; local metric XYZ\n")
        for x, y, z in vertices:
            f.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
        for a, b, c in faces:
            f.write(f"f {a + 1} {b + 1} {c + 1}\n")


def write_ply(vertices: np.ndarray, faces: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("ply\nformat ascii 1.0\n")
        f.write(
            f"element vertex {len(vertices)}\n"
            "property float x\nproperty float y\nproperty float z\n"
        )
        f.write(
            f"element face {len(faces)}\n"
            "property list uchar int vertex_indices\nend_header\n"
        )
        for x, y, z in vertices:
            f.write(f"{x:.6f} {y:.6f} {z:.6f}\n")
        for a, b, c in faces:
            f.write(f"3 {a} {b} {c}\n")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Build wider ground/parking context from classified LiDAR"
    )
    p.add_argument("--lidar", type=Path, action="append", required=True)
    p.add_argument("--footprint-json", type=Path, required=True)
    p.add_argument("--ground-z", type=float, required=True)
    p.add_argument("--margin-m", type=float, default=25.0)
    p.add_argument("--cell-size-m", type=float, default=0.5)
    p.add_argument("--ground-class", type=int, action="append", dest="ground_classes")
    p.add_argument("--min-points-per-cell", type=int, default=1)
    p.add_argument("--chunk-size", type=int, default=1_000_000)
    p.add_argument("--fill-radius-cells", type=int, default=0)
    p.add_argument("--fill-min-neighbors", type=int, default=4)
    p.add_argument("--fill-min-directions", type=int, default=3)
    p.add_argument("--fill-max-z-span-m", type=float, default=0.6)
    p.add_argument("--output-json", type=Path, required=True)
    p.add_argument("--output-obj", type=Path, required=True)
    p.add_argument("--output-ply", type=Path, required=True)
    args = p.parse_args()

    vertices, faces, meta = build_from_lidars(
        tuple(args.lidar),
        args.footprint_json,
        ground_z=args.ground_z,
        margin_m=args.margin_m,
        cell_size_m=args.cell_size_m,
        ground_classes=tuple(args.ground_classes or [2]),
        min_points_per_cell=args.min_points_per_cell,
        chunk_size=args.chunk_size,
        fill_radius_cells=args.fill_radius_cells,
        fill_min_neighbors=args.fill_min_neighbors,
        fill_min_directions=args.fill_min_directions,
        fill_max_z_span_m=args.fill_max_z_span_m,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_obj(vertices, faces, args.output_obj)
    write_ply(vertices, faces, args.output_ply)
    grid = meta["grid"]
    print(
        "context ground: "
        f"sources={meta['source']['overlapping_source_count']} "
        f"points={meta['ground_point_count']} "
        f"measured={grid['measured_cell_count']} "
        f"inferred={grid['inferred_cell_count']} "
        f"cells={grid['occupied_cell_count']}/{grid['cell_count']} "
        f"coverage={grid['coverage_ratio']:.3f} "
        f"vertices={len(vertices)} faces={len(faces)}"
    )
    print(f"json: {args.output_json}")
    print(f"obj: {args.output_obj}")
    print(f"ply: {args.output_ply}")


if __name__ == "__main__":
    main()
