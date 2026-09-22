from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

from .panoramax import PanoramaxError, PanoramaxProvider


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Discover imagery metadata around a BatiForge target without bulk downloading images."
    )
    parser.add_argument("--site", type=Path, help="TOML site configuration")
    parser.add_argument("--lat", type=float, help="Target latitude (WGS84)")
    parser.add_argument("--lon", type=float, help="Target longitude (WGS84)")
    parser.add_argument("--radius-m", type=float, default=500.0)
    parser.add_argument("--limit", type=int, default=2_000)
    parser.add_argument(
        "--endpoint",
        default="https://panoramax.openstreetmap.fr/api",
        help="Panoramax/STAC API endpoint",
    )
    parser.add_argument("--output", type=Path, help="Write deterministic JSON to this file")
    return parser


def _target_from_args(args: argparse.Namespace) -> tuple[float, float]:
    latitude = args.lat
    longitude = args.lon

    if args.site:
        with args.site.open("rb") as handle:
            site = tomllib.load(handle)
        latitude = latitude if latitude is not None else site.get("latitude")
        longitude = longitude if longitude is not None else site.get("longitude")

    if latitude is None or longitude is None:
        raise ValueError("target requires --site or both --lat and --lon")

    return float(latitude), float(longitude)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    try:
        latitude, longitude = _target_from_args(args)
        provider = PanoramaxProvider(endpoint=args.endpoint)
        result = provider.survey(
            latitude=latitude,
            longitude=longitude,
            radius_m=args.radius_m,
            limit=args.limit,
        )
    except (OSError, ValueError, PanoramaxError) as exc:
        print(f"BatiForge imagery survey failed: {exc}", file=sys.stderr)
        return 2

    payload = result.to_json()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8", newline="\n")
        print(
            f"{result.provider}: {len(result.candidates)} candidates -> {args.output}"
        )
    else:
        sys.stdout.write(payload)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
