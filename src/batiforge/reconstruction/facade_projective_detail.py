from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from batiforge.reconstruction.facade_opening_candidates import extract_vertical_wall_planes, _parse_obj


def _iou(a: list[float], b: list[float]) -> float:
    ax0, ay0, ax1, ay1 = map(float, a)
    bx0, by0, bx1, by1 = map(float, b)
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0.0:
        return 0.0
    aa = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    ba = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    return inter / max(aa + ba - inter, 1e-9)


def _nms(items: list[dict[str, Any]], iou_threshold: float = 0.45) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda x: float(x.get("score", x.get("mean_confidence", 0.0))), reverse=True):
        if any(item["class"] == kept["class"] and _iou(item["bbox_px"], kept["bbox_px"]) >= iou_threshold for kept in out):
            continue
        out.append(item)
    return out


def _pointed_arch(width: float, height: float, segments: int = 7) -> np.ndarray:
    width = max(width, 0.08)
    height = max(height, 0.12)
    half = width * 0.5
    bottom = -height * 0.5
    top = height * 0.5
    spring = bottom + height * 0.62
    pts: list[tuple[float, float]] = [(-half, bottom), (half, bottom), (half, spring)]
    for i in range(1, segments + 1):
        t = i / segments
        x = half * (1.0 - t)
        z = spring + (top - spring) * (2.0 * t - t * t)
        pts.append((x, z))
    for i in range(1, segments + 1):
        t = i / segments
        x = -half * t
        z = top - (top - spring) * (t * t)
        pts.append((x, z))
    return np.asarray(pts, dtype=np.float64)


def _quatrefoil(width: float, height: float, segments: int = 48) -> np.ndarray:
    pts = []
    rx, rz = width * 0.5, height * 0.5
    for i in range(segments):
        a = 2.0 * math.pi * i / segments
        r = 0.78 + 0.22 * math.cos(4.0 * a)
        pts.append((rx * r * math.cos(a), rz * r * math.sin(a)))
    return np.asarray(pts, dtype=np.float64)


def _largest_contour(mask: np.ndarray) -> np.ndarray | None:
    m = (mask > 0).astype(np.uint8) * 255
    contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    if cv2.contourArea(contour) <= 12:
        return None
    eps = max(1.2, 0.008 * cv2.arcLength(contour, True))
    return cv2.approxPolyDP(contour, eps, True).reshape(-1, 2).astype(np.float64)


def _plane_from_region(region: dict[str, Any], walls: dict[str, Any], building_centroid_xy: np.ndarray) -> dict[str, Any]:
    selected = [walls[wid] for wid in region["wall_ids"]]
    if region["kind"] == "single_wall":
        w = selected[0]
        n = np.asarray(w.normal_xy, dtype=np.float64)
        u_axis = np.asarray(w.u_axis_xy, dtype=np.float64)
        d = float(np.dot(n, np.asarray(w.centroid_xyz[:2], dtype=np.float64)))
        u_min, u_max = float(w.u_min), float(w.u_max)
    else:
        weighted = np.zeros(2, dtype=np.float64)
        d_sum = 0.0
        area_sum = 0.0
        endpoints: list[np.ndarray] = []
        for w in selected:
            a = float(w.area_m2)
            wn = np.asarray(w.normal_xy, dtype=np.float64)
            wc = np.asarray(w.centroid_xyz[:2], dtype=np.float64)
            wd = float(np.dot(wn, wc))
            wu = np.asarray(w.u_axis_xy, dtype=np.float64)
            weighted += wn * a
            d_sum += wd * a
            area_sum += a
            endpoints.extend([wn * wd + wu * float(w.u_min), wn * wd + wu * float(w.u_max)])
        n = weighted / max(float(np.linalg.norm(weighted)), 1e-9)
        if n[0] < 0.0:
            n = -n
        u_axis = np.asarray([-n[1], n[0]], dtype=np.float64)
        d = d_sum / max(area_sum, 1e-9)
        us = [float(np.dot(u_axis, p)) for p in endpoints]
        u_min, u_max = min(us), max(us)
    if float(np.dot(n, building_centroid_xy)) > d:
        outward = -n
    else:
        outward = n.copy()
    return {
        "normal_xy": n.tolist(),
        "outward_normal_xy": outward.tolist(),
        "u_axis_xy": u_axis.tolist(),
        "d": d,
        "u_min": u_min,
        "u_max": u_max,
        "z_min": float(region["metric_z"][0]),
        "z_max": float(region["metric_z"][1]),
    }


