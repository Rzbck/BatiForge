from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def build_contact_sheet(image_paths: list[Path], output_path: Path, *, thumb_width: int = 420) -> dict[str, Any]:
    from PIL import Image, ImageDraw, ImageFont

    valid: list[tuple[Path, Image.Image]] = []
    for path in image_paths:
        try:
            image = Image.open(path).convert("RGB")
        except Exception:
            continue
        valid.append((path, image))
    if not valid:
        raise RuntimeError("No readable images for contact sheet")

    margin = 24
    caption_h = 48
    rows: list[tuple[Path, Image.Image, int, int]] = []
    total_h = margin
    max_w = thumb_width + 2 * margin
    for path, image in valid:
        scale = thumb_width / max(1, image.width)
        h = max(1, int(round(image.height * scale)))
        resized = image.resize((thumb_width, h), Image.Resampling.LANCZOS)
        rows.append((path, resized, thumb_width, h))
        total_h += h + caption_h + margin

    sheet = Image.new("RGB", (max_w, total_h), (28, 28, 32))
    draw = ImageDraw.Draw(sheet)
    y = margin
    for idx, (path, image, w, h) in enumerate(rows, start=1):
        sheet.paste(image, (margin, y))
        y += h + 8
        label = f"{idx:02d}  {path.name}"
        draw.text((margin, y), label, fill=(240, 240, 240))
        y += caption_h + margin - 8

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)
    return {
        "schema_version": 1,
        "output_path": str(output_path),
        "image_count": len(rows),
        "images": [str(path) for path, *_ in rows],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build one vertical contact sheet from facade evidence images")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("images", nargs="*", type=Path)
    args = parser.parse_args()
    result = build_contact_sheet(args.images, args.output)
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"contact sheet: {result['image_count']} image(s) -> {result['output_path']}")


if __name__ == "__main__":
    main()
