from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests


DEFAULT_WFS_URL = "https://data.geopf.fr/wfs/ows"
DEFAULT_LAYERS = (
    "IGNF_LIDAR-HD_METADONNEE:metadata",
)


@dataclass(frozen=True, slots=True)
class TileResource:
    name: str
    url: str
    projection: str | None
    layer: str


def crop_from_footprint(footprint: dict[str, Any], margin_m: float) -> tuple[float, float, float, float]:
    if margin_m < 0:
        raise ValueError("margin_m must be >= 0")
    bounds = footprint.get("bounds")
    if not isinstance(bounds, dict):
        raise ValueError("footprint has no bounds")
    return (
        float(bounds["min_x"]) - margin_m,
        float(bounds["min_y"]) - margin_m,
        float(bounds["max_x"]) + margin_m,
        float(bounds["max_y"]) + margin_m,
    )


def _download_url_from_properties(properties: dict[str, Any]) -> str | None:
    # Since September 2026 the unified IGN LiDAR-HD WFS metadata layer
    # exposes the classified point-cloud URL in `url_npl`.
    preferred_keys = (
        "url_npl",
        "url",
        "download_url",
        "href",
        "lien",
        "link",
    )
    for key in preferred_keys:
        value = properties.get(key)
        if isinstance(value, str) and value.startswith(("https://", "http://")):
            lower = value.lower()
            if key == "url_npl" or ".laz" in lower or "copc" in lower:
                return value
    for value in properties.values():
        if not isinstance(value, str):
            continue
        lower = value.lower()
        if value.startswith(("https://", "http://")) and (".laz" in lower or "copc" in lower):
            return value
    return None


def _resource_name(properties: dict[str, Any], url: str) -> str:
    for key in ("name_download", "filename", "name", "nom", "nom_dalle"):
        value = properties.get(key)
        if isinstance(value, str) and value.strip():
            name = value.strip()
            if key == "name" and not name.lower().endswith((".laz", ".las")):
                name += ".copc.laz"
            return Path(name).name
    path_name = Path(urlparse(url).path).name
    return path_name or "lidar-tile.copc.laz"


def query_wfs_tiles(
    crop: tuple[float, float, float, float],
    *,
    wfs_url: str = DEFAULT_WFS_URL,
    layers: tuple[str, ...] = DEFAULT_LAYERS,
    timeout_s: float = 30.0,
) -> list[TileResource]:
    min_x, min_y, max_x, max_y = crop
    errors: list[str] = []
    for layer in layers:
        params = {
            "SERVICE": "WFS",
            "VERSION": "2.0.0",
            "REQUEST": "GetFeature",
            "TYPENAMES": layer,
            "OUTPUTFORMAT": "application/json",
            "SRSNAME": "EPSG:2154",
            "BBOX": f"{min_x},{min_y},{max_x},{max_y},EPSG:2154",
            "COUNT": "50",
        }
        try:
            response = requests.get(wfs_url, params=params, timeout=timeout_s)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # pragma: no cover - exercised on host/network
            errors.append(f"{layer}: {exc}")
            continue

        features = payload.get("features") if isinstance(payload, dict) else None
        if not isinstance(features, list):
            errors.append(f"{layer}: response has no feature list")
            continue

        resources: list[TileResource] = []
        for feature in features:
            if not isinstance(feature, dict):
                continue
            properties = feature.get("properties")
            if not isinstance(properties, dict):
                continue
            url = _download_url_from_properties(properties)
            if not url:
                continue
            resources.append(
                TileResource(
                    name=_resource_name(properties, url),
                    url=url,
                    projection=str(properties.get("projection")) if properties.get("projection") else None,
                    layer=layer,
                )
            )
        if resources:
            unique: dict[str, TileResource] = {}
            for resource in resources:
                unique.setdefault(resource.url, resource)
            return sorted(unique.values(), key=lambda item: item.name)
        errors.append(f"{layer}: {len(features)} features but no downloadable point-cloud URL")

    raise RuntimeError("No downloadable LiDAR tiles found. " + " | ".join(errors))


def download_tile(resource: TileResource, destination: Path, *, timeout_s: float = 120.0) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size > 0:
        return {
            "name": resource.name,
            "url": resource.url,
            "path": str(destination),
            "bytes": destination.stat().st_size,
            "status": "existing",
            "projection": resource.projection,
            "layer": resource.layer,
        }

    tmp = destination.with_suffix(destination.suffix + ".part")
    if tmp.exists():
        tmp.unlink()
    try:
        with requests.get(resource.url, stream=True, timeout=timeout_s) as response:
            response.raise_for_status()
            with tmp.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
        tmp.replace(destination)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise

    return {
        "name": resource.name,
        "url": resource.url,
        "path": str(destination),
        "bytes": destination.stat().st_size,
        "status": "downloaded",
        "projection": resource.projection,
        "layer": resource.layer,
    }


def fetch_context_tiles(
    footprint_json: Path,
    output_dir: Path,
    *,
    margin_m: float = 25.0,
    wfs_url: str = DEFAULT_WFS_URL,
) -> dict[str, Any]:
    footprint = json.loads(footprint_json.read_text(encoding="utf-8"))
    crop = crop_from_footprint(footprint, margin_m)
    resources = query_wfs_tiles(crop, wfs_url=wfs_url)
    results = [download_tile(resource, output_dir / resource.name) for resource in resources]
    return {
        "schema_version": 2,
        "source": "IGN Geoplateforme WFS unified LiDAR-HD metadata layer",
        "wfs_url": wfs_url,
        "layers_tried": list(DEFAULT_LAYERS),
        "footprint_json": str(footprint_json),
        "target_crs": footprint.get("target_crs"),
        "margin_m": margin_m,
        "crop_abs_xy": {
            "min_x": crop[0],
            "min_y": crop[1],
            "max_x": crop[2],
            "max_y": crop[3],
        },
        "tile_count": len(results),
        "tiles": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch official IGN LiDAR HD tiles covering a BatiForge context crop")
    parser.add_argument("--footprint-json", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--margin-m", type=float, default=25.0)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--wfs-url", default=DEFAULT_WFS_URL)
    args = parser.parse_args()

    manifest = fetch_context_tiles(
        args.footprint_json,
        args.output_dir,
        margin_m=args.margin_m,
        wfs_url=args.wfs_url,
    )
    manifest_path = args.manifest or (args.output_dir / "context-lidar-fetch.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"official context tiles: {manifest['tile_count']}")
    for tile in manifest["tiles"]:
        mib = tile["bytes"] / (1024 * 1024)
        print(f"  {tile['status']:10s} {tile['name']}  {mib:.2f} MiB")
    print(f"manifest: {manifest_path}")


if __name__ == "__main__":
    main()
