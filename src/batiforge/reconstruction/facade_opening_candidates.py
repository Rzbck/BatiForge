from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True)
class WallPlane:
    wall_id: str
    normal_xy: tuple[float, float]
    u_axis_xy: tuple[float, float]
    u_min: float
    u_max: float
    z_min: float
    z_max: float
    area_m2: float
    centroid_xyz: tuple[float, float, float]

    @property
    def width_m(self) -> float:
        return self.u_max - self.u_min

    @property
    def height_m(self) -> float:
        return self.z_max - self.z_min

    @property
    def aspect(self) -> float:
        return self.width_m / max(self.height_m, 1e-9)


def _normalise_xy(x: float, y: float) -> tuple[float, float]:
    n = math.hypot(x, y)
    if n <= 1e-12:
        raise ValueError("zero XY normal")
    x /= n
    y /= n
    if x < 0.0 or (abs(x) < 1e-12 and y < 0.0):
        x = -x
        y = -y
    return x, y


def _parse_obj(path: Path) -> tuple[np.ndarray, list[tuple[int, ...]]]:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("v "):
            parts = line.split()
            if len(parts) >= 4:
                vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
        elif line.startswith("f "):
            idx: list[int] = []
            for token in line.split()[1:]:
                head = token.split("/", 1)[0]
                if not head:
                    continue
                value = int(head)
                if value < 0:
                    value = len(vertices) + value + 1
                idx.append(value - 1)
            if len(idx) >= 3:
                faces.append(tuple(idx))
    if not vertices or not faces:
        raise ValueError(f"OBJ contains no usable mesh: {path}")
    return np.asarray(vertices, dtype=np.float64), faces


def _face_metrics(vertices: np.ndarray, face: tuple[int, ...]) -> tuple[np.ndarray, float, np.ndarray]:
    pts = vertices[np.asarray(face, dtype=np.int64)]
    normal_sum = np.zeros(3, dtype=np.float64)
    area = 0.0
    base = pts[0]
    for i in range(1, len(pts) - 1):
        cross = np.cross(pts[i] - base, pts[i + 1] - base)
        tri_area = 0.5 * float(np.linalg.norm(cross))
        if tri_area > 0.0:
            area += tri_area
            normal_sum += cross
    norm = float(np.linalg.norm(normal_sum))
    if norm <= 1e-12:
        normal = np.zeros(3, dtype=np.float64)
    else:
        normal = normal_sum / norm
    return normal, area, pts.mean(axis=0)


