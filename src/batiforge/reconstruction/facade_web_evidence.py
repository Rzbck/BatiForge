from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import requests


_ALLOWED_KINDS = {"image", "pdf", "page"}


def _safe_name(value: str) -> str:
    keep = []
    for char in value.strip():
        if char.isalnum() or char in ("-", "_", "."):
            keep.append(char)
        else:
            keep.append("-")
    name = "".join(keep).strip("-.")
    if not name:
        raise ValueError("empty output filename")
    return name


def validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported facade web evidence schema")
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("manifest must contain at least one source")
    seen: set[str] = set()
    for item in sources:
        if not isinstance(item, dict):
            raise ValueError("source entry must be an object")
        source_id = str(item.get("id", "")).strip()
        if not source_id or source_id in seen:
            raise ValueError("source ids must be non-empty and unique")
        seen.add(source_id)
        kind = str(item.get("kind", "")).strip()
        if kind not in _ALLOWED_KINDS:
            raise ValueError(f"unsupported source kind for {source_id}: {kind}")
        page_url = str(item.get("page_url", "")).strip()
        if not page_url.startswith(("https://", "http://")):
            raise ValueError(f"source {source_id} has no valid page_url")
        if item.get("download", False):
            asset_url = str(item.get("asset_url", "")).strip()
            filename = str(item.get("filename", "")).strip()
            if not asset_url.startswith(("https://", "http://")):
                raise ValueError(f"download source {source_id} has no valid asset_url")
            _safe_name(filename)
        if not str(item.get("rights", "")).strip():
            raise ValueError(f"source {source_id} must record rights/provenance")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_manifest(
    manifest_path: Path,
    output_dir: Path,
    *,
    timeout_s: float = 60.0,
    max_bytes: int = 100_000_000,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_manifest(manifest)
    output_dir.mkdir(parents=True, exist_ok=True)

    resolved: list[dict[str, Any]] = []
    for item in manifest["sources"]:
        record = dict(item)
        record["status"] = "catalogued"
        if item.get("download", False):
            response = requests.get(
                item["asset_url"],
                timeout=timeout_s,
                headers={"User-Agent": "BatiForge/0.1 facade-evidence"},
            )
            response.raise_for_status()
            payload = response.content
            if not payload:
                raise RuntimeError(f"empty response for {item['id']}")
            if len(payload) > max_bytes:
                raise RuntimeError(
                    f"source {item['id']} exceeds max_bytes ({len(payload)} > {max_bytes})"
                )
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            kind = item["kind"]
            if kind == "image" and not content_type.startswith("image/"):
                raise RuntimeError(
                    f"source {item['id']} expected image, got {content_type or 'unknown'}"
                )
            if kind == "pdf" and content_type not in ("application/pdf", "application/octet-stream"):
                raise RuntimeError(
                    f"source {item['id']} expected PDF, got {content_type or 'unknown'}"
                )
            target = output_dir / _safe_name(item["filename"])
            target.write_bytes(payload)
            record.update(
                {
                    "status": "downloaded",
                    "local_path": str(target),
                    "bytes": len(payload),
                    "sha256": _sha256(payload),
                    "content_type": content_type,
                    "resolved_url": response.url,
                }
            )
        resolved.append(record)

    result = {
        "schema_version": 1,
        "source_manifest": str(manifest_path),
        "output_dir": str(output_dir),
        "sources": resolved,
        "downloaded_count": sum(item["status"] == "downloaded" for item in resolved),
        "catalogued_count": len(resolved),
    }
    output_manifest = output_dir / "web-evidence-resolved.json"
    output_manifest.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch explicitly catalogued web facade evidence with provenance"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout-s", type=float, default=60.0)
    parser.add_argument("--max-bytes", type=int, default=100_000_000)
    args = parser.parse_args()

    result = fetch_manifest(
        args.manifest,
        args.output_dir,
        timeout_s=args.timeout_s,
        max_bytes=args.max_bytes,
    )
    print(
        "facade web evidence: "
        f"catalogued={result['catalogued_count']} downloaded={result['downloaded_count']}"
    )
    for item in result["sources"]:
        print(f"{item['id']}: {item['status']} {item.get('local_path', item['page_url'])}")
    print(f"manifest: {Path(result['output_dir']) / 'web-evidence-resolved.json'}")


if __name__ == "__main__":
    main()
