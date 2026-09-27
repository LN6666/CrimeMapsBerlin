"""Conservative local name matching. Coordinates are candidates, never GPS observations."""

import re
from collections import defaultdict
from difflib import get_close_matches

from shapely.geometry import Point, shape
from shapely.ops import nearest_points, transform, unary_union

from .feed import mentions
from .location_text import (
    DISTRICT_NAMES,
    GENERIC_NAMES,
    INCIDENT_WORDS,
    NameMatcher,
    contextual_locality,
    locative,
    mention_role,
    name_aliases,
    narrative_sentences,
    normalize,
    preparatory_location,
    station_context,
    venue_context,
)
from .spatial import TO_METRIC, TO_WGS

GEOCODE_VERSION = "2"
NON_INCIDENT = re.compile(
    r"bilanz|allgemeinverfügung|aktionstag|videoschutz|präventions|speedweek|"
    r"gemeinsam für mehr sicherheit|stadtweite durchsuchungs|koordinierte internationale kontroll"
)


class Gazetteer:
    def __init__(self, streets, places=None, localities=None, addresses=None):
        groups = defaultdict(list)
        for row in streets:
            name = normalize(row.get("name", ""))
            if (
                len(name) < 4
                or name in GENERIC_NAMES
                or "/" in name
                or re.match(r"(?:[us](?:\+u)?\s|polizeidirektion\s)", name)
                or row.get("highway") in {"platform", "elevator", "corridor", "steps"}
            ):
                continue
            groups[name].append(shape(row["geometry"]))
        self.names = {name: unary_union(geometries) for name, geometries in groups.items()}
        self.street_matcher = NameMatcher(
            (alias, name) for name in self.names for alias in name_aliases(name)
        )
        self.street_cache = {}
        self.localities = {
            str(row.get("id", i)): dict(row, metric=transform(TO_METRIC, shape(row["geometry"])))
            for i, row in enumerate(localities or [])
        }
        self.locality_matcher = NameMatcher(
            (normalize(row["name"]), ident) for ident, row in self.localities.items()
        )
        self.locality_names = DISTRICT_NAMES | {normalize(r["name"]) for r in self.localities.values()}
        self.places = {f["properties"]["id"]: f for f in (places or {}).get("features", [])}
        place_aliases = []
        for ident, f in self.places.items():
            p = f["properties"]
            for name in [p["name"], *p.get("aliases", [])]:
                if not name or len(name) < 4 or name == p["kind"]:
                    continue
                variants = name_aliases(name)
                if p["kind"] == "station":
                    variants |= {
                        re.sub(r"^(?:berlin[- ]|[us](?:\+u)?[- ](?:bahnhof\s+)?|bahnhof\s+)", "", v)
                        for v in variants
                    }
                for alias in variants:
                    place_aliases.append((alias, ident))
        self.place_matcher = NameMatcher(place_aliases)
        self.addresses = defaultdict(list)
        for row in addresses or []:
            self.addresses[(normalize(row["street"]), normalize(row["number"]).replace(" ", ""))].append(row)

    def _scope(self, district, intro):
        districts = [
            self.localities[i]
            for _, ids in self.locality_matcher.matches(normalize(district))
            for i in sorted(ids)
            if self.localities[i].get("admin_level") == "9"
        ]
        district_area = unary_union([r["metric"] for r in districts])
        neighbourhoods = []
        for match, ids in self.locality_matcher.matches(intro):
            if not contextual_locality(intro, match.start()) and not locative(intro, match.start()):
                continue
            for ident in sorted(ids):
                row = self.localities[ident]
                if row.get("admin_level") == "10" and (
                    district_area.is_empty or district_area.covers(row["metric"].representative_point())
                ):
                    neighbourhoods.append(row)
        # A district heading with the same name as a neighbourhood must not select that neighbourhood.
        # Narrative order matters: a smaller later destination must not replace the initial locality.
        if neighbourhoods:
            return neighbourhoods[0]
        return min(districts, key=lambda r: r["metric"].area) if districts else None

    def _road(self, name, scope):
        key = name, scope["id"] if scope else None
        if key not in self.street_cache:
            road = transform(TO_METRIC, self.names[name])
            if scope:
                # Street centre lines can fall just outside an administrative street-side boundary.
                road = road.intersection(scope["metric"].buffer(30))
            self.street_cache[key] = road
        return self.street_cache[key]

    def _matches(self, sentence):
        rows = []
        for match, names in self.street_matcher.matches(sentence):
            for name in sorted(names):
                if name in self.locality_names and contextual_locality(sentence, match.start()):
                    continue
                rows.append(
                    dict(kind="street", key=name, alias=match[0], start=match.start(), end=match.end())
                )
        for match, ids in self.place_matcher.matches(sentence):
            for ident in sorted(ids):
                p = self.places[ident]["properties"]
                if p["kind"] not in {"station", "park", "attraction"} and not venue_context(
                    sentence, match.start()
                ):
                    continue
                if match[0] in self.locality_names | {"berlin", "deutschland"} and p["kind"] != "station":
                    if not venue_context(sentence, match.start()):
                        continue
                if p["kind"] == "station" and not station_context(
                    sentence, match.start(), match.end(), match[0]
                ):
                    continue
                if not locative(sentence, match.start()) and not station_context(
                    sentence, match.start(), match.end(), match[0]
                ):
                    continue
                rows.append(
                    dict(kind="place", key=ident, alias=match[0], start=match.start(), end=match.end())
                )
        for row in rows:
            row["role"] = mention_role(sentence, row["start"], row["end"])
        return rows

    def _suggestions(self, text):
        suggestions = set()
        for token in set(re.findall(r"\b[\w-]+(?:strasse|allee|damm|ring)\b", text)):
            if token not in self.names:
                suggestions.update(get_close_matches(token, self.names, n=2, cutoff=0.9))
        return sorted(suggestions)

    def locate(self, body, *, title="", district=""):
        sentences = narrative_sentences(body)
        result = dict(
            coordinates=None,
            location_precision="unknown",
            location_label=district,
            geocode_method="unmatched",
            geocode_candidates=[],
            geocode_version=GEOCODE_VERSION,
            location_object_ids=[],
            geocode_evidence=[],
        )
        if NON_INCIDENT.search(normalize(title)):
            result["geocode_method"] = "non_incident_report"
            return result
        selected = []
        selected_index = 0
        refined_travel = False
        unscoped = []
        ignored = []
        for i, sentence in enumerate(sentences):
            matches = self._matches(sentence)
            primary = [m for m in matches if m["role"] == "primary"]
            ignored.extend(dict(name=m["alias"], reason=m["role"]) for m in matches if m["role"] != "primary")
            if primary:
                unscoped.extend(primary)
                if any(locative(sentence, m["start"]) or m["kind"] == "place" for m in primary):
                    selected, selected_index = primary, i
                    if preparatory_location(sentence):
                        for j in range(i + 1, len(sentences)):
                            next_sentence = sentences[j + 1] if j + 1 < len(sentences) else ""
                            if not INCIDENT_WORDS.search(sentences[j]) and not (
                                re.match(r"daraufhin|dabei|dort|anschliessend", next_sentence)
                                and INCIDENT_WORDS.search(next_sentence)
                            ):
                                continue
                            scene = [m for m in self._matches(sentences[j]) if m["role"] == "primary"]
                            if scene and any(
                                locative(sentences[j], m["start"]) or m["kind"] == "place" for m in scene
                            ):
                                selected, selected_index, refined_travel = scene, j, True
                                break
                        if not refined_travel and any(m["kind"] == "place" for m in primary):
                            result.update(
                                geocode_method="travel_origin_review",
                                geocode_candidates=sorted({m["alias"] for m in primary}),
                            )
                            return result
                    # A following explicit junction can refine a road already mentioned as travel context.
                    keys = {m["key"] for m in primary if m["kind"] == "street"}
                    for j in range(i + 1, min(i + 3, len(sentences))):
                        if (
                            not refined_travel
                            and not re.search(r"kreuzung|einmündung|ecke|/", sentence)
                            and re.search(r"kreuzung|einmündung|ecke", sentences[j])
                        ):
                            junction = [m for m in self._matches(sentences[j]) if m["role"] == "primary"]
                            if keys & {m["key"] for m in junction}:
                                selected, selected_index = junction, j
                                break
                    break
        if not selected and unscoped:
            # Name-only lists are candidates, not an incident coordinate.
            result["geocode_candidates"] = sorted({m["alias"] for m in unscoped})
            result["geocode_method"] = "unscoped_locations_review"
            result["location_label"] = " / ".join(result["geocode_candidates"])
            return result
        if not selected:
            suggestions = self._suggestions(" ".join(sentences))
            result["geocode_candidates"] = suggestions
            if suggestions:
                result["geocode_method"] = "spelling_review"
            elif ignored:
                result["geocode_method"] = "only_nonincident_locations"
            elif district and district not in {
                "berlinweit",
                "bundesweit",
                "bezirksübergreifend",
                "bundeslandübergreifend",
                "Berlin/Brandenburg",
            }:
                result["location_precision"] = "district"
                result["geocode_method"] = "district_only"
            return result
        sentence = sentences[selected_index]
        scope = self._scope(
            district, sentence if refined_travel else " ".join(sentences[: selected_index + 1])
        )
        result["geocode_evidence"] = [
            dict(name=m["alias"], kind=m["kind"], role=m["role"], sentence_index=selected_index)
            for m in selected
        ]
        result["geocode_candidates"] = sorted({m["alias"] for m in selected})
        result["location_label"] = " / ".join(result["geocode_candidates"])
        if scope:
            result["location_scope"] = scope["name"]
        place_ids = sorted({m["key"] for m in selected if m["kind"] == "place"})
        road_names = sorted({m["key"] for m in selected if m["kind"] == "street"})
        if place_ids:
            return self._locate_place(place_ids, road_names, scope, result)
        roads = [self._road(name, scope) for name in road_names]
        if len(roads) == 1 and re.search(
            r"[\w-]+(?:strasse|allee|alle|damm|ring|platz|weg)\s*/\s*[\w-]+", sentence
        ):
            result["geocode_method"] = "incomplete_junction_review"
            return result
        if any(road.is_empty for road in roads):
            result["geocode_method"] = "locality_conflict_review"
            return result
        if len(road_names) == 1:
            match = next(m for m in selected if m["kind"] == "street")
            number = re.match(r"\s+(?:hausnummer\s+|nr\.?\s+)?(\d+[a-z]?)\b", sentence[match["end"] :])
            if number:
                addresses = self.addresses.get((road_names[0], number[1]), [])
                points = [transform(TO_METRIC, Point(a["coordinates"])) for a in addresses]
                points = [p for p in points if not scope or scope["metric"].covers(p)]
                if points and self._span(unary_union(points)) <= 50:
                    point = min(points, key=lambda p: (p.x, p.y))
                    return self._located(
                        result, point, "osm_address", "address", self._span(unary_union(points))
                    )
        if len(roads) == 2 and re.search(r"kreuzung|kreuzungsbereich|einmündung|ecke|höhe|/", sentence):
            intersection = roads[0].intersection(roads[1])
            if intersection.geom_type in {"Point", "MultiPoint"} and not intersection.is_empty:
                if self._span(intersection) <= 75:
                    return self._located(
                        result,
                        intersection.representative_point(),
                        "named_street_intersection",
                        "street",
                        self._span(intersection),
                    )
        if len(roads) != 1:
            result["geocode_method"] = "multiple_locations_review"
            return result
        road = roads[0]
        # Measure geographic extent, not the summed lengths of parallel OSM fragments.
        connected = road.buffer(15)
        if self._span(road) > 3000:
            result["geocode_method"] = "long_or_ambiguous_street_review"
            return result
        if connected.geom_type != "Polygon":
            result["geocode_method"] = "disconnected_street_review"
            return result
        point = nearest_points(connected.representative_point(), road)[1]
        return self._located(result, point, "street_representative", "street", self._span(road))

    @staticmethod
    def _span(geometry):
        return max(geometry.bounds[2] - geometry.bounds[0], geometry.bounds[3] - geometry.bounds[1])

    @staticmethod
    def _located(result, point, method, precision, extent):
        point = transform(TO_WGS, point)
        result.update(
            coordinates=[round(point.x, 7), round(point.y, 7)],
            location_precision=precision,
            geocode_method=method,
            location_extent_m=round(extent),
        )
        return result

    def _locate_place(self, ids, road_names, scope, result):
        places = []
        for ident in ids:
            f = self.places[ident]
            # Use the original footprint/point, never the synthetic 50m display circle.
            geometry = shape(f.get("location_geometry", f["geometry"]))
            metric = transform(TO_METRIC, geometry)
            if scope and not scope["metric"].buffer(30).intersects(metric):
                continue
            if road_names and not any(self._road(n, scope).distance(metric) <= 100 for n in road_names):
                continue
            places.append((ident, metric))
        if not places:
            result["geocode_method"] = "locality_conflict_review"
            return result
        # Same-named branches remain unresolved. Nearby station nodes can describe one complex.
        connected = unary_union([g.buffer(75) for _, g in places])
        if connected.geom_type != "Polygon":
            result["geocode_method"] = "ambiguous_place_review"
            return result
        extent = self._span(unary_union([g for _, g in places]))
        if extent > 1100:
            result["geocode_method"] = "wide_place_review"
            return result
        ids = [ident for ident, _ in places]
        # Prefer a real footprint; the representative is inside it, not a presumed incident GPS point.
        geometry = max((g for _, g in places), key=lambda g: g.area)
        result["location_object_ids"] = ids
        result["location_label"] = " / ".join(sorted({self.places[i]["properties"]["name"] for i in ids}))
        return self._located(
            result, geometry.representative_point(), "named_place_representative", "place", extent
        )


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
        location = gazetteer.locate(r["body"], title=r["title"], district=r["district"])
        poi_kinds = mentions(r["body"])
        if location["location_precision"] == "place":
            poi_kinds = sorted(
                set(poi_kinds)
                | {gazetteer.places[i]["properties"]["kind"] for i in location["location_object_ids"]}
            )
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
                poi_mentions=poi_kinds,
                mention_basis="official_report_named_place"
                if location["location_precision"] == "place"
                else "official_report_keyword_match",
                outcome="unknown",
                source_status="unavailable"
                if r["http_status"] in (404, 410)
                else "refresh_failed"
                if r["error"]
                else "available",
                source_sha256=r["sha256"],
                source_revision=r["revision"],
                **location,
            )
        )
    return rows
