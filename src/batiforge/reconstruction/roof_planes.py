from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import laspy
import numpy as np


@dataclass(frozen=True, slots=True)
class RoofPlane:
    index: int
    point_count: int
    rmse_m: float
    area_m2: float
    slope_deg: float
    aspect_downslope_deg: float
    a: float
    b: float
    c: float
    normal_x: float
    normal_y: float
    normal_z: float
    hull_local_xy: tuple[tuple[float, float], ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["hull_local_xy"] = [list(point) for point in self.hull_local_xy]
        return payload


@dataclass(frozen=True, slots=True)
class RoofAnalysis:
    origin_x: float
    origin_y: float
    ground_z: float
    horizontal_crs: str
    vertical_datum: str
    source_point_count: int
    roof_candidate_count: int
    assigned_point_count: int
    unassigned_point_count: int
    coverage_ratio: float
    min_height_m: float
    residual_threshold_m: float
    planes: tuple[RoofPlane, ...]
    z_above_ground_quantiles_m: dict[str, float]
    high_structure_counts: dict[str, int]
    bounds: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "georeference": {
                "origin_x": self.origin_x,
                "origin_y": self.origin_y,
                "ground_z": self.ground_z,
                "horizontal_crs": self.horizontal_crs,
                "vertical_datum": self.vertical_datum,
                "local_axes": "X east / Y north / Z up",
                "plane_equation": "z_abs = a*(x_abs-origin_x) + b*(y_abs-origin_y) + c",
            },
            "source_point_count": self.source_point_count,
            "roof_candidate_count": self.roof_candidate_count,
            "assigned_point_count": self.assigned_point_count,
            "unassigned_point_count": self.unassigned_point_count,
            "coverage_ratio": self.coverage_ratio,
            "parameters": {
                "min_height_m": self.min_height_m,
                "residual_threshold_m": self.residual_threshold_m,
            },
            "z_above_ground_quantiles_m": self.z_above_ground_quantiles_m,
            "high_structure_counts": self.high_structure_counts,
            "bounds": self.bounds,
            "plane_count": len(self.planes),
            "planes": [plane.to_dict() for plane in self.planes],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def _plane_from_three(points: np.ndarray) -> tuple[float, float, float] | None:
    matrix = np.column_stack((points[:, 0], points[:, 1], np.ones(3)))
    if abs(float(np.linalg.det(matrix))) < 1e-9:
        return None
    try:
        a, b, c = np.linalg.solve(matrix, points[:, 2])
    except np.linalg.LinAlgError:
        return None
    return float(a), float(b), float(c)


def _fit_plane_lstsq(points: np.ndarray) -> tuple[float, float, float]:
    matrix = np.column_stack((points[:, 0], points[:, 1], np.ones(len(points))))
    coeffs, _, _, _ = np.linalg.lstsq(matrix, points[:, 2], rcond=None)
    return float(coeffs[0]), float(coeffs[1]), float(coeffs[2])


def _plane_residuals(points: np.ndarray, plane: tuple[float, float, float]) -> np.ndarray:
    a, b, c = plane
    return np.abs(points[:, 2] - (a * points[:, 0] + b * points[:, 1] + c))


def _slope_deg(a: float, b: float) -> float:
    return math.degrees(math.atan(math.hypot(a, b)))


def _normal(a: float, b: float) -> tuple[float, float, float]:
    vector = np.asarray([-a, -b, 1.0], dtype=np.float64)
    vector /= np.linalg.norm(vector)
    return float(vector[0]), float(vector[1]), float(vector[2])


def _aspect_downslope_deg(a: float, b: float) -> float:
    if abs(a) < 1e-12 and abs(b) < 1e-12:
        return 0.0
    # Lambert-93 X is east and Y is north. atan2(east, north) gives bearing.
    return (math.degrees(math.atan2(-a, -b)) + 360.0) % 360.0


def _convex_hull_xy(points_xy: np.ndarray) -> tuple[tuple[float, float], ...]:
    unique = sorted({(float(x), float(y)) for x, y in points_xy})
    if len(unique) <= 2:
        return tuple(unique)

    def cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0.0:
            lower.pop()
        lower.append(point)

    upper: list[tuple[float, float]] = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0.0:
            upper.pop()
        upper.append(point)

    return tuple(lower[:-1] + upper[:-1])


def _polygon_area(points: Iterable[tuple[float, float]]) -> float:
    polygon = list(points)
    if len(polygon) < 3:
        return 0.0
    area = 0.0
    for index, current in enumerate(polygon):
        nxt = polygon[(index + 1) % len(polygon)]
        area += current[0] * nxt[1] - nxt[0] * current[1]
    return abs(area) * 0.5


def analyze_roof_planes(
    xyz: np.ndarray,
    *,
    ground_z: float,
    horizontal_crs: str = "EPSG:2154",
    vertical_datum: str = "IGN69",
    min_height_m: float = 2.0,
    residual_threshold_m: float = 0.18,
    min_plane_points: int = 250,
    min_plane_area_m2: float = 1.0,
    max_planes: int = 16,
    max_slope_deg: float = 75.0,
    ransac_iterations: int = 600,
    seed: int = 20260922,
) -> RoofAnalysis:
    """Fit deterministic roof-like planes to a georeferenced building point cloud.

    The fitter deliberately models surfaces as ``z=f(x,y)`` and rejects slopes
    above ``max_slope_deg``. That makes it useful for aerial LiDAR roof/upper
    structure evidence while avoiding accidental facade fitting.

    This stage does not invent missing geometry and does not claim to produce a
    final watertight building. It produces metric roof patches that can later be
    intersected with the authoritative footprint and assembled into a shell.
    """

    points = np.asarray(xyz, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("xyz must be an Nx3 array")
    if len(points) < 3:
        raise ValueError("xyz must contain at least 3 points")
    if residual_threshold_m <= 0.0:
        raise ValueError("residual_threshold_m must be > 0")
    if min_plane_points < 3:
        raise ValueError("min_plane_points must be >= 3")
    if max_planes <= 0 or ransac_iterations <= 0:
        raise ValueError("max_planes and ransac_iterations must be > 0")

    finite = np.isfinite(points).all(axis=1)
    points = points[finite]
    if len(points) < 3:
        raise ValueError("not enough finite points")

    origin_x = float(np.median(points[:, 0]))
    origin_y = float(np.median(points[:, 1]))

    local = points.copy()
    local[:, 0] -= origin_x
    local[:, 1] -= origin_y

    z_above = points[:, 2] - float(ground_z)
    candidate_mask = z_above >= float(min_height_m)
    candidate_indices = np.flatnonzero(candidate_mask)
    candidate_points = local[candidate_mask]

    if len(candidate_points) < 3:
        candidate_points = np.empty((0, 3), dtype=np.float64)

    rng = np.random.default_rng(seed)
    remaining = np.arange(len(candidate_points), dtype=np.int64)
    planes: list[RoofPlane] = []
    assigned_count = 0

    while len(remaining) >= min_plane_points and len(planes) < max_planes:
        active = candidate_points[remaining]
        best_mask: np.ndarray | None = None
        best_plane: tuple[float, float, float] | None = None
        best_count = 0
        best_rmse = float("inf")

        for _ in range(ransac_iterations):
            sample_rows = rng.choice(len(active), size=3, replace=False)
            plane = _plane_from_three(active[sample_rows])
            if plane is None:
                continue
            if _slope_deg(plane[0], plane[1]) > max_slope_deg:
                continue

            residuals = _plane_residuals(active, plane)
            mask = residuals <= residual_threshold_m
            count = int(mask.sum())
            if count < min_plane_points:
                continue
            rmse = float(np.sqrt(np.mean(residuals[mask] ** 2)))
            if count > best_count or (count == best_count and rmse < best_rmse):
                best_mask = mask
                best_plane = plane
                best_count = count
                best_rmse = rmse

        if best_mask is None or best_plane is None:
            break

        # Refine twice because least-squares fitting can pull the inlier boundary.
        refined_mask = best_mask
        refined_plane = best_plane
        for _ in range(2):
            refined_plane = _fit_plane_lstsq(active[refined_mask])
            if _slope_deg(refined_plane[0], refined_plane[1]) > max_slope_deg:
                refined_mask = np.zeros(len(active), dtype=bool)
                break
            residuals = _plane_residuals(active, refined_plane)
            refined_mask = residuals <= residual_threshold_m
            if int(refined_mask.sum()) < min_plane_points:
                break

        inlier_count = int(refined_mask.sum())
        if inlier_count < min_plane_points:
            break

        inliers = active[refined_mask]
        a, b, c = refined_plane
        residuals = _plane_residuals(inliers, refined_plane)
        hull = _convex_hull_xy(inliers[:, :2])
        area = _polygon_area(hull)

        # A tiny dense cluster is not a roof patch. Consume it so it cannot
        # repeatedly win RANSAC, then continue looking for larger surfaces.
        if len(hull) < 3 or area < min_plane_area_m2:
            remaining = remaining[~refined_mask]
            continue

        normal_x, normal_y, normal_z = _normal(a, b)
        planes.append(
            RoofPlane(
                index=len(planes) + 1,
                point_count=inlier_count,
                rmse_m=round(float(np.sqrt(np.mean(residuals**2))), 5),
                area_m2=round(area, 3),
                slope_deg=round(_slope_deg(a, b), 4),
                aspect_downslope_deg=round(_aspect_downslope_deg(a, b), 4),
                a=float(a),
                b=float(b),
                c=float(c),
                normal_x=normal_x,
                normal_y=normal_y,
                normal_z=normal_z,
                hull_local_xy=tuple((round(x, 4), round(y, 4)) for x, y in hull),
            )
        )
        assigned_count += inlier_count
        remaining = remaining[~refined_mask]

    roof_candidate_count = int(len(candidate_points))
    unassigned_count = max(roof_candidate_count - assigned_count, 0)
    coverage_ratio = (
        float(assigned_count) / float(roof_candidate_count)
        if roof_candidate_count
        else 0.0
    )

    quantile_levels = (0.0, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 1.0)
    quantiles = np.quantile(z_above, quantile_levels)
    quantile_payload = {
        f"p{int(level * 100):02d}": round(float(value), 4)
        for level, value in zip(quantile_levels, quantiles, strict=True)
    }

    high_structure_counts = {
        f"ge_{height_m:g}m": int(np.count_nonzero(z_above >= height_m))
        for height_m in (22.0, 24.0, 26.0, 28.0)
    }

    bounds = {
        "min_x": float(np.min(points[:, 0])),
        "max_x": float(np.max(points[:, 0])),
        "min_y": float(np.min(points[:, 1])),
        "max_y": float(np.max(points[:, 1])),
        "min_z": float(np.min(points[:, 2])),
        "max_z": float(np.max(points[:, 2])),
    }

    return RoofAnalysis(
        origin_x=origin_x,
        origin_y=origin_y,
        ground_z=float(ground_z),
        horizontal_crs=horizontal_crs,
        vertical_datum=vertical_datum,
        source_point_count=int(len(points)),
        roof_candidate_count=roof_candidate_count,
        assigned_point_count=assigned_count,
        unassigned_point_count=unassigned_count,
        coverage_ratio=round(coverage_ratio, 6),
        min_height_m=float(min_height_m),
        residual_threshold_m=float(residual_threshold_m),
        planes=tuple(planes),
        z_above_ground_quantiles_m=quantile_payload,
        high_structure_counts=high_structure_counts,
        bounds=bounds,
    )


def write_diagnostic_obj(path: Path, analysis: RoofAnalysis) -> None:
    """Write roof-patch polygons in local metric coordinates for inspection.

    X/Y are relative to the georeference origin and Z is height above ground.
    The absolute origin and datum are written as comments and remain in JSON.
    """

    lines = [
        "# BatiForge roof-plane diagnostic OBJ",
        f"# horizontal_crs={analysis.horizontal_crs}",
        f"# vertical_datum={analysis.vertical_datum}",
        f"# origin_x={analysis.origin_x:.6f}",
        f"# origin_y={analysis.origin_y:.6f}",
        f"# ground_z={analysis.ground_z:.6f}",
        "# axes: X east, Y north, Z up; Z values are metres above ground_z",
    ]

    vertex_offset = 1
    for plane in analysis.planes:
        if len(plane.hull_local_xy) < 3:
            continue
        lines.append(f"o roof_plane_{plane.index:02d}")
        lines.append(
            f"# points={plane.point_count} area_m2={plane.area_m2:.3f} "
            f"slope_deg={plane.slope_deg:.4f} rmse_m={plane.rmse_m:.5f}"
        )
        for x_local, y_local in plane.hull_local_xy:
            z_abs = plane.a * x_local + plane.b * y_local + plane.c
            z_local = z_abs - analysis.ground_z
            lines.append(f"v {x_local:.6f} {y_local:.6f} {z_local:.6f}")

        count = len(plane.hull_local_xy)
        # Fan triangulation is sufficient for the convex hull used here.
        for index in range(2, count):
            lines.append(
                f"f {vertex_offset} {vertex_offset + index - 1} {vertex_offset + index}"
            )
        vertex_offset += count

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


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
        classes = np.asarray(las.classification)
        xyz = xyz[classes == classification]

    if len(xyz) == 0:
        raise ValueError("no points remain after loading/classification filtering")
    return xyz


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fit deterministic roof-like planes to a BatiForge building LAZ/LAS cloud."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--ground-z", type=float, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-obj", type=Path)
    parser.add_argument("--horizontal-crs", default="EPSG:2154")
    parser.add_argument("--vertical-datum", default="IGN69")
    parser.add_argument("--classification", type=int, default=6)
    parser.add_argument("--all-classes", action="store_true")
    parser.add_argument("--min-height-m", type=float, default=2.0)
    parser.add_argument("--residual-threshold-m", type=float, default=0.18)
    parser.add_argument("--min-plane-points", type=int, default=250)
    parser.add_argument("--min-plane-area-m2", type=float, default=1.0)
    parser.add_argument("--max-planes", type=int, default=16)
    parser.add_argument("--max-slope-deg", type=float, default=75.0)
    parser.add_argument("--ransac-iterations", type=int, default=600)
    parser.add_argument("--seed", type=int, default=20260922)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    classification = None if args.all_classes else args.classification

    try:
        xyz = _load_las_xyz(args.input, classification)
        analysis = analyze_roof_planes(
            xyz,
            ground_z=args.ground_z,
            horizontal_crs=args.horizontal_crs,
            vertical_datum=args.vertical_datum,
            min_height_m=args.min_height_m,
            residual_threshold_m=args.residual_threshold_m,
            min_plane_points=args.min_plane_points,
            min_plane_area_m2=args.min_plane_area_m2,
            max_planes=args.max_planes,
            max_slope_deg=args.max_slope_deg,
            ransac_iterations=args.ransac_iterations,
            seed=args.seed,
        )
    except (OSError, ValueError, laspy.errors.LaspyException) as exc:
        print(f"BatiForge roof analysis failed: {exc}")
        return 2

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(analysis.to_json(), encoding="utf-8", newline="\n")
    if args.output_obj:
        write_diagnostic_obj(args.output_obj, analysis)

    print(
        "roof planes: "
        f"source={analysis.source_point_count} "
        f"candidates={analysis.roof_candidate_count} "
        f"planes={len(analysis.planes)} "
        f"assigned={analysis.assigned_point_count} "
        f"coverage={analysis.coverage_ratio:.3f}"
    )
    print(f"json: {args.output_json}")
    if args.output_obj:
        print(f"diagnostic obj: {args.output_obj}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
