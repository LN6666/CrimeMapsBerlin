"""Fetch, build and validate local-only POI products for the selected cities."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from crimemapsberlin.poi_cities import (
    POI_CITY_SPECS,
    build_city,
    fetch_city_sources,
    runtime_root,
    selected_cities,
)
from crimemapsberlin.poi_validation import validate_city_product

PROJECT = Path(__file__).resolve().parents[2]
CATALOG = PROJECT / "data/safety/europe_sources.json"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build checked OSM POI inputs and local browser tiles without publishing a city map."
    )
    parser.add_argument("command", choices=("fetch", "build", "validate", "run"))
    parser.add_argument("--city", choices=(*POI_CITY_SPECS, "all"), required=True)
    parser.add_argument("--root", type=Path, default=runtime_root(PROJECT))
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="For fetch/run, compare against the current Geofabrik checksum and replace a stale local input.",
    )
    args = parser.parse_args()
    cities = selected_cities(args.city)
    root = args.root.resolve()

    if args.command in {"fetch", "run"}:
        sources = fetch_city_sources(
            cities,
            root=root,
            project_root=PROJECT,
            refresh=args.refresh,
        )
        for region, source in sources.items():
            print(f"{region}: checked {source['pbf_timestamp']} {source['sha256'][:12]}", flush=True)

    if args.command in {"build", "run"}:
        for city in cities:
            report = build_city(city, root=root, project_root=PROJECT, catalog_path=CATALOG)
            print(
                f"{city}: built {report['poi_count']} local POIs and {report['tile_count']} tiles; unpublished",
                flush=True,
            )

    if args.command in {"validate", "run"}:
        for city in cities:
            validation = validate_city_product(
                city,
                root=root,
                project_root=PROJECT,
                catalog_path=CATALOG,
            )
            print(
                json.dumps(
                    {
                        "city": city,
                        "passed": validation["passed"],
                        "poi_count": validation["poi_count"],
                        "tile_count": validation["tile_count"],
                        "publication_ready": False,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