def extract_vertical_wall_planes(
    obj_path: Path,
    *,
    max_abs_nz: float = 0.22,
    max_angle_deg: float = 5.0,
    max_plane_offset_m: float = 0.22,
    min_area_m2: float = 2.0,
    min_width_m: float = 1.0,
    min_height_m: float = 1.5,
) -> list[WallPlane]:
    vertices, faces = _parse_obj(obj_path)
    face_info: dict[int, dict[str, Any]] = {}
    edge_to_faces: dict[tuple[int, int], list[int]] = {}

    for fi, face in enumerate(faces):
        normal, area, centroid = _face_metrics(vertices, face)
        if area <= 1e-9 or abs(float(normal[2])) > max_abs_nz:
            continue
        xy_len = math.hypot(float(normal[0]), float(normal[1]))
        if xy_len <= 0.75:
            continue
        nx, ny = _normalise_xy(float(normal[0]), float(normal[1]))
        angle = math.atan2(ny, nx)
        d = nx * float(centroid[0]) + ny * float(centroid[1])
        face_info[fi] = {
            "face": face,
            "normal_xy": (nx, ny),
            "angle": angle,
            "d": d,
            "area": area,
            "centroid": centroid,
        }
        for a, b in zip(face, face[1:] + face[:1], strict=True):
            edge = (min(a, b), max(a, b))
            edge_to_faces.setdefault(edge, []).append(fi)

    parent = {fi: fi for fi in face_info}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    max_angle = math.radians(max_angle_deg)
    for members in edge_to_faces.values():
        usable = [fi for fi in members if fi in face_info]
        for i in range(len(usable)):
            for j in range(i + 1, len(usable)):
                a = face_info[usable[i]]
                b = face_info[usable[j]]
                da = abs(float(a["angle"]) - float(b["angle"]))
                da = min(da, math.pi - da)
                if da <= max_angle and abs(float(a["d"]) - float(b["d"])) <= max_plane_offset_m:
                    union(usable[i], usable[j])

    groups: dict[int, list[int]] = {}
    for fi in face_info:
        groups.setdefault(find(fi), []).append(fi)

    walls: list[WallPlane] = []
    for _, members in groups.items():
        area = sum(float(face_info[fi]["area"]) for fi in members)
        if area < min_area_m2:
            continue
        weighted = np.zeros(2, dtype=np.float64)
        cent = np.zeros(3, dtype=np.float64)
        all_indices: set[int] = set()
        for fi in members:
            info = face_info[fi]
            w = float(info["area"])
            weighted += np.asarray(info["normal_xy"], dtype=np.float64) * w
            cent += np.asarray(info["centroid"], dtype=np.float64) * w
            all_indices.update(info["face"])
        nx, ny = _normalise_xy(float(weighted[0]), float(weighted[1]))
        ux, uy = -ny, nx
        pts = vertices[np.asarray(sorted(all_indices), dtype=np.int64)]
        us = pts[:, 0] * ux + pts[:, 1] * uy
        zs = pts[:, 2]
        u_min, u_max = float(us.min()), float(us.max())
        z_min, z_max = float(zs.min()), float(zs.max())
        width = u_max - u_min
        height = z_max - z_min
        if width < min_width_m or height < min_height_m:
            continue
        cent /= max(area, 1e-9)
        walls.append(
            WallPlane(
                wall_id="",
                normal_xy=(nx, ny),
                u_axis_xy=(ux, uy),
                u_min=u_min,
                u_max=u_max,
                z_min=z_min,
                z_max=z_max,
                area_m2=area,
                centroid_xyz=(float(cent[0]), float(cent[1]), float(cent[2])),
            )
        )

    walls.sort(key=lambda item: item.area_m2, reverse=True)
    return [
        WallPlane(
            wall_id=f"wall-{i:02d}",
            normal_xy=w.normal_xy,
            u_axis_xy=w.u_axis_xy,
            u_min=w.u_min,
            u_max=w.u_max,
            z_min=w.z_min,
            z_max=w.z_max,
            area_m2=w.area_m2,
            centroid_xyz=w.centroid_xyz,
        )
        for i, w in enumerate(walls, start=1)
    ]


