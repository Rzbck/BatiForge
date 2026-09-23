from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import requests


DEFAULT_WMS_URL = "https://data.geopf.fr/wms-r"
DEFAULT_LAYER = "ORTHOIMAGERY.ORTHOPHOTOS"


def image_size_for_bbox(
    bbox: tuple[float, float, float, float],
    *,
    gsd_m: float = 0.20,
    max_pixels: int = 4096,
) -> tuple[int, int]:
    if gsd_m <= 0:
        raise ValueError("gsd_m must be > 0")
    if max_pixels < 1:
        raise ValueError("max_pixels must be >= 1")
    min_x, min_y, max_x, max_y = map(float, bbox)
    width_m = max_x - min_x
    height_m = max_y - min_y
    if width_m <= 0 or height_m <= 0:
        raise ValueError("bbox must have positive area")

    width = max(1, int(math.ceil(width_m / gsd_m)))
    height = max(1, int(math.ceil(height_m / gsd_m)))
    scale = min(1.0, max_pixels / width, max_pixels / height)
    return max(1, int(round(width * scale))), max(1, int(round(height * scale)))


def build_wms_params(
    bbox: tuple[float, float, float, float],
    *,
    layer: str,
    width: int,
    height: int,
    crs: str = "EPSG:2154",
    image_format: str = "image/jpeg",
) -> dict[str, str]:
    min_x, min_y, max_x, max_y = map(float, bbox)
    return {
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "REQUEST": "GetMap",
        "LAYERS": layer,
        "STYLES": "",
        "CRS": crs,
        "BBOX": f"{min_x},{min_y},{max_x},{max_y}",
        "WIDTH": str(int(width)),
        "HEIGHT": str(int(height)),
        "FORMAT": image_format,
        "TRANSPARENT": "FALSE",
    }


def fetch_orthophoto(
    context: dict[str, Any],
    output_image: Path,
    *,
    layer: str = DEFAULT_LAYER,
    gsd_m: float = 0.20,
    max_pixels: int = 4096,
    wms_url: str = DEFAULT_WMS_URL,
    timeout_s: float = 60.0,
) -> dict[str, Any]:
    crop = context.get("crop_abs_xy")
    if not isinstance(crop, dict):
        raise ValueError("context metadata has no crop_abs_xy")
    bbox = (
        float(crop["min_x"]),
        float(crop["min_y"]),
        float(crop["max_x"]),
        float(crop["max_y"]),
    )
    width, height = image_size_for_bbox(bbox, gsd_m=gsd_m, max_pixels=max_pixels)
    params = build_wms_params(bbox, layer=layer, width=width, height=height)

    response = requests.get(wms_url, params=params, timeout=timeout_s)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if not content_type.startswith("image/"):
        preview = response.text[:500] if response.content else "<empty response>"
        raise RuntimeError(
            f"IGN WMS returned {content_type or 'unknown content type'} instead of image: {preview}"
        )
    if len(response.content) < 100:
        raise RuntimeError("IGN WMS image response is unexpectedly small")

    output_image.parent.mkdir(parents=True, exist_ok=True)
    output_image.write_bytes(response.content)

    width_m = bbox[2] - bbox[0]
    height_m = bbox[3] - bbox[1]
    return {
        "source": "IGN Geoplateforme WMS-Raster",
        "wms_url": wms_url,
        "layer": layer,
        "crs": "EPSG:2154",
        "bbox_abs_xy": {
            "min_x": bbox[0],
            "min_y": bbox[1],
            "max_x": bbox[2],
            "max_y": bbox[3],
        },
        "image": {
            "path": str(output_image),
            "content_type": content_type,
            "bytes": len(response.content),
            "width_px": width,
            "height_px": height,
            "requested_gsd_m": gsd_m,
            "effective_gsd_x_m": width_m / width,
            "effective_gsd_y_m": height_m / height,
        },
        "request_url": response.url,
    }