def _homography(region: dict[str, Any], plane: dict[str, Any]) -> np.ndarray:
    src = np.asarray(region["image_quad"], dtype=np.float32)
    dst = np.asarray(
        [
            [plane["u_min"], plane["z_min"]],
            [plane["u_max"], plane["z_min"]],
            [plane["u_max"], plane["z_max"]],
            [plane["u_min"], plane["z_max"]],
        ],
        dtype=np.float32,
    )
    return cv2.getPerspectiveTransform(src, dst)


def _map_points(H: np.ndarray, pts: np.ndarray) -> np.ndarray:
    arr = np.asarray(pts, dtype=np.float32).reshape(1, -1, 2)
    return cv2.perspectiveTransform(arr, H)[0].astype(np.float64)


def _inside_quad(quad: list[list[float]], x: float, y: float) -> bool:
    contour = np.asarray(quad, dtype=np.float32).reshape(-1, 1, 2)
    return cv2.pointPolygonTest(contour, (float(x), float(y)), False) >= 0


def _pick_source_result(multiview: dict[str, Any], suffix: str) -> dict[str, Any]:
    for result in multiview.get("results", []):
        if str(result.get("image_path", "")).replace("/", "\\").lower().endswith(suffix.replace("/", "\\").lower()):
            return result
    raise RuntimeError(f"No detection result matches {suffix}")


def _sam_masks(image_path: Path, boxes: list[list[float]], model_id: str) -> list[np.ndarray | None]:
    if not boxes:
        return []
    from PIL import Image
    import torch
    from transformers import Sam2Model, Sam2Processor

    image = Image.open(image_path).convert("RGB")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    processor = Sam2Processor.from_pretrained(model_id)
    model = Sam2Model.from_pretrained(model_id).to(device)
    model.eval()
    inputs = processor(images=image, input_boxes=[boxes], return_tensors="pt").to(device)
    with torch.no_grad():
        outputs = model(**inputs, multimask_output=False)
    masks = processor.post_process_masks(outputs.pred_masks.cpu(), inputs["original_sizes"])[0]
    arr = masks.detach().cpu().numpy()
    while arr.ndim > 3 and arr.shape[0] == 1:
        arr = arr[0]
    if arr.ndim == 4 and arr.shape[1] == 1:
        arr = arr[:, 0]
    if arr.ndim == 4 and arr.shape[0] == len(boxes):
        arr = arr[:, 0]
    if arr.ndim == 2:
        arr = arr[None, ...]
    if arr.ndim != 3 or arr.shape[0] != len(boxes):
        return [None for _ in boxes]
    return [(m > 0).astype(np.uint8) for m in arr]