def _bbox_from_mask(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _connected_components(mask: np.ndarray) -> list[tuple[int, int, int, int, np.ndarray]]:
    from scipy import ndimage

    labels, count = ndimage.label(mask)
    boxes: list[tuple[int, int, int, int, np.ndarray]] = []
    for label_id in range(1, count + 1):
        component = labels == label_id
        bbox = _bbox_from_mask(component)
        if bbox is not None:
            boxes.append((*bbox, component))
    return boxes


def segment_facade_image(
    image_path: Path,
    output_dir: Path,
    *,
    model_id: str,
    min_component_fraction: float = 0.00035,
    min_confidence: float = 0.42,
) -> dict[str, Any]:
    from PIL import Image
    import torch
    import torch.nn.functional as F
    from transformers import AutoImageProcessor, AutoModelForSemanticSegmentation

    output_dir.mkdir(parents=True, exist_ok=True)
    image = Image.open(image_path).convert("RGB")
    width, height = image.size
    device = "cuda" if torch.cuda.is_available() else "cpu"
    processor = AutoImageProcessor.from_pretrained(model_id)
    model = AutoModelForSemanticSegmentation.from_pretrained(model_id)
    model.to(device)
    model.eval()

    inputs = processor(images=image, return_tensors="pt")
    inputs = {key: value.to(device) for key, value in inputs.items()}
    with torch.no_grad():
        logits = model(**inputs).logits
        upsampled = F.interpolate(logits, size=(height, width), mode="bilinear", align_corners=False)
        probs = torch.softmax(upsampled, dim=1)[0]
        pred = probs.argmax(dim=0).cpu().numpy().astype(np.int16)
        confidence = probs.max(dim=0).values.cpu().numpy().astype(np.float32)

    id2label = {int(k): str(v).lower() for k, v in dict(model.config.id2label).items()}
    label_to_id = {value: key for key, value in id2label.items()}
    facade_ids = [label_to_id[name] for name in ("facade_wall", "window", "door", "balcony") if name in label_to_id]
    facade_mask = np.isin(pred, np.asarray(facade_ids, dtype=np.int16))
    facade_bbox = _bbox_from_mask(facade_mask)
    if facade_bbox is None:
        raise RuntimeError(f"No facade region detected in {image_path}")
    fx0, fy0, fx1, fy1 = facade_bbox
    fw = max(1, fx1 - fx0)
    fh = max(1, fy1 - fy0)

    min_pixels = max(20, int(width * height * min_component_fraction))
    openings: list[dict[str, Any]] = []
    for class_name in ("window", "door", "balcony"):
        class_id = label_to_id.get(class_name)
        if class_id is None:
            continue
        for x0, y0, x1, y1, component in _connected_components(pred == class_id):
            area = int(component.sum())
            if area < min_pixels:
                continue
            mean_conf = float(confidence[component].mean())
            if mean_conf < min_confidence:
                continue
            rel = {
                "x0": (x0 - fx0) / fw,
                "y0": (y0 - fy0) / fh,
                "x1": (x1 - fx0) / fw,
                "y1": (y1 - fy0) / fh,
            }
            if rel["x1"] < -0.05 or rel["x0"] > 1.05 or rel["y1"] < -0.05 or rel["y0"] > 1.05:
                continue
            openings.append(
                {
                    "class": class_name,
                    "bbox_px": [x0, y0, x1, y1],
                    "bbox_facade_norm": rel,
                    "area_px": area,
                    "mean_confidence": mean_conf,
                }
            )

    overlay = np.asarray(image).copy()
    colours = {
        "facade_wall": np.asarray((80, 180, 255), dtype=np.float32),
        "window": np.asarray((40, 220, 255), dtype=np.float32),
        "door": np.asarray((255, 150, 40), dtype=np.float32),
        "balcony": np.asarray((220, 80, 255), dtype=np.float32),
    }
    base = overlay.astype(np.float32)
    alpha = 0.42
    for name, colour in colours.items():
        class_id = label_to_id.get(name)
        if class_id is None:
            continue
        mask = pred == class_id
        base[mask] = (1.0 - alpha) * base[mask] + alpha * colour
    overlay = np.clip(base, 0, 255).astype(np.uint8)
    overlay_path = output_dir / f"{image_path.stem}-facade-segmentation.png"
    Image.fromarray(overlay).save(overlay_path)

    return {
        "image_path": str(image_path),
        "image_size": [width, height],
        "device": device,
        "model_id": model_id,
        "labels": id2label,
        "facade_bbox_px": [fx0, fy0, fx1, fy1],
        "facade_aspect_px": fw / max(fh, 1),
        "opening_count": len(openings),
        "openings": openings,
        "overlay_path": str(overlay_path),
    }


def map_openings_to_walls(
    segmentation: dict[str, Any],
    walls: list[WallPlane],
    *,
    top_walls: int = 4,
) -> list[dict[str, Any]]:
    image_aspect = float(segmentation["facade_aspect_px"])
    candidates: list[dict[str, Any]] = []
    for wall in walls:
        score = abs(math.log(max(wall.aspect, 1e-9) / max(image_aspect, 1e-9)))
        for mirrored in (False, True):
            openings: list[dict[str, Any]] = []
            nx, ny = wall.normal_xy
            ux, uy = wall.u_axis_xy
            d = nx * wall.centroid_xyz[0] + ny * wall.centroid_xyz[1]
            for opening in segmentation["openings"]:
                rel = opening["bbox_facade_norm"]
                x0 = float(rel["x0"])
                x1 = float(rel["x1"])
                y0 = float(rel["y0"])
                y1 = float(rel["y1"])
                if mirrored:
                    x0, x1 = 1.0 - x1, 1.0 - x0
                x0, x1 = sorted((max(0.0, min(1.0, x0)), max(0.0, min(1.0, x1))))
                y0, y1 = sorted((max(0.0, min(1.0, y0)), max(0.0, min(1.0, y1))))
                u0 = wall.u_min + x0 * wall.width_m
                u1 = wall.u_min + x1 * wall.width_m
                z_top = wall.z_max - y0 * wall.height_m
                z_bottom = wall.z_max - y1 * wall.height_m
                uc = 0.5 * (u0 + u1)
                zc = 0.5 * (z_top + z_bottom)
                x = ux * uc + nx * d
                y = uy * uc + ny * d
                openings.append(
                    {
                        **opening,
                        "center_xyz": [x, y, zc],
                        "width_m": max(0.05, u1 - u0),
                        "height_m": max(0.05, z_top - z_bottom),
                    }
                )
            candidates.append(
                {
                    "candidate_id": f"{wall.wall_id}-{'mirror' if mirrored else 'normal'}",
                    "wall_id": wall.wall_id,
                    "mirrored": mirrored,
                    "aspect_score": score,
                    "wall": {
                        "normal_xy": list(wall.normal_xy),
                        "u_axis_xy": list(wall.u_axis_xy),
                        "u_min": wall.u_min,
                        "u_max": wall.u_max,
                        "z_min": wall.z_min,
                        "z_max": wall.z_max,
                        "width_m": wall.width_m,
                        "height_m": wall.height_m,
                        "area_m2": wall.area_m2,
                        "centroid_xyz": list(wall.centroid_xyz),
                    },
                    "openings": openings,
                }
            )
    candidates.sort(key=lambda item: (float(item["aspect_score"]), -float(item["wall"]["area_m2"]), bool(item["mirrored"])))
    return candidates[: max(1, top_walls * 2)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Segment facade openings and map them onto ranked vertical wall planes")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--building-obj", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model-id", default="Marco333/segformer-b0-facade-cmp")
    parser.add_argument("--top-walls", type=int, default=4)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    segmentation = segment_facade_image(args.image, args.output_dir, model_id=args.model_id)
    walls = extract_vertical_wall_planes(args.building_obj)
    if not walls:
        raise RuntimeError("No usable vertical wall planes found in building OBJ")
    candidates = map_openings_to_walls(segmentation, walls, top_walls=args.top_walls)

    result = {
        "schema_version": 1,
        "status": "EXPERIMENTAL",
        "method": "HF facade segmentation + normalized facade-box mapping to ranked coplanar vertical Roofer wall planes",
        "caveat": "Candidate panels are not accepted metric openings until wall identity/orientation is host-validated; no boolean cuts are applied.",
        "source_image": str(args.image),
        "building_obj": str(args.building_obj),
        "segmentation": segmentation,
        "wall_count": len(walls),
        "walls": [
            {
                "wall_id": wall.wall_id,
                "normal_xy": list(wall.normal_xy),
                "u_axis_xy": list(wall.u_axis_xy),
                "width_m": wall.width_m,
                "height_m": wall.height_m,
                "area_m2": wall.area_m2,
                "centroid_xyz": list(wall.centroid_xyz),
            }
            for wall in walls
        ],
        "candidate_mappings": candidates,
    }
    output_json = args.output_dir / "facade-opening-candidates.json"
    output_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"facade segmentation: openings={segmentation['opening_count']} device={segmentation['device']}")
    print(f"vertical walls: {len(walls)}")
    for i, item in enumerate(candidates, start=1):
        print(
            f"candidate {i}: {item['candidate_id']} score={item['aspect_score']:.4f} "
            f"wall={item['wall']['width_m']:.2f}x{item['wall']['height_m']:.2f}m "
            f"openings={len(item['openings'])}"
        )
    print(f"overlay: {segmentation['overlay_path']}")
    print(f"json: {output_json}")


if __name__ == "__main__":
    main()
