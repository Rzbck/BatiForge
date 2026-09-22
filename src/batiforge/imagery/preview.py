from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests


MAX_PREVIEW_BYTES = 5 * 1024 * 1024


def shortlist_candidates(
    candidates: list[dict[str, Any]],
    *,
    max_items: int = 24,
    per_sequence: int = 4,
) -> list[dict[str, Any]]:
    """Return a deterministic, sequence-diverse preview shortlist.

    Priority is deliberately conservative:
    1. non-panoramic views with target_in_fov=True;
    2. non-panoramic front views with unknown FOV;
    3. panoramas, which can look in every horizontal direction.

    A known target_in_fov=False candidate is not promoted merely because its
    heading falls inside the broader 45-degree "front" geometry class.
    """

    if max_items <= 0:
        raise ValueError("max_items must be > 0")
    if per_sequence <= 0:
        raise ValueError("per_sequence must be > 0")

    ranked: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    for candidate in candidates:
        panoramic = candidate.get("panoramic") is True or candidate.get("view_class") == "panoramic"
        in_fov = candidate.get("target_in_fov")
        view_class = candidate.get("view_class")

        if not panoramic and in_fov is True:
            tier = 0
        elif not panoramic and view_class == "front" and in_fov is None:
            tier = 1
        elif panoramic:
            tier = 2
        else:
            continue

        try:
            distance = float(candidate.get("distance_m"))
        except (TypeError, ValueError):
            distance = float("inf")

        try:
            heading_error = float(candidate.get("heading_error_deg"))
        except (TypeError, ValueError):
            heading_error = 999.0

        source_id = str(candidate.get("source_id") or "")
        ranked.append(((tier, distance, heading_error, source_id), candidate))

    ranked.sort(key=lambda item: item[0])

    sequence_counts: dict[str, int] = {}
    selected: list[dict[str, Any]] = []

    for _, candidate in ranked:
        source_id = str(candidate.get("source_id") or "")
        sequence_id = candidate.get("sequence_id")
        group_key = str(sequence_id) if sequence_id else f"__unsequenced__:{source_id}"

        if sequence_counts.get(group_key, 0) >= per_sequence:
            continue

        selected.append(candidate)
        sequence_counts[group_key] = sequence_counts.get(group_key, 0) + 1

        if len(selected) >= max_items:
            break

    return selected


def thumbnail_url_from_item(item: dict[str, Any]) -> str | None:
    """Return only an explicitly advertised thumbnail derivative URL."""

    properties = item.get("properties")
    if isinstance(properties, dict):
        legacy = properties.get("geovisio:thumbnail")
        if isinstance(legacy, str) and legacy.strip():
            return legacy.strip()

    assets = item.get("assets")
    if not isinstance(assets, dict):
        return None

    for asset in assets.values():
        if not isinstance(asset, dict):
            continue
        roles = asset.get("roles")
        href = asset.get("href")
        if (
            isinstance(roles, list)
            and "thumbnail" in roles
            and isinstance(href, str)
            and href.strip()
        ):
            return href.strip()

    for key in ("thumbnail", "thumb"):
        asset = assets.get(key)
        if isinstance(asset, dict):
            href = asset.get("href")
            if isinstance(href, str) and href.strip():
                return href.strip()

    return None


def _is_http_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _extension_for_content_type(content_type: str) -> str:
    normalized = content_type.split(";", 1)[0].strip().lower()
    return {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
        "image/png": ".png",
    }.get(normalized, ".img")


def _download_one(
    session: requests.Session,
    candidate: dict[str, Any],
    *,
    output_dir: Path,
    rank: int,
    timeout_s: float,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "rank": rank,
        "source_id": candidate.get("source_id"),
        "sequence_id": candidate.get("sequence_id"),
        "distance_m": candidate.get("distance_m"),
        "view_class": candidate.get("view_class"),
        "target_in_fov": candidate.get("target_in_fov"),
        "heading_error_deg": candidate.get("heading_error_deg"),
        "captured_at": candidate.get("captured_at"),
        "source_url": candidate.get("source_url"),
        "status": "failed",
    }

    source_url = candidate.get("source_url")
    if not _is_http_url(source_url):
        result["error"] = "missing or invalid metadata source_url"
        return result

    try:
        metadata_response = session.get(source_url, timeout=timeout_s)
        metadata_response.raise_for_status()
        item = metadata_response.json()
    except (requests.RequestException, ValueError) as exc:
        result["error"] = f"metadata request failed: {exc}"
        return result

    if not isinstance(item, dict):
        result["error"] = "metadata response is not an object"
        return result

    thumbnail_url = thumbnail_url_from_item(item)
    result["thumbnail_url"] = thumbnail_url

    if not _is_http_url(thumbnail_url):
        result["error"] = "no explicit thumbnail derivative advertised"
        return result

    try:
        preview_response = session.get(thumbnail_url, timeout=timeout_s)
        preview_response.raise_for_status()
    except requests.RequestException as exc:
        result["error"] = f"thumbnail request failed: {exc}"
        return result

    content_type = preview_response.headers.get("Content-Type", "")
    if not content_type.lower().startswith("image/"):
        result["error"] = f"thumbnail returned non-image content type: {content_type!r}"
        return result

    content = preview_response.content
    if len(content) > MAX_PREVIEW_BYTES:
        result["error"] = f"thumbnail exceeds {MAX_PREVIEW_BYTES} byte safety limit"
        return result

    source_id = str(candidate.get("source_id") or f"rank-{rank}")
    safe_source = "".join(ch for ch in source_id if ch.isalnum() or ch in "-_")
    suffix = _extension_for_content_type(content_type)
    filename = f"{rank:02d}_{safe_source}{suffix}"
    file_path = output_dir / "thumbnails" / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(content)

    result["status"] = "downloaded"
    result["local_file"] = f"thumbnails/{filename}"
    result["bytes"] = len(content)
    result["content_type"] = content_type.split(";", 1)[0].strip()
    return result


