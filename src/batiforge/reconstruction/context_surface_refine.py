from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from batiforge.reconstruction.context_ground import write_obj, write_ply


def _shifted(values: np.ndarray, dy: int, dx: int) -> np.ndarray:
    padded = np.pad(values, 1, mode="constant", constant_values=np.nan)
    return padded[
        1 + dy : 1 + dy + values.shape[0],
        1 + dx : 1 + dx + values.shape[1],
    ]


def roughness_stats(values: np.ndarray) -> dict[str, float]:
    z = np.asarray(values, dtype=np.float64)
    if z.ndim != 2 or not z.size or not np.isfinite(z).all():
        raise ValueError("values must be a finite non-empty 2D grid")

    total = np.zeros_like(z)
    count = np.zeros_like(z, dtype=np.int16)
    for dy, dx in ((-1, 0), (0, -1), (0, 1), (1, 0)):
        neighbour = _shifted(z, dy, dx)
        valid = np.isfinite(neighbour)
        total[valid] += neighbour[valid]
        count[valid] += 1

    valid = count > 0
    mean = np.zeros_like(z)
    mean[valid] = total[valid] / count[valid]
    residual = np.abs(z[valid] - mean[valid])
    if not residual.size:
        return {"median_m": 0.0, "p90_m": 0.0, "p95_m": 0.0, "max_m": 0.0}
    return {
        "median_m": float(np.median(residual)),
        "p90_m": float(np.quantile(residual, 0.90)),
        "p95_m": float(np.quantile(residual, 0.95)),
        "max_m": float(residual.max()),
    }


def refine_surface_grid(
    values: np.ndarray,
    *,
    iterations: int = 12,
    strength: float = 0.65,
    sigma_z_m: float = 0.30,
    max_delta_m: float = 0.30,
) -> tuple[np.ndarray, dict[str, Any]]:
    if iterations < 0:
        raise ValueError("iterations must be >= 0")
    if not 0.0 <= strength <= 1.0:
        raise ValueError("strength must be between 0 and 1")
    if sigma_z_m <= 0:
        raise ValueError("sigma_z_m must be > 0")
    if max_delta_m < 0:
        raise ValueError("max_delta_m must be >= 0")

    original = np.asarray(values, dtype=np.float64)
    if original.ndim != 2 or not original.size or not np.isfinite(original).all():
        raise ValueError("values must be a finite non-empty 2D grid")

    current = original.copy()
    before = roughness_stats(original)
    offsets = (
        (-1, -1), (-1, 0), (-1, 1),
        (0, -1),             (0, 1),
        (1, -1),  (1, 0),   (1, 1),
    )

    for _ in range(iterations):
        numerator = current.copy()
        denominator = np.ones_like(current)
        for dy, dx in offsets:
            neighbour = _shifted(current, dy, dx)
            valid = np.isfinite(neighbour)
            if not np.any(valid):
                continue
            distance = math.sqrt(float(dx * dx + dy * dy))
            spatial_weight = math.exp(-0.5 * (distance / 1.25) ** 2)
            dz = neighbour - current
            range_weight = np.exp(-0.5 * (dz / sigma_z_m) ** 2)
            weight = spatial_weight * range_weight
            weight[~valid] = 0.0
            numerator += weight * np.nan_to_num(neighbour, nan=0.0)
            denominator += weight

        target = numerator / denominator
        current = (1.0 - strength) * current + strength * target
        if max_delta_m > 0:
            current = np.clip(current, original - max_delta_m, original + max_delta_m)
        else:
            current = original.copy()

    displacement = current - original
    after = roughness_stats(current)
    metrics = {
        "roughness_before": before,
        "roughness_after": after,
        "displacement": {
            "rms_m": float(np.sqrt(np.mean(displacement ** 2))),
            "median_abs_m": float(np.median(np.abs(displacement))),
            "p95_abs_m": float(np.quantile(np.abs(displacement), 0.95)),
            "max_abs_m": float(np.max(np.abs(displacement))),
        },
        "parameters": {
            "iterations": iterations,
            "strength": strength,
            "sigma_z_m": sigma_z_m,
            "max_delta_m": max_delta_m,
        },
    }
    return current, metrics


