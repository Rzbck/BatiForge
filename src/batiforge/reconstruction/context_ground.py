from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import laspy
import numpy as np


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
        & (pts[:, 0] >= min_x) & (pts[:, 0] <= max_x)
        & (pts[:, 1] >= min_y) & (pts[:, 1] <= max_y)
        & np.isin(cls.astype(np.int64), np.asarray(ground_classes, dtype=np.int64))
    )
    ground = pts[mask]
    if not len(ground):
        raise ValueError("no ground-class points found in crop")

    nx = max(1, int(math.ceil((max_x - min_x) / cell_size_m)))
    ny = max(1, int(math.ceil((max_y - min_y) / cell_size_m)))
    ix = np.clip(np.floor((ground[:, 0] - min_x) / cell_size_m).astype(np.int64), 0, nx - 1)
    iy = np.clip(np.floor((ground[:, 1] - min_y) / cell_size_m).astype(np.int64), 0, ny - 1)
    keys = iy * nx + ix
    order = np.argsort(keys, kind="mergesort")
    keys = keys[order]
    zs = ground[:, 2][order]
    unique, starts, counts = np.unique(keys, return_index=True, return_counts=True)

    cell_z: dict[int, float] = {}
    for key, start, count in zip(unique.tolist(), starts.tolist(), counts.tolist(), strict=True):
        if count >= min_points_per_cell:
            cell_z[int(key)] = float(np.median(zs[start:start + count]))
    if not cell_z:
        raise ValueError("no occupied cells pass min_points_per_cell")

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
            q = (row * nx + col, row * nx + col + 1, (row + 1) * nx + col + 1, (row + 1) * nx + col)
            if all(key in indices for key in q):
                a, b, c, d = (indices[key] for key in q)
                faces.extend(((a, b, c), (a, c, d)))

    verts = np.asarray(vertices, dtype=np.float64)
    tris = np.asarray(faces, dtype=np.int64).reshape((-1, 3)) if faces else np.empty((0, 3), dtype=np.int64)
    meta = {
        "ground_point_count": int(len(ground)),
        "grid": {
            "nx": nx,
            "ny": ny,
            "cell_count": nx * ny,
            "occupied_cell_count": len(vertices),
            "coverage_ratio": len(vertices) / (nx * ny),
        },
        "mesh": {"vertex_count": len(vertices), "face_count": len(faces)},
    }
    return verts, tris, meta


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
) -> tuple[np.ndarray, np.ndarray, dict]:
    footprint = json.loads(footprint_json.read_text(encoding="utf-8"))
    b = footprint["bounds"]
    crop = (
        float(b["min_x"]) - margin_m,
        float(b["min_y"]) - margin_m,
        float(b["max_x"]) + margin_m,
        float(b["max_y"]) + margin_m,
    )
    xyz_parts: list[np.ndarray] = []
    cls_parts: list[np.ndarray] = []
    histogram: dict[int, int] = {}
    cropped_all = 0
    min_x, min_y, max_x, max_y = crop

    with laspy.open(lidar) as reader:
        for chunk in reader.chunk_iterator(chunk_size):
            x = np.asarray(chunk.x, dtype=np.float64)
            y = np.asarray(chunk.y, dtype=np.float64)
            in_crop = (x >= min_x) & (x <= max_x) & (y >= min_y) & (y <= max_y)
            if not np.any(in_crop):
                continue
            z = np.asarray(chunk.z, dtype=np.float64)[in_crop]
            cls = np.asarray(chunk.classification, dtype=np.uint8)[in_crop]
            x = x[in_crop]
            y = y[in_crop]
            cropped_all += len(x)
            vals, counts = np.unique(cls.astype(np.int64), return_counts=True)
            for val, count in zip(vals.tolist(), counts.tolist(), strict=True):
                histogram[int(val)] = histogram.get(int(val), 0) + int(count)
            keep = np.isin(cls.astype(np.int64), np.asarray(ground_classes, dtype=np.int64))
            if np.any(keep):
                xyz_parts.append(np.column_stack((x[keep], y[keep], z[keep])))
                cls_parts.append(cls[keep])

    if not xyz_parts:
        raise ValueError("no requested ground classes found in LiDAR crop")
    xyz = np.concatenate(xyz_parts)
    classes = np.concatenate(cls_parts)
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
    )
    meta.update({
        "schema_version": 1,
        "method": "ground-class regular grid with per-cell median elevation",
        "source": {
            "lidar_path": str(lidar),
            "footprint_path": str(footprint_json),
            "horizontal_crs": footprint.get("target_crs"),
            "cropped_all_point_count": cropped_all,
            "classification_histogram": {str(k): v for k, v in sorted(histogram.items())},
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
        },
        "crop_abs_xy": {"min_x": min_x, "min_y": min_y, "max_x": max_x, "max_y": max_y},
    })
    if len(verts):
        meta["mesh"].update({"local_z_min_m": float(verts[:, 2].min()), "local_z_max_m": float(verts[:, 2].max())})
    return verts, faces, meta


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
        f.write(f"element vertex {len(vertices)}\nproperty float x\nproperty float y\nproperty float z\n")
        f.write(f"element face {len(faces)}\nproperty list uchar int vertex_indices\nend_header\n")
        for x, y, z in vertices:
            f.write(f"{x:.6f} {y:.6f} {z:.6f}\n")
        for a, b, c in faces:
            f.write(f"3 {a} {b} {c}\n")


def main() -> None:
    p = argparse.ArgumentParser(description="Build wider ground/parking context from classified LiDAR")
    p.add_argument("--lidar", type=Path, required=True)
    p.add_argument("--footprint-json", type=Path, required=True)
    p.add_argument("--ground-z", type=float, required=True)
    p.add_argument("--margin-m", type=float, default=25.0)
    p.add_argument("--cell-size-m", type=float, default=0.5)
    p.add_argument("--ground-class", type=int, action="append", dest="ground_classes")
    p.add_argument("--min-points-per-cell", type=int, default=1)
    p.add_argument("--chunk-size", type=int, default=1_000_000)
    p.add_argument("--output-json", type=Path, required=True)
    p.add_argument("--output-obj", type=Path, required=True)
    p.add_argument("--output-ply", type=Path, required=True)
    args = p.parse_args()

    vertices, faces, meta = build_from_lidar(
        args.lidar,
        args.footprint_json,
        ground_z=args.ground_z,
        margin_m=args.margin_m,
        cell_size_m=args.cell_size_m,
        ground_classes=tuple(args.ground_classes or [2]),
        min_points_per_cell=args.min_points_per_cell,
        chunk_size=args.chunk_size,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_obj(vertices, faces, args.output_obj)
    write_ply(vertices, faces, args.output_ply)
    grid = meta["grid"]
    print(f"context ground: points={meta['ground_point_count']} cells={grid['occupied_cell_count']}/{grid['cell_count']} coverage={grid['coverage_ratio']:.3f} vertices={len(vertices)} faces={len(faces)}")
    print(f"json: {args.output_json}")
    print(f"obj: {args.output_obj}")
    print(f"ply: {args.output_ply}")


if __name__ == "__main__":
    main()