def build_detail(
    *,
    source_image: Path,
    multiview_json: Path,
    building_obj: Path,
    registration_json: Path,
    output_json: Path,
    overlay_path: Path,
    sam_model_id: str,
) -> dict[str, Any]:
    registration = json.loads(registration_json.read_text(encoding="utf-8"))
    multiview = json.loads(multiview_json.read_text(encoding="utf-8"))
    source = _pick_source_result(multiview, registration["source_image_suffix"])
    vertices, _ = _parse_obj(building_obj)
    building_centroid_xy = vertices[:, :2].mean(axis=0)
    wall_list = extract_vertical_wall_planes(building_obj)
    walls = {w.wall_id: w for w in wall_list}

    regions: list[dict[str, Any]] = []
    for r in registration["regions"]:
        plane = _plane_from_region(r, walls, building_centroid_xy)
        H = _homography(r, plane)
        regions.append({**r, "plane": plane, "H": H})

    detections = _nms(list(source.get("openings", [])))
    doors = [d for d in detections if d["class"] == "door"]
    filtered: list[dict[str, Any]] = []
    for item in detections:
        if item["class"] == "window" and any(_iou(item["bbox_px"], door["bbox_px"]) > 0.08 for door in doors):
            continue
        filtered.append(item)

    selected: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for region in regions:
        items: list[dict[str, Any]] = []
        for item in filtered:
            if item["class"] not in region["accept_classes"]:
                continue
            x0, y0, x1, y1 = map(float, item["bbox_px"])
            cx, cy = 0.5 * (x0 + x1), 0.5 * (y0 + y1)
            if _inside_quad(region["image_quad"], cx, cy):
                items.append(item)
        if region["id"] == "front_gable":
            wins = sorted([x for x in items if x["class"] == "window"], key=lambda x: (x["bbox_px"][2]-x["bbox_px"][0])*(x["bbox_px"][3]-x["bbox_px"][1]), reverse=True)[:1]
            ds = sorted([x for x in items if x["class"] == "door"], key=lambda x: float(x.get("score", 0.0)), reverse=True)[:1]
            items = wins + ds
        elif region["id"] == "side_upper":
            items = [x for x in items if (x["bbox_px"][3]-x["bbox_px"][1]) >= 1.15 * (x["bbox_px"][2]-x["bbox_px"][0])]
            items = sorted(items, key=lambda x: x["bbox_px"][0])[: int(region.get("max_openings", 10))]
        else:
            items = sorted(items, key=lambda x: x["bbox_px"][0])[: int(region.get("max_openings", 8))]
        selected.extend((region, item) for item in items)

    boxes = [list(map(float, item["bbox_px"])) for _, item in selected]
    masks = _sam_masks(source_image, boxes, sam_model_id)

    openings: list[dict[str, Any]] = []
    for idx, ((region, item), mask) in enumerate(zip(selected, masks, strict=True), start=1):
        H = region["H"]
        x0, y0, x1, y1 = map(float, item["bbox_px"])
        box_metric = _map_points(H, np.asarray([[x0,y0],[x1,y0],[x1,y1],[x0,y1]], dtype=np.float64))
        u_center = float(box_metric[:,0].mean())
        z_center = float(box_metric[:,1].mean())
        width = max(0.12, float(box_metric[:,0].max()-box_metric[:,0].min()))
        height = max(0.18, float(box_metric[:,1].max()-box_metric[:,1].min()))

        shape_source = "pointed_arch_fallback"
        local_poly: np.ndarray | None = None
        if mask is not None:
            contour = _largest_contour(mask)
            if contour is not None:
                bx = contour[:,0]
                by = contour[:,1]
                inside = (bx >= x0-3) & (bx <= x1+3) & (by >= y0-3) & (by <= y1+3)
                contour = contour[inside]
                if len(contour) >= 5:
                    mapped = _map_points(H, contour)
                    mw = float(mapped[:,0].max()-mapped[:,0].min())
                    mh = float(mapped[:,1].max()-mapped[:,1].min())
                    if mw >= 0.25*width and mh >= 0.35*height and len(mapped) <= 80:
                        local_poly = mapped - np.asarray([u_center,z_center])
                        shape_source = "sam2_mask"
        if local_poly is None:
            local_poly = _pointed_arch(width, height)

        plane = region["plane"]
        openings.append(
            {
                "id": f"opening-{idx:02d}",
                "region": region["id"],
                "class": item["class"],
                "score": float(item.get("score", item.get("mean_confidence", 0.0))),
                "bbox_px": [x0,y0,x1,y1],
                "u_center": u_center,
                "z_center": z_center,
                "width_m": width,
                "height_m": height,
                "shape_source": shape_source,
                "polygon_local_uz": local_poly.tolist(),
                "plane": plane,
                "mullions": 2 if region["id"] == "front_gable" and item["class"] == "window" else 0,
            }
        )

    for feature in registration.get("manual_features", []):
        region = next(r for r in regions if r["id"] == feature["region"])
        H = region["H"]
        x0,y0,x1,y1 = map(float, feature["bbox_px"])
        mapped = _map_points(H, np.asarray([[x0,y0],[x1,y1]], dtype=np.float64))
        uc, zc = mapped.mean(axis=0)
        width = max(0.15, abs(float(mapped[1,0]-mapped[0,0])))
        height = max(0.15, abs(float(mapped[1,1]-mapped[0,1])))
        openings.append(
            {
                "id": feature["id"],
                "region": region["id"],
                "class": "quatrefoil",
                "score": 1.0,
                "bbox_px": [x0,y0,x1,y1],
                "u_center": float(uc),
                "z_center": float(zc),
                "width_m": width,
                "height_m": height,
                "shape_source": "registered_manual_feature",
                "polygon_local_uz": _quatrefoil(width,height).tolist(),
                "plane": region["plane"],
                "mullions": 0,
            }
        )

    # Objective gate: do not write plausible-looking geometry if the clean view did not resolve the basic architecture.
    counts = {"front_gable": 0, "side_upper": 0, "side_lower": 0}
    for op in openings:
        counts[op["region"]] = counts.get(op["region"], 0) + 1
    if counts.get("front_gable",0) < 2 or counts.get("side_upper",0) < 4 or counts.get("side_lower",0) < 2:
        raise RuntimeError(f"Fidelity gate failed: {counts}. Refusing to generate facade geometry.")

    image = cv2.imread(str(source_image))
    if image is not None:
        for region in regions:
            q = np.asarray(region["image_quad"], dtype=np.int32).reshape(-1,1,2)
            cv2.polylines(image,[q],True,(0,255,255),2)
            p = tuple(map(int, region["image_quad"][0]))
            cv2.putText(image,region["id"],p,cv2.FONT_HERSHEY_SIMPLEX,0.55,(0,255,255),1,cv2.LINE_AA)
        for op in openings:
            x0,y0,x1,y1 = map(int, op["bbox_px"])
            colour = (255,180,0) if op["class"] == "window" else (0,120,255)
            if op["class"] == "quatrefoil": colour = (255,0,255)
            cv2.rectangle(image,(x0,y0),(x1,y1),colour,2)
        overlay_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(overlay_path),image)

    payload = {
        "schema_version": 4,
        "status": "REGISTERED_EVIDENCE_DETAIL",
        "method": "page-5 exterior projective facade registration + Grounding DINO boxes + SAM2 contours",
        "source_image": str(source_image),
        "building_obj": str(building_obj),
        "registration": str(registration_json),
        "sam_model_id": sam_model_id,
        "counts": counts,
        "opening_count": len(openings),
        "regions": [{k:v for k,v in r.items() if k != "H"} for r in regions],
        "openings": openings,
        "overlay_path": str(overlay_path),
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source-image", type=Path, required=True)
    p.add_argument("--multiview-json", type=Path, required=True)
    p.add_argument("--building-obj", type=Path, required=True)
    p.add_argument("--registration-json", type=Path, required=True)
    p.add_argument("--output-json", type=Path, required=True)
    p.add_argument("--overlay", type=Path, required=True)
    p.add_argument("--sam-model-id", default="facebook/sam2.1-hiera-small")
    args = p.parse_args()
    payload = build_detail(
        source_image=args.source_image,
        multiview_json=args.multiview_json,
        building_obj=args.building_obj,
        registration_json=args.registration_json,
        output_json=args.output_json,
        overlay_path=args.overlay,
        sam_model_id=args.sam_model_id,
    )
    print(f"facade detail openings: {payload['opening_count']} counts={payload['counts']}")
    print(f"json: {args.output_json}")
    print(f"overlay: {args.overlay}")


if __name__ == "__main__":
    main()