def read_regular_obj(path: Path) -> tuple[np.ndarray, np.ndarray]:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("v "):
            p = line.split()
            if len(p) < 4:
                raise ValueError(f"invalid OBJ vertex: {raw}")
            vertices.append((float(p[1]), float(p[2]), float(p[3])))
        elif line.startswith("f "):
            refs = line.split()[1:]
            if len(refs) != 3:
                raise ValueError("refinement expects triangular context OBJ faces")
            face = tuple(int(ref.split("/", 1)[0]) - 1 for ref in refs)
            if min(face) < 0:
                raise ValueError("OBJ face indices must be positive")
            faces.append(face)
    if not vertices or not faces:
        raise ValueError("source OBJ has no vertices/faces")
    return np.asarray(vertices, dtype=np.float64), np.asarray(faces, dtype=np.int64)


def refine_surface(
    source_json: Path,
    source_obj: Path,
    *,
    iterations: int,
    strength: float,
    sigma_z_m: float,
    max_delta_m: float,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    source_meta = json.loads(source_json.read_text(encoding="utf-8"))
    grid = source_meta.get("grid")
    if not isinstance(grid, dict):
        raise ValueError("source metadata has no grid")
    nx = int(grid["nx"])
    ny = int(grid["ny"])
    vertices, faces = read_regular_obj(source_obj)
    if len(vertices) != nx * ny:
        raise ValueError(
            f"vertex count {len(vertices)} does not match regular grid {nx}x{ny}"
        )

    z = vertices[:, 2].reshape(ny, nx)
    refined_z, metrics = refine_surface_grid(
        z,
        iterations=iterations,
        strength=strength,
        sigma_z_m=sigma_z_m,
        max_delta_m=max_delta_m,
    )
    refined = vertices.copy()
    refined[:, 2] = refined_z.reshape(-1)

    meta = dict(source_meta)
    meta["schema_version"] = 2
    meta["method"] = (
        "continuous DTM render refinement with deterministic edge-aware bilateral Z smoothing"
    )
    meta["source_surface_json"] = str(source_json)
    meta["source_surface_obj"] = str(source_obj)
    meta["refinement"] = metrics
    meta["mesh"] = {
        **dict(source_meta.get("mesh") or {}),
        "vertex_count": int(len(refined)),
        "face_count": int(len(faces)),
        "local_z_min_m": float(refined[:, 2].min()),
        "local_z_max_m": float(refined[:, 2].max()),
    }
    return refined, faces, meta


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refine a continuous BatiForge context surface for clean rendering"
    )
    parser.add_argument("--source-json", type=Path, required=True)
    parser.add_argument("--source-obj", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=12)
    parser.add_argument("--strength", type=float, default=0.65)
    parser.add_argument("--sigma-z-m", type=float, default=0.30)
    parser.add_argument("--max-delta-m", type=float, default=0.30)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-obj", type=Path, required=True)
    parser.add_argument("--output-ply", type=Path, required=True)
    args = parser.parse_args()

    vertices, faces, meta = refine_surface(
        args.source_json,
        args.source_obj,
        iterations=args.iterations,
        strength=args.strength,
        sigma_z_m=args.sigma_z_m,
        max_delta_m=args.max_delta_m,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_obj(vertices, faces, args.output_obj)
    write_ply(vertices, faces, args.output_ply)

    r = meta["refinement"]
    print(
        "context surface refine: "
        f"vertices={len(vertices)} faces={len(faces)} "
        f"rough_p90={r['roughness_before']['p90_m']:.4f}->{r['roughness_after']['p90_m']:.4f}m "
        f"disp_rms={r['displacement']['rms_m']:.4f}m "
        f"disp_max={r['displacement']['max_abs_m']:.4f}m"
    )
    print(f"json: {args.output_json}")
    print(f"obj: {args.output_obj}")
    print(f"ply: {args.output_ply}")


if __name__ == "__main__":
    main()
