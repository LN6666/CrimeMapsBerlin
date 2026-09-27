"""Conservative local name matching. Coordinates are candidates, never GPS observations."""

import re
from collections import defaultdict
from difflib import get_close_matches

from shapely import line_merge
from shapely.geometry import Point, mapping, shape
from shapely.ops import nearest_points, substring, transform, unary_union

from .feed import mentions
from .location_text import (
    CONTEXTUAL_GENERIC_NAMES,
    DISTRICT_NAMES,
    GENERIC_NAMES,
    INCIDENT_ACTIONS,
    INCIDENT_WORDS,
    NameMatcher,
    contextual_locality,
    incident_at_location,
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

GEOCODE_VERSION = "4"
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
        if re.search(r"durchsuchungsbeschl", intro):
            return min(districts, key=lambda r: r["metric"].area) if districts else None
        neighbourhoods = []
        for match, ids in self.locality_matcher.matches(intro):
            dispatched = re.search(r"\bnach\s+$", intro[: match.start()]) and re.search(
                r"alarmiert", intro[match.end() :]
            )
            if (
                not dispatched
                and not contextual_locality(intro, match.start())
                and not locative(intro, match.start())
            ):
                continue
            if station_context(intro, match.start(), match.end(), match[0]) or (
                not dispatched
                and mention_role(intro, match.start(), match.end())
                in {"direction", "travel_origin", "destination"}
            ):
                continue
            for ident in sorted(ids):
                row = self.localities[ident]
                # "In Mitte/Spandau/Pankow" can mean the district, rather than its namesake Ortsteil.
                explicit_neighbourhood = re.search(
                    r"\b(?:ortsteil|stadtteil)\s+(?:berlin-)?$", intro[: match.start()]
                )
                if not explicit_neighbourhood and any(
                    normalize(d["name"]) == normalize(row["name"]) for d in districts
                ):
                    continue
                if row.get("admin_level") == "10" and (
                    district_area.is_empty or district_area.covers(row["metric"].representative_point())
                ):
                    neighbourhoods.append(row)
        # A district heading with the same name as a neighbourhood must not select that neighbourhood.
        if neighbourhoods:
            return neighbourhoods[0]
        return min(districts, key=lambda r: r["metric"].area) if districts else None

    def _scene_scope(self, district, sentences, selected_index, selected):
        # A journey may cross neighbourhoods: retain explicit context consistent with the scene.
        # The official district boundary still applies, even if the source contradicts it.
        default = self._scope(district, "")
        nearest = None
        for sentence in reversed(sentences[: selected_index + 1]):
            scope = self._scope(district, sentence)
            if scope and scope.get("admin_level") == "10":
                nearest = nearest or scope
                if all(self._intersects_scope(m, scope) for m in selected):
                    return scope
        if (
            nearest
            and district in {"bezirksübergreifend", "bundeslandübergreifend"}
            and re.search(r"kreuzung|einmündung", sentences[selected_index])
            and not self._scope(district, sentences[selected_index])
        ):
            # An explicit later junction in a cross-district pursuit is not clipped to its origin.
            return default
        return nearest or default

    def _intersects_scope(self, match, scope):
        if match["kind"] == "street":
            return not self._road(match["key"], scope).is_empty
        feature = self.places[match["key"]]
        geometry = transform(TO_METRIC, shape(feature.get("location_geometry", feature["geometry"])))
        return scope["metric"].buffer(30).intersects(geometry)

    def _junction_anchors(self, linked, matches, sentence, previous, previous_index):
        """Retain a named junction across adjacent travel/collision sentences."""
        roads = {m["key"] for m in linked if m["kind"] == "street"}
        if len(roads) != 1 or any(m["kind"] == "place" for m in linked):
            return linked
        previous_roads = [
            m for m in self._matches(previous) if m["kind"] == "street" and m["role"] == "primary"
        ]
        if re.search(r"kreuzung|einmündung", previous):
            origins = {m["key"] for m in matches if m["role"] == "travel_origin"}
            anchors = [m for m in previous_roads if m["key"] in origins]
        elif (
            re.search(r"kreuzung|einmündung|\bhöhe\b", sentence)
            and re.search(r"abbog|abgebogen|fuhr|stiess", sentence)
            and (
                preparatory_location(previous)
                or (re.search(r"unterwegs", previous) and not INCIDENT_WORDS.search(previous))
            )
        ):
            anchors = previous_roads if len(previous_roads) == 1 else []
        else:
            anchors = []
        return linked + [
            dict(m, role="junction_anchor", sentence_index=previous_index)
            for m in anchors
            if m["key"] not in roads
        ]

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
                if re.search(r"bushaltestelle\s+$", sentence[: match.start()]) and re.match(
                    r"\s+(?:nord|süd|ost|west)\b", sentence[match.end() :]
                ):
                    continue  # A qualified stop name is not its same-named road.
                if name in CONTEXTUAL_GENERIC_NAMES and not (
                    re.search(r"\b(?:strasse|namens)\s+[„“\"]?$", sentence[: match.start()])
                    or sentence[max(0, match.start() - 1) : match.start()] in {"/", '"', "„"}
                    or sentence[match.end() : match.end() + 1] == "/"
                ):
                    continue
                if name in self.locality_names and contextual_locality(sentence, match.start()):
                    continue
                rows.append(
                    dict(kind="street", key=name, alias=match[0], start=match.start(), end=match.end())
                )
        for match, ids in self.place_matcher.matches(sentence):
            for ident in sorted(ids):
                p = self.places[ident]["properties"]
                if normalize(p["name"]) in CONTEXTUAL_GENERIC_NAMES and not venue_context(
                    sentence, match.start()
                ):
                    continue
                if (
                    p["kind"] in {"park", "attraction"}
                    and any(
                        m["kind"] == "street" and m["start"] == match.start() and m["end"] == match.end()
                        for m in rows
                    )
                    and not venue_context(sentence, match.start())
                ):
                    continue
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
        place_spans = {
            (m["start"], m["end"])
            for m in rows
            if m["kind"] == "place"
            and (
                self.places[m["key"]]["properties"]["kind"] == "station"
                or venue_context(sentence, m["start"])
            )
        }
        rows = [m for m in rows if m["kind"] != "street" or (m["start"], m["end"]) not in place_spans]
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
        unscoped = []
        ignored = []
        scene_options = []
        fallback = []
        moving_response = False
        mobile_context = re.search(r"\b(?:im zug|im bus|während der fahrt)\b", " ".join(sentences))
        for i, sentence in enumerate(sentences):
            matches = self._matches(sentence)
            primary = [m for m in matches if m["role"] == "primary"]
            ignored.extend(
                dict(name=m["alias"], role=m["role"], sentence_index=i)
                for m in matches
                if m["role"] != "primary"
            )
            if primary:
                unscoped.extend(primary)
                if any(locative(sentence, m["start"]) or m["kind"] == "place" for m in primary):
                    linked = [m for m in primary if incident_at_location(sentence, m)]
                    if (linked and re.search(r",\s*als\b", sentence)) or (
                        re.search(r"kreuzung|einmündung", sentence) and re.search(r"\bund\s+kollid", sentence)
                    ):
                        # The collision clause can refer back to the road in the preceding travel clause.
                        linked = primary
                    # A following action may refer back to this driveway, control point or junction.
                    # Do not jump over an intervening different place (e.g. boarding -> later bus stop).
                    keys = {(m["kind"], m["key"]) for m in primary}
                    for j in range(i + 1, min(i + 3, len(sentences))):
                        following = sentences[j]
                        next_primary = [m for m in self._matches(following) if m["role"] == "primary"]
                        if any((m["kind"], m["key"]) not in keys for m in next_primary):
                            break
                        if (
                            not linked
                            and (
                                next_primary
                                or re.match(
                                    r"daraufhin|dabei|dort|anschliessend|beim\b|als\b|in der folge|"
                                    r"auf der kreuzung|zum selben zeitpunkt|"
                                    r"kurz (?:hinter|vor) der bushaltestelle\b|"
                                    r"(?:die|der)\s+(?:insassen|fahrer|mann|frau|tatverdächtigen|täter)\b|"
                                    r"(?:die|der|ein|eine)\s+\d{1,3}-jährig\w*\b|"
                                    r"dieses\b|dieser\b|das fahrzeug\b",
                                    following,
                                )
                            )
                            and (INCIDENT_ACTIONS.search(following) or INCIDENT_WORDS.search(following))
                        ):
                            linked = primary
                            break
                    if linked:
                        if i:
                            linked = self._junction_anchors(
                                linked, matches, sentence, sentences[i - 1], i - 1
                            )
                        scene_options.append((i, linked))
                    elif not preparatory_location(sentence):
                        if (
                            mobile_context
                            and re.search(r"alarmiert", sentence)
                            and all(
                                m["kind"] == "place"
                                and self.places[m["key"]]["properties"]["kind"] == "station"
                                for m in primary
                            )
                        ):
                            # A response station cannot establish the location of an attack in transit.
                            moving_response = True
                        else:
                            fallback.append((i, primary))
        result["excluded_location_context"] = ignored
        if scene_options:
            selected_index, selected = scene_options[0]
            result["location_selection"] = "first_explicit_incident_scene"
            keys = {(m["kind"], m["key"]) for m in selected}
            result["other_scene_candidates"] = [
                dict(name=m["alias"], sentence_index=i)
                for i, matches in scene_options[1:]
                for m in matches
                if (m["kind"], m["key"]) not in keys
            ]
        elif fallback:
            selected_index, selected = fallback[0]
            result["location_selection"] = "narrative_location"
        if not selected and unscoped:
            # Name-only lists are candidates, not an incident coordinate.
            result["geocode_candidates"] = sorted({m["alias"] for m in unscoped})
            result["geocode_method"] = (
                "moving_scene_review"
                if moving_response
                else "travel_origin_review"
                if all(preparatory_location(s) for s in sentences if self._matches(s))
                else "unscoped_locations_review"
            )
            result["location_label"] = " / ".join(result["geocode_candidates"])
            if any(self._section_reference(s, self._matches(s)) for s in sentences):
                result["geocode_method"] = "street_section_review"
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
        scope = self._scene_scope(district, sentences, selected_index, selected)
        result["geocode_evidence"] = [
            dict(
                name=m["alias"],
                kind=m["kind"],
                role=m["role"],
                sentence_index=m.get("sentence_index", selected_index),
            )
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
        if self._section_reference(sentence, selected):
            return self._street_section(selected, sentence, scope, result)
        if 2 <= len(roads) <= 4 and (
            any(m["role"] == "junction_anchor" for m in selected)
            or re.search(
                r"kreuzung|kreuzungsbereich|einmündung|ecke|höhe|/|\bbog\b|\beinbog\b|abbiegen|überquer|"
                r"\b(?:fuhr|fuhren)\b.*?\bin\b.*?\bein\b",
                sentence,
            )
        ):
            junction = self._junction(roads)
            if junction is not None:
                point, extent = junction
                return self._located(result, point, "named_street_intersection", "street", extent)
            result["geocode_method"] = "junction_geometry_review"
            return result
        if len(roads) != 1:
            result["geocode_method"] = "multiple_locations_review"
            return result
        road = roads[0]
        # Measure geographic extent, not the summed lengths of parallel OSM fragments.
        connected = road.buffer(15)
        if self._span(road) > 3000:
            result["geocode_method"] = "long_or_ambiguous_street_review"
            return self._candidate_road(result, road)
        if connected.geom_type != "Polygon":
            result["geocode_method"] = "disconnected_street_review"
            return self._candidate_road(result, road)
        point = nearest_points(connected.representative_point(), road)[1]
        return self._located(result, point, "street_representative", "street", self._span(road))

    @staticmethod
    def _candidate_road(result, road):
        """Display matched road parts without inventing an incident point or filling gaps.

        The input has already passed scene selection and locality clipping. Display-only
        simplification is in metres; original geometry still controls all geocode checks.
        A clipped geometry can contain boundary-touch points, which are not road ranges.
        """
        def lines(geometry):
            if geometry.geom_type == "LineString":
                return [geometry]
            return [line for part in getattr(geometry, "geoms", []) for line in lines(part)]

        parts = lines(road)
        if parts:
            geometry = line_merge(unary_union(parts)).simplify(5, preserve_topology=True)
            result["candidate_road_geometry"] = mapping(transform(TO_WGS, geometry))
        return result

    @staticmethod
    def _span(geometry):
        return max(geometry.bounds[2] - geometry.bounds[0], geometry.bounds[3] - geometry.bounds[1])

    @classmethod
    def _junction(cls, roads):
        """One compact common junction, allowing up to 20 m between mapped carriageways.

        Every named road must meet the cluster. Distant/multiple crossings cannot be averaged.
        """
        exact = roads[0]
        for road in roads[1:]:
            exact = exact.intersection(road)
        if not exact.is_empty and exact.geom_type in {"Point", "MultiPoint"} and cls._span(exact) <= 75:
            return exact.representative_point(), cls._span(exact)
        area = roads[0].buffer(10)
        for road in roads[1:]:
            area = area.intersection(road.buffer(10))
        if area.is_empty or cls._span(area) > 75:
            return None
        point = nearest_points(area.representative_point(), roads[0])[1]
        if any(point.distance(road) > 20 for road in roads):
            return None
        return point, cls._span(area)

    @staticmethod
    def _section_reference(sentence, matches):
        for between in re.finditer(r"\bzwischen\b", sentence):
            roads = sorted(
                (m for m in matches if m["kind"] == "street" and m["start"] >= between.end()),
                key=lambda m: m["start"],
            )
            if (
                len(roads) >= 2
                and re.fullmatch(r"\s*(?:(?:der|dem|den)\s+)?", sentence[between.end() : roads[0]["start"]])
                and re.fullmatch(
                    r"\s+(?:und|bis)\s+(?:(?:der|dem|den|zur|zum)\s+)?",
                    sentence[roads[0]["end"] : roads[1]["start"]],
                )
            ):
                return True
        return False

    def _street_section(self, selected, sentence, scope, result):
        """A reported section is represented on its main road, not at a boundary road."""
        split = re.search(r"\bzwischen\b", sentence).start()
        names = sorted((m for m in selected if m["kind"] == "street"), key=lambda m: m["start"])
        anchors = [m for m in names if m["end"] <= split]
        boundaries = list(dict.fromkeys(m["key"] for m in names if m["start"] > split))
        if not anchors or len(boundaries) != 2:
            result["geocode_method"] = "street_section_review"
            return result
        main = anchors[-1]["key"]
        road = self._road(main, scope)
        ends = [self._junction([road, self._road(name, scope)]) for name in boundaries]
        if any(end is None for end in ends):
            result["geocode_method"] = "street_section_review"
            return result
        merged = line_merge(road)
        lines = list(merged.geoms) if merged.geom_type == "MultiLineString" else [merged]
        sections = []
        for line in lines:
            if line.geom_type != "LineString" or any(line.distance(end[0]) > 20 for end in ends):
                continue
            segment = substring(line, line.project(ends[0][0]), line.project(ends[1][0]))
            if segment.geom_type == "LineString" and segment.length > 1:
                sections.append(segment)
        if not sections:
            result["geocode_method"] = "street_section_review"
            return result
        geometry = unary_union(sections)
        if self._span(geometry) > 3000 or geometry.buffer(15).geom_type != "Polygon":
            result["geocode_method"] = "street_section_review"
            return result
        point = max(sections, key=lambda line: line.length).interpolate(0.5, normalized=True)
        result["reported_location_geometry"] = mapping(transform(TO_WGS, geometry))
        result["location_label"] = f"{main} (zwischen {' / '.join(boundaries)})"
        return self._located(result, point, "reported_street_section", "street", self._span(geometry))

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