def _write_gallery(output_dir: Path, manifest: dict[str, Any]) -> None:
    cards: list[str] = []
    for item in manifest["items"]:
        source_id = html.escape(str(item.get("source_id") or ""))
        sequence_id = html.escape(str(item.get("sequence_id") or "—"))
        view_class = html.escape(str(item.get("view_class") or "unknown"))
        distance = html.escape(str(item.get("distance_m") or "?"))
        in_fov = html.escape(str(item.get("target_in_fov")))
        local_file = item.get("local_file")

        if isinstance(local_file, str):
            media = f'<img loading="lazy" src="{html.escape(local_file)}" alt="{source_id}">'
        else:
            media = f'<div class="missing">{html.escape(str(item.get("error") or "preview unavailable"))}</div>'

        source_url = item.get("source_url")
        link = (
            f'<a href="{html.escape(source_url)}" target="_blank" rel="noreferrer">metadata source</a>'
            if _is_http_url(source_url)
            else ""
        )

        cards.append(
            "<article>"
            f"{media}"
            f"<h2>#{item['rank']} · {distance} m · {view_class}</h2>"
            f"<p><code>{source_id}</code></p>"
            f"<p>sequence: <code>{sequence_id}</code><br>target_in_fov: {in_fov}</p>"
            f"<p>{link}</p>"
            "</article>"
        )

    page = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>BatiForge Panoramax preview shortlist</title>
<style>
body{font-family:system-ui,sans-serif;margin:24px;background:#111;color:#eee}
header{max-width:1100px;margin:auto auto 24px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;max-width:1500px;margin:auto}
article{background:#1d1d1d;border:1px solid #333;border-radius:10px;overflow:hidden;padding-bottom:12px}img,.missing{display:block;width:100%;height:220px;object-fit:cover;background:#2a2a2a}.missing{box-sizing:border-box;padding:24px;color:#aaa}h2,p{margin:10px 14px}h2{font-size:1rem}p{font-size:.86rem;color:#ccc;overflow-wrap:anywhere}a{color:#8dc8ff}code{font-size:.78rem}
</style>
</head>
<body>
<header><h1>BatiForge · Panoramax preview shortlist</h1><p>Thumbnail derivatives only. This gallery is for visual target/occlusion inspection, not photogrammetric input.</p></header>
<div class="grid">""" + "\n".join(cards) + """</div>
</body>
</html>
"""
    (output_dir / "index.html").write_text(page, encoding="utf-8", newline="\n")


def build_preview_gallery(
    survey_path: Path,
    output_dir: Path,
    *,
    max_items: int,
    per_sequence: int,
    timeout_s: float,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    payload = json.loads(survey_path.read_text(encoding="utf-8"))
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("survey JSON has no candidates list")

    selected = shortlist_candidates(
        candidates,
        max_items=max_items,
        per_sequence=per_sequence,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    client = session or requests.Session()
    client.headers.setdefault(
        "User-Agent",
        "BatiForge/0.1 (+https://github.com/Rzbck/BatiForge)",
    )

    items = [
        _download_one(
            client,
            candidate,
            output_dir=output_dir,
            rank=rank,
            timeout_s=timeout_s,
        )
        for rank, candidate in enumerate(selected, start=1)
    ]

    manifest = {
        "schema_version": 1,
        "source_survey": str(survey_path),
        "selected_count": len(selected),
        "downloaded_count": sum(item["status"] == "downloaded" for item in items),
        "failed_count": sum(item["status"] != "downloaded" for item in items),
        "max_items": max_items,
        "per_sequence": per_sequence,
        "items": items,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    _write_gallery(output_dir, manifest)
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a small local Panoramax thumbnail gallery from a BatiForge survey."
    )
    parser.add_argument("--survey", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max", dest="max_items", type=int, default=24)
    parser.add_argument("--per-sequence", type=int, default=4)
    parser.add_argument("--timeout-s", type=float, default=30.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        manifest = build_preview_gallery(
            args.survey,
            args.output_dir,
            max_items=args.max_items,
            per_sequence=args.per_sequence,
            timeout_s=args.timeout_s,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"BatiForge preview gallery failed: {exc}", file=sys.stderr)
        return 2

    print(
        "panoramax previews: "
        f"selected={manifest['selected_count']} "
        f"downloaded={manifest['downloaded_count']} "
        f"failed={manifest['failed_count']} "
        f"-> {args.output_dir / 'index.html'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
