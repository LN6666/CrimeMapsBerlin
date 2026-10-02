"""Local paths and publication permissions for the first five cities."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CitySpec:
    name: str
    epsg: int
    source: str
    attribution: str
    source_schema: str
    candidate_enabled: bool
    publication_enabled: bool


@dataclass(frozen=True)
class CityPaths:
    source_db: Path
    raw: Path
    runtime: Path
    public: Path

    def osm_indexes(self, city: str) -> tuple[Path, ...]:
        return (
            self.raw / f"{city}-pois.json",
            self.raw / "streets.json",
            self.raw / "localities.json",
            self.raw / "addresses.json",
        )


CITY_SPECS = {
    "berlin": CitySpec(
        "Berlin", 25833, "Polizei Berlin official archive",
        "© OpenStreetMap contributors / Geofabrik (ODbL); Polizei Berlin",
        "collector", False, True,
    ),
    "hamburg": CitySpec(
        "Hamburg", 25832, "Polizei Hamburg / Presseportal",
        "© OpenStreetMap contributors / Geofabrik (ODbL); Polizei Hamburg",
        "collector", True, True,
    ),
    "cologne": CitySpec(
        "Köln", 25832, "Polizei Köln native press archive",
        "© OpenStreetMap contributors / Geofabrik (ODbL); Polizei Köln",
        "cologne_native", True, False,
    ),
    "frankfurt": CitySpec(
        "Frankfurt am Main", 25832, "Polizeipräsidium Frankfurt am Main / Presseportal",
        "© OpenStreetMap contributors / Geofabrik (ODbL); Polizeipräsidium Frankfurt am Main",
        "collector_frankfurt", True, False,
    ),
    "munich": CitySpec(
        "München", 25832, "POLIZEIKARTE Munich 365-day index linked to police originals",
        "© OpenStreetMap contributors / Geofabrik (ODbL); POLIZEIKARTE; source police publishers",
        "polizeikarte_munich", True, False,
    ),
}


def paths_for(city: str, root: Path) -> CityPaths:
    if city not in CITY_SPECS:
        raise ValueError(f"Unsupported first-group city: {city}")
    base_raw = root / "data/raw/safety"
    base_runtime = root / ".runtime/safety"
    base_public = root / "web/public/safety"
    if city == "berlin":
        return CityPaths(base_runtime / "police.sqlite", base_raw, base_runtime, base_public)
    return CityPaths(
        base_runtime / "cities" / city / "police.sqlite",
        base_raw / "cities" / city,
        base_runtime / "cities" / city,
        base_public / "cities" / city,
    )