def write_textured_obj(
    source_obj: Path,
    output_obj: Path,
    output_mtl: Path,
    image_name: str,
    context: dict[str, Any],
) -> dict[str, int]:
    georef = context.get("georeference")
    crop = context.get("crop_abs_xy")
    if not isinstance(georef, dict) or not isinstance(crop, dict):
        raise ValueError("context metadata is missing georeference/crop_abs_xy")

    origin_x = float(georef["origin_x"])
    origin_y = float(georef["origin_y"])
    min_x = float(crop["min_x"])
    min_y = float(crop["min_y"])
    max_x = float(crop["max_x"])
    max_y = float(crop["max_y"])
    span_x = max_x - min_x
    span_y = max_y - min_y
    if span_x <= 0 or span_y <= 0:
        raise ValueError("invalid context crop")

    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for raw_line in source_obj.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("v "):
            parts = line.split()
            if len(parts) < 4:
                raise ValueError(f"invalid OBJ vertex: {raw_line}")
            vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
        elif line.startswith("f "):
            face: list[int] = []
            for token in line.split()[1:]:
                index = int(token.split("/", 1)[0])
                if index <= 0:
                    raise ValueError("negative/zero OBJ indices are not supported")
                face.append(index)
            if len(face) >= 3:
                faces.append(tuple(face))

    if not vertices or not faces:
        raise ValueError("source OBJ contains no usable vertices/faces")

    uvs: list[tuple[float, float]] = []
    for x, y, _z in vertices:
        abs_x = x + origin_x
        abs_y = y + origin_y
        u = (abs_x - min_x) / span_x
        v = (abs_y - min_y) / span_y
        uvs.append((min(1.0, max(0.0, u)), min(1.0, max(0.0, v))))

    output_obj.parent.mkdir(parents=True, exist_ok=True)
    with output_obj.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("# BatiForge LiDAR context textured with official IGN orthophoto\n")
        handle.write(f"mtllib {output_mtl.name}\n")
        handle.write("o context_ground_ortho\n")
        for x, y, z in vertices:
            handle.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
        for u, v in uvs:
            handle.write(f"vt {u:.8f} {v:.8f}\n")
        handle.write("usemtl ign_orthophoto\n")
        for face in faces:
            refs = " ".join(f"{index}/{index}" for index in face)
            handle.write(f"f {refs}\n")

    with output_mtl.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("newmtl ign_orthophoto\n")
        handle.write("Ka 1.000000 1.000000 1.000000\n")
        handle.write("Kd 1.000000 1.000000 1.000000\n")
        handle.write("Ks 0.000000 0.000000 0.000000\n")
        handle.write("d 1.0\n")
        handle.write("illum 1\n")
        handle.write(f"map_Kd {image_name}\n")

    return {"vertex_count": len(vertices), "face_count": len(faces), "uv_count": len(uvs)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch IGN orthophoto and texture a BatiForge context OBJ")
    parser.add_argument("--context-json", type=Path, required=True)
    parser.add_argument("--source-obj", type=Path, required=True)
    parser.add_argument("--output-image", type=Path, required=True)
    parser.add_argument("--output-obj", type=Path, required=True)
    parser.add_argument("--output-mtl", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--layer", default=DEFAULT_LAYER)
    parser.add_argument("--gsd-m", type=float, default=0.20)
    parser.add_argument("--max-pixels", type=int, default=4096)
    parser.add_argument("--wms-url", default=DEFAULT_WMS_URL)
    args = parser.parse_args()

    context = json.loads(args.context_json.read_text(encoding="utf-8"))
    ortho = fetch_orthophoto(
        context,
        args.output_image,
        layer=args.layer,
        gsd_m=args.gsd_m,
        max_pixels=args.max_pixels,
        wms_url=args.wms_url,
    )
    mesh = write_textured_obj(
        args.source_obj,
        args.output_obj,
        args.output_mtl,
        args.output_image.name,
        context,
    )
    manifest = {
        "schema_version": 1,
        "method": "official IGN orthophoto WMS texture projected from metric XY",
        "context_json": str(args.context_json),
        "source_obj": str(args.source_obj),
        "orthophoto": ortho,
        "mesh": mesh,
        "local_axes": "X east / Y north / Z up",
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    image = ortho["image"]
    print(
        f"context ortho: layer={ortho['layer']} image={image['width_px']}x{image['height_px']} "
        f"gsd={image['effective_gsd_x_m']:.3f}x{image['effective_gsd_y_m']:.3f}m "
        f"vertices={mesh['vertex_count']} faces={mesh['face_count']}"
    )
    print(f"image: {args.output_image}")
    print(f"obj: {args.output_obj}")
    print(f"mtl: {args.output_mtl}")
    print(f"json: {args.output_json}")


if __name__ == "__main__":
    main()
