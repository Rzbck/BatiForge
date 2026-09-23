from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterable

import laspy
import numpy as np

from batiforge.reconstruction.context_ground import (
    _bounds_overlap_ratio,
    _deduplicate_xyz,
    _footprint_crop,
    lidar_header_bounds,
    write_obj,
    write_ply,
)


def _neighbor_mean(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    padded = np.pad(values, 1, mode="constant", constant_values=np.nan)
    total = np.zeros_like(values, dtype=np.float64)
    count = np.zeros_like(values, dtype=np.int16)
    for dy, dx in (
        (-1, -1), (-1, 0), (-1, 1),
        (0, -1),             (0, 1),
        (1, -1),  (1, 0),   (1, 1),
    ):
        neighbour = padded[
            1 + dy : 1 + dy + values.shape[0],
            1 + dx : 1 + dx + values.shape[1],
        ]
        valid = np.isfinite(neighbour)
        total[valid] += neighbour[valid]
        count[valid] += 1
    mean = np.full_like(values, np.nan, dtype=np.float64)
    valid = count > 0
    mean[valid] = total[valid] / count[valid]
    return mean, count


def build_continuous_grid(
    xyz: np.ndarray,
    *,
    crop: tuple[float, float, float, float],
    origin_x: float,
    origin_y: float,
    ground_z: float,
    cell_size_m: float = 0.5,
    relax_iterations: int = 80,
    relax_weight: float = 0.65,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    if cell_size_m <= 0:
        raise ValueError("cell_size_m must be > 0")
    if relax_iterations < 0:
        raise ValueError("relax_iterations must be >= 0")
    if not 0.0 <= relax_weight <= 1.0:
        raise ValueError("relax_weight must be between 0 and 1")

    pts = np.asarray(xyz, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 3 or not len(pts):
        raise ValueError("xyz must be a non-empty Nx3 array")

    min_x, min_y, max_x, max_y = map(float, crop)
    nx = max(1, int(math.ceil((max_x - min_x) / cell_size_m)))
    ny = max(1, int(math.ceil((max_y - min_y) / cell_size_m)))

    inside = (
        np.isfinite(pts).all(axis=1)
        & (pts[:, 0] >= min_x)
        & (pts[:, 0] <= max_x)
        & (pts[:, 1] >= min_y)
        & (pts[:, 1] <= max_y)
    )
    pts = pts[inside]
    if not len(pts):
        raise ValueError("no ground points inside crop")

    ix = np.clip(
        np.floor((pts[:, 0] - min_x) / cell_size_m).astype(np.int64), 0, nx - 1
    )
    iy = np.clip(
        np.floor((pts[:, 1] - min_y) / cell_size_m).astype(np.int64), 0, ny - 1
    )
    keys = iy * nx + ix
    order = np.argsort(keys, kind="mergesort")
    keys = keys[order]
    zs = pts[:, 2][order]
    unique, starts, counts = np.unique(keys, return_index=True, return_counts=True)

    measured = np.full((ny, nx), np.nan, dtype=np.float64)
    for key, start, count in zip(
        unique.tolist(), starts.tolist(), counts.tolist(), strict=True
    ):
        row, col = divmod(int(key), nx)
        measured[row, col] = float(np.median(zs[start : start + count]))

    measured_mask = np.isfinite(measured)
    measured_count = int(measured_mask.sum())
    if measured_count == 0:
        raise ValueError("no measured ground cells")

    surface = measured.copy()
    fill_distance = np.full((ny, nx), -1, dtype=np.int32)
    fill_distance[measured_mask] = 0

    max_steps = nx + ny + 4
    for step in range(1, max_steps + 1):
        missing = ~np.isfinite(surface)
        if not np.any(missing):
            break
        mean, neighbour_count = _neighbor_mean(surface)
        fillable = missing & (neighbour_count > 0) & np.isfinite(mean)
        if not np.any(fillable):
            break
        surface[fillable] = mean[fillable]
        fill_distance[fillable] = step

    if np.any(~np.isfinite(surface)):
        raise RuntimeError("continuous surface propagation did not reach all grid cells")

    inferred_mask = ~measured_mask
    for _ in range(relax_iterations):
        mean, neighbour_count = _neighbor_mean(surface)
        update = inferred_mask & (neighbour_count > 0) & np.isfinite(mean)
        surface[update] = (
            (1.0 - relax_weight) * surface[update]
            + relax_weight * mean[update]
        )
        surface[measured_mask] = measured[measured_mask]

    vertices: list[tuple[float, float, float]] = []
    for row in range(ny):
        y = min_y + (row + 0.5) * cell_size_m
        for col in range(nx):
            x = min_x + (col + 0.5) * cell_size_m
            vertices.append((x - origin_x, y - origin_y, surface[row, col] - ground_z))

    faces: list[tuple[int, int, int]] = []
    for row in range(ny - 1):
        for col in range(nx - 1):
            a = row * nx + col
            b = a + 1
            d = (row + 1) * nx + col
            c = d + 1
            faces.extend(((a, b, c), (a, c, d)))

    verts = np.asarray(vertices, dtype=np.float64)
    tris = np.asarray(faces, dtype=np.int64).reshape((-1, 3))
    inferred_count = int(inferred_mask.sum())
    meta = {
        "grid": {
            "nx": nx,
            "ny": ny,
            "cell_count": nx * ny,
            "measured_cell_count": measured_count,
            "inferred_cell_count": inferred_count,
            "measured_coverage_ratio": measured_count / (nx * ny),
            "final_coverage_ratio": 1.0,
            "max_fill_distance_cells": int(fill_distance.max()),
            "max_fill_distance_m": float(fill_distance.max() * cell_size_m),
        },
        "mesh": {
            "vertex_count": len(verts),
            "face_count": len(tris),
            "local_z_min_m": float(verts[:, 2].min()),
            "local_z_max_m": float(verts[:, 2].max()),
        },
        "parameters": {
            "cell_size_m": cell_size_m,
            "relax_iterations": relax_iterations,
            "relax_weight": relax_weight,
        },
    }
    return verts, tris, meta


def collect_ground_points(
    lidars: Iterable[Path],
    crop: tuple[float, float, float, float],
    *,
    ground_classes: tuple[int, ...] = (2,),
    chunk_size: int = 1_000_000,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    min_x, min_y, max_x, max_y = crop
    wanted = np.asarray(ground_classes, dtype=np.int64)
    parts: list[np.ndarray] = []
    source_stats: list[dict[str, Any]] = []

    for lidar in dict.fromkeys(Path(path) for path in lidars):
        bounds = lidar_header_bounds(lidar)
        overlap = _bounds_overlap_ratio(bounds, crop)
        if overlap <= 0.0:
            continue

        source_total = 0
        source_ground = 0
        with laspy.open(lidar) as reader:
            for chunk in reader.chunk_iterator(chunk_size):
                x = np.asarray(chunk.x, dtype=np.float64)
                y = np.asarray(chunk.y, dtype=np.float64)
                mask = (
                    (x >= min_x) & (x <= max_x)
                    & (y >= min_y) & (y <= max_y)
                )
                if not np.any(mask):
                    continue
                x = x[mask]
                y = y[mask]
                z = np.asarray(chunk.z, dtype=np.float64)[mask]
                cls = np.asarray(chunk.classification, dtype=np.uint8)[mask]
                source_total += len(x)
                keep = np.isin(cls.astype(np.int64), wanted)
                if np.any(keep):
                    xyz = np.column_stack((x[keep], y[keep], z[keep]))
                    parts.append(xyz)
                    source_ground += len(xyz)

        source_stats.append(
            {
                "lidar_path": str(lidar),
                "crop_overlap_ratio": float(overlap),
                "cropped_all_point_count": int(source_total),
                "ground_point_count": int(source_ground),
            }
        )

    if not parts:
        raise ValueError("no requested ground-class points found in overlapping LiDAR sources")
    return _deduplicate_xyz(np.concatenate(parts)), source_stats


def build_from_lidars(
    lidars: Iterable[Path],
    footprint_json: Path,
    *,
    ground_z: float,
    margin_m: float = 25.0,
    cell_size_m: float = 0.5,
    ground_classes: tuple[int, ...] = (2,),
    chunk_size: int = 1_000_000,
    relax_iterations: int = 80,
    relax_weight: float = 0.65,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    footprint = json.loads(footprint_json.read_text(encoding="utf-8"))
    crop = _footprint_crop(footprint, margin_m)
    xyz, source_stats = collect_ground_points(
        lidars,
        crop,
        ground_classes=ground_classes,
        chunk_size=chunk_size,
    )
    verts, faces, meta = build_continuous_grid(
        xyz,
        crop=crop,
        origin_x=float(footprint["origin_x"]),
        origin_y=float(footprint["origin_y"]),
        ground_z=ground_z,
        cell_size_m=cell_size_m,
        relax_iterations=relax_iterations,
        relax_weight=relax_weight,
    )
    meta.update(
        {
            "schema_version": 1,
            "method": "continuous DTM from measured class-2 cell medians with deterministic neighbour fill and inferred-cell relaxation",
            "source": {
                "lidar_paths": [item["lidar_path"] for item in source_stats],
                "source_count": len(source_stats),
                "deduplicated_ground_point_count": int(len(xyz)),
                "sources": source_stats,
                "footprint_path": str(footprint_json),
                "horizontal_crs": footprint.get("target_crs"),
            },
            "georeference": {
                "origin_x": float(footprint["origin_x"]),
                "origin_y": float(footprint["origin_y"]),
                "ground_z": float(ground_z),
                "local_axes": "X east / Y north / Z up",
            },
            "crop_abs_xy": {
                "min_x": crop[0],
                "min_y": crop[1],
                "max_x": crop[2],
                "max_y": crop[3],
            },
            "parameters": {
                **meta["parameters"],
                "margin_m": margin_m,
                "ground_classes": list(ground_classes),
            },
        }
    )
    return verts, faces, meta


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a continuous renderable context DTM from official classified LiDAR")
    parser.add_argument("--lidar", type=Path, action="append", required=True)
    parser.add_argument("--footprint-json", type=Path, required=True)
    parser.add_argument("--ground-z", type=float, required=True)
    parser.add_argument("--margin-m", type=float, default=25.0)
    parser.add_argument("--cell-size-m", type=float, default=0.5)
    parser.add_argument("--ground-class", type=int, action="append", dest="ground_classes")
    parser.add_argument("--chunk-size", type=int, default=1_000_000)
    parser.add_argument("--relax-iterations", type=int, default=80)
    parser.add_argument("--relax-weight", type=float, default=0.65)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-obj", type=Path, required=True)
    parser.add_argument("--output-ply", type=Path, required=True)
    args = parser.parse_args()

    vertices, faces, meta = build_from_lidars(
        tuple(args.lidar),
        args.footprint_json,
        ground_z=args.ground_z,
        margin_m=args.margin_m,
        cell_size_m=args.cell_size_m,
        ground_classes=tuple(args.ground_classes or [2]),
        chunk_size=args.chunk_size,
        relax_iterations=args.relax_iterations,
        relax_weight=args.relax_weight,
    )

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_obj(vertices, faces, args.output_obj)
    write_ply(vertices, faces, args.output_ply)

    grid = meta["grid"]
    print(
        "context surface: "
        f"sources={meta['source']['source_count']} "
        f"ground={meta['source']['deduplicated_ground_point_count']} "
        f"measured={grid['measured_cell_count']} inferred={grid['inferred_cell_count']} "
        f"coverage={grid['final_coverage_ratio']:.3f} "
        f"vertices={meta['mesh']['vertex_count']} faces={meta['mesh']['face_count']}"
    )
    print(f"json: {args.output_json}")
    print(f"obj: {args.output_obj}")
    print(f"ply: {args.output_ply}")


if __name__ == "__main__":
    main()
