from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _normalise_pages(values: list[int], page_count: int) -> list[int]:
    if page_count <= 0:
        raise ValueError("page_count must be > 0")
    result: list[int] = []
    seen: set[int] = set()
    for value in values:
        page = int(value)
        if page < 1 or page > page_count:
            raise ValueError(f"page {page} outside document range 1..{page_count}")
        if page not in seen:
            seen.add(page)
            result.append(page)
    return result


def render_selected_pdf_pages(
    resolved_manifest: Path,
    output_dir: Path,
    *,
    dpi: int = 180,
) -> dict[str, Any]:
    if dpi < 72:
        raise ValueError("dpi must be >= 72")

    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover - runtime dependency via uv --with
        raise RuntimeError(
            "PyMuPDF is required for PDF evidence rendering. Run through the provided uv runner."
        ) from exc

    data = json.loads(resolved_manifest.read_text(encoding="utf-8"))
    sources = data.get("sources")
    if not isinstance(sources, list):
        raise ValueError("resolved manifest has no sources list")

    output_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[dict[str, Any]] = []

    for source in sources:
        if source.get("kind") != "pdf" or not source.get("extract_pages"):
            continue
        local_path = Path(str(source.get("local_path", "")))
        if not local_path.is_file():
            raise FileNotFoundError(f"downloaded PDF missing for {source.get('id')}: {local_path}")

        document = fitz.open(local_path)
        try:
            pages = _normalise_pages(
                [int(value) for value in source["extract_pages"]], len(document)
            )
            scale = float(dpi) / 72.0
            matrix = fitz.Matrix(scale, scale)
            for page_number in pages:
                page = document.load_page(page_number - 1)
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                target = output_dir / f"{source['id']}-page-{page_number:02d}.png"
                pixmap.save(target)
                rendered.append(
                    {
                        "source_id": source["id"],
                        "source_pdf": str(local_path),
                        "page": page_number,
                        "dpi": dpi,
                        "width_px": int(pixmap.width),
                        "height_px": int(pixmap.height),
                        "local_path": str(target),
                        "geometry_usage": source.get("geometry_usage"),
                        "rights": source.get("rights"),
                    }
                )
        finally:
            document.close()

    result = {
        "schema_version": 1,
        "resolved_manifest": str(resolved_manifest),
        "output_dir": str(output_dir),
        "dpi": dpi,
        "rendered_count": len(rendered),
        "pages": rendered,
    }
    manifest_path = output_dir / "pdf-evidence-pages.json"
    manifest_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render selected pages from downloaded facade evidence PDFs"
    )
    parser.add_argument("--resolved-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--dpi", type=int, default=180)
    args = parser.parse_args()

    result = render_selected_pdf_pages(
        args.resolved_manifest,
        args.output_dir,
        dpi=args.dpi,
    )
    print(f"facade PDF evidence: rendered={result['rendered_count']} dpi={result['dpi']}")
    for item in result["pages"]:
        print(
            f"{item['source_id']} page {item['page']}: "
            f"{item['width_px']}x{item['height_px']} {item['local_path']}"
        )
    print(f"manifest: {Path(result['output_dir']) / 'pdf-evidence-pages.json'}")


if __name__ == "__main__":
    main()
