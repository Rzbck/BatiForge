from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def extract_pdf_page_images(
    pdf_path: Path,
    output_dir: Path,
    *,
    pages: list[int],
    min_width: int = 240,
    min_height: int = 160,
) -> dict[str, Any]:
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PyMuPDF is required") from exc

    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open(pdf_path)
    assets: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    try:
        for page_number in pages:
            if page_number < 1 or page_number > len(doc):
                raise ValueError(f"page {page_number} outside 1..{len(doc)}")
            page = doc.load_page(page_number - 1)
            for image_index, image_info in enumerate(page.get_images(full=True), start=1):
                xref = int(image_info[0])
                extracted = doc.extract_image(xref)
                payload = extracted.get("image", b"")
                if not payload:
                    continue
                width = int(extracted.get("width", 0))
                height = int(extracted.get("height", 0))
                if width < min_width or height < min_height:
                    continue
                digest = _sha256(payload)
                if digest in seen_hashes:
                    continue
                seen_hashes.add(digest)
                ext = str(extracted.get("ext", "png")).lower().strip(".") or "png"
                target = output_dir / f"page-{page_number:02d}-image-{image_index:02d}.{ext}"
                target.write_bytes(payload)
                assets.append(
                    {
                        "page": page_number,
                        "image_index": image_index,
                        "xref": xref,
                        "width_px": width,
                        "height_px": height,
                        "bytes": len(payload),
                        "sha256": digest,
                        "local_path": str(target),
                    }
                )
    finally:
        doc.close()

    result = {
        "schema_version": 1,
        "pdf_path": str(pdf_path),
        "pages": pages,
        "min_width": min_width,
        "min_height": min_height,
        "asset_count": len(assets),
        "assets": assets,
    }
    manifest = output_dir / "pdf-photo-assets.json"
    manifest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract individual raster photo assets from selected PDF pages")
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--pages", type=int, nargs="+", required=True)
    parser.add_argument("--min-width", type=int, default=240)
    parser.add_argument("--min-height", type=int, default=160)
    args = parser.parse_args()

    result = extract_pdf_page_images(
        args.pdf,
        args.output_dir,
        pages=args.pages,
        min_width=args.min_width,
        min_height=args.min_height,
    )
    print(f"pdf photo assets: {result['asset_count']}")
    for item in result["assets"]:
        print(
            f"page {item['page']} image {item['image_index']}: "
            f"{item['width_px']}x{item['height_px']} {item['local_path']}"
        )
    print(f"manifest: {Path(args.output_dir) / 'pdf-photo-assets.json'}")


if __name__ == "__main__":
    main()
