from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from batiforge.reconstruction.facade_opening_candidates import (
    WallPlane,
    extract_vertical_wall_planes,
)


def canonical_label(label: str) -> str | None:
    value = label.strip().lower()
    if "window" in value or "stained glass" in value:
        return "window"
    if "door" in value or "entrance" in value or "doorway" in value:
        return "door"
    if "facade" in value or "building" in value or "wall" in value:
        return "facade"
    return None


def box_iou(a: list[float], b: list[float]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = area_a + area_b - inter
    return inter / union if union > 0.0 else 0.0


def dedupe_detections(items: list[dict[str, Any]], iou_threshold: float = 0.45) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda row: float(row["score"]), reverse=True):
        if any(
            other["class"] == item["class"]
            and box_iou(other["bbox_px"], item["bbox_px"]) >= iou_threshold
            for other in kept
        ):
            continue
        kept.append(item)
    return kept


def _contains_center(box: list[float], point_box: list[float]) -> bool:
    x0, y0, x1, y1 = box
    px0, py0, px1, py1 = point_box
    cx, cy = 0.5 * (px0 + px1), 0.5 * (py0 + py1)
    return x0 <= cx <= x1 and y0 <= cy <= y1


def choose_facade_box(
    facade_boxes: list[dict[str, Any]],
    openings: list[dict[str, Any]],
    image_size: tuple[int, int],
) -> list[float]:
    width, height = image_size
    if facade_boxes:
        ranked = sorted(
            facade_boxes,
            key=lambda row: (
                sum(_contains_center(row["bbox_px"], opening["bbox_px"]) for opening in openings),
                float(row["score"]),
            ),
            reverse=True,
        )
        best = list(map(float, ranked[0]["bbox_px"]))
        if sum(_contains_center(best, opening["bbox_px"]) for opening in openings) >= max(1, len(openings) // 2):
            return best

    if openings:
        x0 = min(float(item["bbox_px"][0]) for item in openings)
        y0 = min(float(item["bbox_px"][1]) for item in openings)
        x1 = max(float(item["bbox_px"][2]) for item in openings)
        y1 = max(float(item["bbox_px"][3]) for item in openings)
        bw, bh = max(1.0, x1 - x0), max(1.0, y1 - y0)
        x0 -= 0.18 * bw
        x1 += 0.18 * bw
        y0 -= 0.45 * bh
        y1 += 0.30 * bh
        return [max(0.0, x0), max(0.0, y0), min(float(width), x1), min(float(height), y1)]

    return [0.0, 0.0, float(width), float(height)]


def detect_grounded_openings(
    image_path: Path,
    output_dir: Path,
    *,
    model_id: str = "IDEA-Research/grounding-dino-base",
    box_threshold: float = 0.24,
    text_threshold: float = 0.20,
) -> dict[str, Any]:
    from PIL import Image, ImageDraw
    import torch
    from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

    output_dir.mkdir(parents=True, exist_ok=True)
    image = Image.open(image_path).convert("RGB")
    width, height = image.size
    device = "cuda" if torch.cuda.is_available() else "cpu"

    queries = [
        "window",
        "arched window",
        "stained glass window",
        "church window",
        "door",
        "entrance",
        "arched doorway",
        "church door",
        "church facade",
        "building facade",
        "church building",
    ]

    processor = AutoProcessor.from_pretrained(model_id)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(model_id).to(device)
    model.eval()

    inputs = processor(images=image, text=[queries], return_tensors="pt").to(device)
    with torch.no_grad():
        outputs = model(**inputs)
    result = processor.post_process_grounded_object_detection(
        outputs,
        inputs.input_ids,
        threshold=box_threshold,
        text_threshold=text_threshold,
        target_sizes=[(height, width)],
    )[0]

    raw: list[dict[str, Any]] = []
    for box, score, label in zip(result["boxes"], result["scores"], result["labels"], strict=True):
        canonical = canonical_label(str(label))
        if canonical is None:
            continue
        bbox = [float(v) for v in box.detach().cpu().tolist()]
        x0, y0, x1, y1 = bbox
        area_fraction = max(0.0, x1 - x0) * max(0.0, y1 - y0) / max(1.0, width * height)
        if canonical in {"window", "door"} and not (0.00015 <= area_fraction <= 0.28):
            continue
        raw.append(
            {
                "class": canonical,
                "query_label": str(label),
                "score": float(score.detach().cpu().item()),
                "bbox_px": bbox,
            }
        )

    facade_boxes = dedupe_detections([item for item in raw if item["class"] == "facade"], 0.60)
    openings = dedupe_detections([item for item in raw if item["class"] in {"window", "door"}], 0.42)
    if not openings:
        raise RuntimeError(
            "Grounding DINO detected no window/door candidates; refusing to render empty facade mappings."
        )

    facade_bbox = choose_facade_box(facade_boxes, openings, (width, height))
    fx0, fy0, fx1, fy1 = facade_bbox
    fw, fh = max(1.0, fx1 - fx0), max(1.0, fy1 - fy0)
    normalized: list[dict[str, Any]] = []
    for opening in openings:
        x0, y0, x1, y1 = opening["bbox_px"]
        normalized.append(
            {
                **opening,
                "mean_confidence": opening["score"],
                "bbox_facade_norm": {
                    "x0": (x0 - fx0) / fw,
                    "y0": (y0 - fy0) / fh,
                    "x1": (x1 - fx0) / fw,
                    "y1": (y1 - fy0) / fh,
                },
            }
        )

    overlay = image.copy()
    draw = ImageDraw.Draw(overlay)
    draw.rectangle(tuple(facade_bbox), outline=(255, 220, 40), width=4)
    colours = {"window": (20, 220, 255), "door": (255, 110, 20)}
    for opening in normalized:
        box = tuple(opening["bbox_px"])
        colour = colours[opening["class"]]
        draw.rectangle(box, outline=colour, width=4)
        draw.text((box[0] + 3, box[1] + 3), f"{opening['class']} {opening['score']:.2f}", fill=colour)
    overlay_path = output_dir / f"{image_path.stem}-grounding-dino.png"
    overlay.save(overlay_path)

    return {
        "image_path": str(image_path),
        "image_size": [width, height],
        "device": device,
        "model_id": model_id,
        "labels": {"window": "window", "door": "door", "facade": "facade"},
        "facade_bbox_px": [float(v) for v in facade_bbox],
        "facade_aspect_px": fw / fh,
        "opening_count": len(normalized),
        "openings": normalized,
        "overlay_path": str(overlay_path),
        "raw_detection_count": len(raw),
    }


def _wall_dict(wall: WallPlane) -> dict[str, Any]:
    return {
        "wall_id": wall.wall_id,
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
    }


def rank_candidate_walls(segmentation: dict[str, Any], walls: list[WallPlane], top_walls: int) -> list[WallPlane]:
    opening_count = len(segmentation.get("openings", []))
    if opening_count >= 3:
        plausible = [w for w in walls if w.width_m >= 6.0 and 3.0 <= w.height_m <= 10.0]
        if plausible:
            return sorted(plausible, key=lambda w: (w.width_m, w.area_m2), reverse=True)[:top_walls]
    image_aspect = max(float(segmentation["facade_aspect_px"]), 1e-6)
    return sorted(
        walls,
        key=lambda w: abs(math.log(max(w.aspect, 1e-6) / image_aspect)),
    )[:top_walls]


def map_grounded_openings(
    segmentation: dict[str, Any], walls: list[WallPlane], *, top_walls: int = 3
) -> list[dict[str, Any]]:
    selected = rank_candidate_walls(segmentation, walls, top_walls)
    mappings: list[dict[str, Any]] = []
    for wall in selected:
        nx, ny = wall.normal_xy
        ux, uy = wall.u_axis_xy
        d = nx * wall.centroid_xyz[0] + ny * wall.centroid_xyz[1]
        for mirrored in (False, True):
            mapped: list[dict[str, Any]] = []
            for opening in segmentation["openings"]:
                rel = opening["bbox_facade_norm"]
                x0, x1 = float(rel["x0"]), float(rel["x1"])
                y0, y1 = float(rel["y0"]), float(rel["y1"])
                if mirrored:
                    x0, x1 = 1.0 - x1, 1.0 - x0
                x0, x1 = sorted((max(0.0, min(1.0, x0)), max(0.0, min(1.0, x1))))
                y0, y1 = sorted((max(0.0, min(1.0, y0)), max(0.0, min(1.0, y1))))
                if x1 - x0 < 0.01 or y1 - y0 < 0.01:
                    continue
                u0 = wall.u_min + x0 * wall.width_m
                u1 = wall.u_min + x1 * wall.width_m
                z_top = wall.z_max - y0 * wall.height_m
                z_bottom = wall.z_max - y1 * wall.height_m
                uc = 0.5 * (u0 + u1)
                zc = 0.5 * (z_top + z_bottom)
                xc = nx * d + ux * uc
                yc = ny * d + uy * uc
                mapped.append(
                    {
                        **opening,
                        "center_xyz": [xc, yc, zc],
                        "width_m": max(0.05, u1 - u0),
                        "height_m": max(0.05, z_top - z_bottom),
                    }
                )
            score = -wall.width_m if len(segmentation["openings"]) >= 3 else abs(
                math.log(max(wall.aspect, 1e-6) / max(float(segmentation["facade_aspect_px"]), 1e-6))
            )
            mappings.append(
                {
                    "candidate_id": f"{wall.wall_id}-{'mirror' if mirrored else 'normal'}",
                    "mirrored": mirrored,
                    "aspect_score": score,
                    "wall_id": wall.wall_id,
                    "wall": _wall_dict(wall),
                    "openings": mapped,
                }
            )
    return mappings


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect facade openings with Grounding DINO and map to Roofer walls")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--building-obj", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model-id", default="IDEA-Research/grounding-dino-base")
    parser.add_argument("--top-walls", type=int, default=3)
    parser.add_argument("--box-threshold", type=float, default=0.24)
    parser.add_argument("--text-threshold", type=float, default=0.20)
    args = parser.parse_args()

    segmentation = detect_grounded_openings(
        args.image,
        args.output_dir,
        model_id=args.model_id,
        box_threshold=args.box_threshold,
        text_threshold=args.text_threshold,
    )
    walls = extract_vertical_wall_planes(args.building_obj)
    mappings = map_grounded_openings(segmentation, walls, top_walls=max(1, args.top_walls))
    result = {
        "schema_version": 2,
        "status": "EXPERIMENTAL",
        "method": "Grounding DINO zero-shot opening detection + large-wall candidate mapping",
        "source_image": str(args.image),
        "building_obj": str(args.building_obj),
        "segmentation": segmentation,
        "wall_count": len(walls),
        "walls": [_wall_dict(w) for w in walls],
        "candidate_mappings": mappings,
        "caveat": "Candidate panels are evidence hypotheses only; no boolean cuts are applied until wall/camera registration is validated.",
    }
    output = args.output_dir / "facade-opening-candidates-v2.json"
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"grounded openings: {segmentation['opening_count']}")
    print(f"device: {segmentation['device']}")
    print(f"overlay: {segmentation['overlay_path']}")
    print(f"candidate mappings: {len(mappings)}")
    print(f"json: {output}")


if __name__ == "__main__":
    main()
