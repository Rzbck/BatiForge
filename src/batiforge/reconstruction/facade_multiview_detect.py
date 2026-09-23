from __future__ import annotations

import argparse
import json
from pathlib import Path

from batiforge.reconstruction.facade_opening_grounding import detect_grounded_openings


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Grounding DINO opening detection over multiple facade evidence images")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model-id", default="IDEA-Research/grounding-dino-base")
    parser.add_argument("--box-threshold", type=float, default=0.24)
    parser.add_argument("--text-threshold", type=float, default=0.20)
    parser.add_argument("images", nargs="+", type=Path)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for index, image in enumerate(args.images, start=1):
        if not image.is_file():
            continue
        target = args.output_dir / f"{index:02d}-{image.stem}"
        target.mkdir(parents=True, exist_ok=True)
        try:
            result = detect_grounded_openings(
                image,
                target,
                model_id=args.model_id,
                box_threshold=args.box_threshold,
                text_threshold=args.text_threshold,
            )
            result["status"] = "detected"
        except Exception as exc:
            result = {
                "image_path": str(image),
                "status": "no_usable_openings",
                "error": str(exc),
                "opening_count": 0,
            }
        results.append(result)
        print(f"[{index:02d}] {image.name}: {result.get('status')} openings={result.get('opening_count', 0)}")

    summary = {
        "schema_version": 1,
        "model_id": args.model_id,
        "image_count": len(results),
        "detected_image_count": sum(r.get("status") == "detected" for r in results),
        "total_openings": sum(int(r.get("opening_count", 0)) for r in results),
        "results": results,
    }
    path = args.output_dir / "multiview-detections.json"
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"summary: {path}")


if __name__ == "__main__":
    main()
