"""Conservative local name matching. Coordinates are candidates, never GPS observations."""

import re
import unicodedata
from collections import defaultdict

from shapely.geometry import shape
from shapely.ops import transform, unary_union

from .feed import mentions
from .spatial import TO_METRIC, TO_WGS


def normalize(text):
    return unicodedata.normalize("NFKC", text).casefold().replace("ß", "ss")


class Gazetteer:
    def __init__(self, streets):
        groups = defaultdict(list)
        for row in streets:
            if row.get("name") and len(row["name"]) >= 6:
                groups[normalize(row["name"])].append(shape(row["geometry"]))
        self.names = {name: unary_union(geometries) for name, geometries in groups.items()}
        self.pattern = (
            re.compile(
                r"(?<!\w)(?:"
                + "|".join(re.escape(n) for n in sorted(self.names, key=len, reverse=True))
                + r")(?!\w)"
            )
            if groups
            else None
        )

    def locate(self, body):
        # Limit to initial incident narrative; not later hospital / police-station destinations.
        intro = normalize(body[:900])
        names = list(dict.fromkeys(self.pattern.findall(intro))) if self.pattern else []
        result = dict(
            coordinates=None,
            location_precision="unknown",
            location_label=" / ".join(names),
            geocode_method="unmatched",
            geocode_candidates=names,
        )
        if not names:
            return result
        if len(names) > 2:
            result["geocode_method"] = "multiple_locations_review"
            return result
        geometries = [transform(TO_METRIC, self.names[n]) for n in names]
        if len(names) == 2:
            intersection = geometries[0].intersection(geometries[1])
            if intersection.is_empty or intersection.geom_type != "Point":
                result["geocode_method"] = "multiple_locations_review"
                return result
            point = intersection
            method = "named_street_intersection"
        else:
            road = geometries[0]
            # Widely separated homonyms and lengthy roads cannot yield a useful point.
            if (
                road.length > 3000
                or max(road.bounds[2] - road.bounds[0], road.bounds[3] - road.bounds[1]) > 3000
            ):
                result["geocode_method"] = "long_or_ambiguous_street_review"
                return result
            if road.geom_type == "MultiLineString":
                from shapely import line_merge

                road = line_merge(road)
                if road.geom_type == "MultiLineString" and len(road.geoms) > 3:
                    result["geocode_method"] = "disconnected_street_review"
                    return result
            point = road.interpolate(0.5, normalized=True)
            method = "street_midpoint"
        point = transform(TO_WGS, point)
        result.update(
            coordinates=[round(point.x, 7), round(point.y, 7)],
            location_precision="street",
            geocode_method=method,
        )
        return result


CATEGORY_RULES = [
    ("Raub", r"raub|ausgeraub|überfall"),
    ("Diebstahl", r"diebstahl|diebe|gestohlen|einbruch|einbrecher"),
    (
        "Gewalt",
        r"angriff|angegriffen|angreif|greift|verletz|attack|messer|schuss|schüsse|körperverletz|getötet|tötungs|mord|geschlagen",
    ),
    ("Sachbeschädigung", r"sachbeschädig|beschädigt|vandal|brandstift"),
    ("Bedrohung", r"bedroht|bedrohung|erpress"),
    ("Sexualdelikt", r"sexual|vergewaltig"),
    ("Betäubungsmittel", r"drogen|betäubungsmittel|dealer"),
    ("Betrug", r"betrug|betrüger"),
]


def category(title):
    low = title.casefold()
    if re.search(r"verkehrsunfall|\bunfall\b|angefahren|zusammenstoß|tretroller|kollision", low):
        return "Verkehr / sonstige Meldung", False
    for label, pattern in CATEGORY_RULES:
        if re.search(pattern, low):
            return label, True
    return "Unklassifiziert", False


def events_from_db(db, gazetteer):
    rows = []
    for r in db.execute("SELECT * FROM reports WHERE body IS NOT NULL ORDER BY published,id"):
        label, crime = category(r["title"])
        rows.append(
            dict(
                id=r["id"],
                title=r["title"],
                category=label,
                is_crime_report=crime,
                published_at=r["published"],
                event_date=None,
                month=r["published"][:7],
                time_basis="publication_month",
                source_url=r["url"],
                district=r["district"],
                poi_mentions=mentions(r["body"]),
                mention_basis="official_report_keyword_match",
                outcome="unknown",
                source_status="unavailable"
                if r["http_status"] in (404, 410)
                else "refresh_failed"
                if r["error"]
                else "available",
                source_sha256=r["sha256"],
                source_revision=r["revision"],
                **gazetteer.locate(r["body"]),
            )
        )
    return rows
