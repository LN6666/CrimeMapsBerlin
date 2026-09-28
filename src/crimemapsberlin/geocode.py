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
    official_scene_heading,
    preparatory_location,
    station_context,
    venue_context,
)
from .multiple_scenes import validated_article_semantics, validated_scene_decision
from .spatial import TO_METRIC, TO_WGS

GEOCODE_VERSION = "5"
MAX_STREET_POINT_SPAN_M = 500
MULTI_EVENT_SUMMARY = re.compile(r"bilanz")
MULTIPLE_OFFICIAL_SCENES = re.compile(r"\b(?:tatorte|unfallorte|orte)\s*:", re.I)
OFFICIAL_LOCATION_HEADING = re.compile(r"\b(?:tatort|unfallort|ort)\s*:", re.I)
SINGULAR_OFFICIAL_SCENE = re.compile(r"\b(?:tatort|unfallort)\s*:", re.I)
MOVING_ROAD_EVENT = re.compile(r"kraftfahrzeugrennen|straßenrennen|strassenrennen")
MULTIPLE_REPORTED_INCIDENTS = re.compile(
    r"\b(?:seit|über)\b.{0,100}\b(?:mehrfach(?:e|en)|wiederholt(?:e|en))\b.{0,60}"
    r"\b(?:diebstähl|einbrüch|taten|vorfällen)"
)
UNNAMED_VENUE = re.compile(
    r"\b(?:spielhalle|tankstelle|supermarkt\w*|wettbüro\w*|imbiss\w*|parkhaus\w*|"
    r"skatepark\w*|bürogebäude\w*|kiosk|apotheke|restaurant|hotel|bar|geschäft|"
    r"verkaufsfiliale|grünfläche|treffen zweier fahrzeuge|"
    r"büroräume|räumlichkeiten eines vereins|gewerbehof(?:es)?|"
    r"betriebs(?:hof(?:es)?|gelände(?:s)?)|firmengelände(?:s)?|"
    r"industrieunternehmen|wohnunterkunft|parkbucht|geschäftsgebäude\w*|geschäftshaus|lagerhalle|"
    r"juweliergeschäft|gewerbepark)\b"
)
UNNAMED_RESIDENTIAL_SCENE = re.compile(
    r"\bvor (?:seiner|ihrer) wohnungstür\b|"
    r"\ban der wohnanschrift,\s+nahm\b|"
    r"\b(?:brach|eingebrochen)\b.{0,80}\bin (?:die|eine?) wohnung\b|"
    r"\b(?:wohnung|wohnhaus|mehrfamilienhaus)\b.{0,100}\b(?:in brand|eingebrochen)\b|"
    r"\bzu ihm ins auto gestiegen\b|"
    r"\b(?:mehrfamilienhaus\w*|treppenhaus\w*|wohnanschrift|wohnhaus\w*)\b|"
    r"\bin (?:seiner|ihrer|einer) wohnung\b"
)
NON_INCIDENT = re.compile(
    r"allgemeinverfügung|aktionstag|videoschutz|präventions|speedweek|"
    r"gemeinsam für mehr sicherheit|stadtweite durchsuchungs|koordinierte internationale kontroll|"
    r"vermisstenfahndung|einladung|kriminalstatistik|verkehrshinweis|pressekonferenz|fototermin|"
    r"bilanz einer aktionswoche|verkehrssicherheitsbilanz|neue streifenboote|"
    r"in hamburg ist man plietsch|"
    r"sendehinweis|nordseegipfel|krimisalon|kriminalpolizeiliche beratung|"
    r"alkoholkonsumverbotszone|verkehrssicherheitsaktion|sicher\.mobil\.leben|"
    r"kinder-hit-tag|lange nacht der museen|erledigung der öffentlichkeitsfahndung|"
    r"ehrenkommissar|jahresempfang|eingeschränkte erreichbarkeit der polizeipressestelle|"
    r"verkehrssicherheitskampagne vorgestellt"
    r"|gemeinsame eingangs-und bearbeitungsstelle|"
    r"befragung zu sicherheit und kriminalität|"
    r"informationstag der polizei|"
    r"frühjahrstagung der arbeitsgemeinschaft der polizeipräsident|"
    r"hinweise der polizei.{0,80}hafengeburtstag|"
    r"taufe.{0,80}polizeiboot|schiffstaufe.{0,100}polizeiboot|"
    r"peterwagen.{0,100}dauerhaft mit blaulicht|"
    r"quattro-streife.{0,100}(?:sichtbarer|präsenter)|"
    r"droneport.{0,100}(?:drohnentechnologie|connect)"
)
EXPLICITLY_UNLOCATED_SCENE = re.compile(
    r"\bnicht\b.{0,160}\beindeutigen lokalisierung des tatortes\b|"
    r"\btatort(?:es)?\b.{0,100}\bnicht eindeutig lokalisiert\b|"
    r"\beindeutig(?:e|en) lokalisierung(?: des tatortes)?\b.{0,100}\b(?:nicht möglich|unmöglich)\b|"
    r"\bfundort\b.{0,80}\bnicht\b.{0,40}\beigentlichen tatort\b|"
    r"\b(?:auffindeort|fundort)\b.{0,80}\b(?:eigentlichen )?tatort\b.{0,40}|"
    r"\b(?:klären|unklar|fraglich)\b|"
    r"\bklären\b.{0,140}\bauffindeort\b.{0,80}\btatort\b"
)
UNCERTAIN_DISCOVERY_SCENE = re.compile(
    r"\bklären\b.{0,140}\bauffindeort\b.{0,80}\btatort\b"
)
OFF_ROAD_SCENE = re.compile(
    r"\b(?:auf einem seeschiff|am bordeigenen kran|auf ein universitätsgelände|"
    r"im bereich des skateparks|führte ihn\b.{0,70}\bzu einem nahegelegenen feldweg|"
    r"am zentralen omnibusbahnhof\w*)\b"
)
UNCERTAIN_RAIL_UNDERPASS = re.compile(r"\bkurz vor der bahnunterführung\b")
MULTI_SITE_OPERATION = re.compile(
    r"\ban einer anderen örtlichkeit umgepackt\b|"
    r"\bermittlungen zu den einzelnen eingeleiteten ermittlungsverfahren\b"
)
OPERATION_LOCATION_ONLY = re.compile(
    r"\b(?:pfänd|beschlagnahm|durchsuch|vollstreck|verhaft|festnahm|festnahme|"
    r"sicherstell)\w*\b"
)
REPORTED_SITE_NOT_SCENE = re.compile(
    r"\beinsatzort\b.{0,100}\bnicht\b.{0,60}\beigentlichen tatort\b"
)
MEDICAL_DEATH_INVESTIGATION = re.compile(
    r"\bmedizinischer notfall\b.{0,160}\b(?:verstirbt|verstorben|tod)\b"
)
STATION_VICINITY = re.compile(
    r"\b(?:im bereich|nahe) des [us](?:\+u)?-bahnhof(?:s)?\b"
)
NAMED_PARK_VICINITY = re.compile(
    r"\bim bereich des ([\w-]+-parks)\b"
)
DISCOVERY_ONLY_SCENE = re.compile(
    r"\bfeststellzeit\s*:.*?\b(?:tödlich verletzte|leblose)\w*\b.{0,180}\baufgefunden\b"
)
MOVING_TRANSIT_SCENE = re.compile(
    r"\b(?:fahrgast\w*\s+)?in einem (?:linien)?bus\b|"
    r"\bin einer? (?:s-bahn|u-bahn|bahn|zug)\b|\bim (?:zug|linienbus)\b"
)
SOURCE_STREET_SUFFIX = re.compile(
    r"(?:strasse|allee|damm|deich|weg|ring|platz|chaussee|stieg|ufer|brücke)\b$"
)
DRUG_HANDOVER = re.compile(
    r"\b(?:übergab|übergaben|überreichte\w*)\b.{0,180}\b(?:im gegenzug|erhielt\w*)\b|"
    r"\bim gegenzug\b.{0,120}\b(?:übergab|erhielt\w*)\b"
)


def source_section_boundaries(sentence):
    """Return verbatim normalized road bounds without fuzzy name substitution."""
    match = re.search(
        r"\bim bereich zwischen\s+(?:dem|der|den)\s+"
        r"(?P<first>[^,;.]{2,80}?)\s+und\s+(?:dem|der|den)\s+"
        r"(?P<second>[^,;.]{2,80}?)"
        r"(?=\s+(?:stiess|stieß|kollid|prall|kam|fuhr|wurde|geriet|ereignete)\b|[,.;]|$)",
        sentence,
    )
    if not match:
        return []
    rows = []
    for group in ("first", "second"):
        name = match[group].strip()
        if not SOURCE_STREET_SUFFIX.search(name):
            return []
        rows.append(dict(name=name, start=match.start(group), end=match.end(group)))
    return rows


def aggregate_control_report(title, body):
    """Identify operation totals whose named control sites are not one offence scene."""
    return bool(
        (
            re.search(r"\bverbundeinsatz\b", title)
            and re.search(
                r"\bstationäre\b.{0,80}\bmobile\b.{0,80}\bverkehrskontrollen\b",
                body,
            )
        )
        or (
            re.search(r"\b(?:bilanz|thementag)\b", title)
            and re.search(r"\b(?:verkehr|wasser|drogen|schiff)\w*\b", title)
            and re.search(r"\bkontroll\w*\b", body)
            and re.search(
                r"\b(?:überprüften|kontrollierten)\b.{0,100}"
                r"\b(?:fahrzeuge|wasserfahrzeuge|personen)\b",
                body,
            )
            and re.search(r"\b(?:straftaten|strafverfahren|ordnungswidrigkeiten)\b", body)
        )
        or (
            re.search(
                r"\bergebnisse\b.{0,120}\b(?:bundesweiten?\s+)?verkehrssicherheitsaktion\b",
                title,
            )
            and re.search(r"\b(?:stationären?\s+und\s+mobilen?\s+)?kontroll\w*\b", body)
            and re.search(r"\b(?:straftaten|strafverfahren|ordnungswidrigkeiten)\b", body)
        )
    )


QUALIFIED_HEIGHT_IMPACT = re.compile(
    r"\bverlor\b.{0,160}\bdie kontrolle\b|\bkam\b.{0,100}\bvon der fahrbahn ab\b|"
    r"\bkollid\w*\b|\bprall\w*\b"
)


def named_woodland_incident(title, body, district):
    """Keep an explicit forest scene without inventing a point from a wide area."""
    if not district or not re.search(r"\btötungsdelikt\b", normalize(title)):
        return None
    heading = re.search(
        r"\bOrt:\s*Hamburg-([^,;]+),\s*([A-ZÄÖÜ][\wÄÖÜäöüß-]*\s+Wald)\b",
        body,
        re.I,
    )
    if not heading or normalize(heading.group(1)) != normalize(district):
        return None
    name = heading.group(2)
    narrative = normalize(body)
    direct_attack = re.search(
        rf"\bim {re.escape(normalize(name))}\b.{{0,50}}\bdort stach\b",
        narrative,
    )
    linked_followup = re.search(
        r"\bzur tatzeit\b.{0,80}\bin dem wald\b.{0,200}"
        r"\bauf ihr opfer eingewirkt\b",
        narrative,
    )
    return name if direct_attack or linked_followup else None


class Gazetteer:
    def __init__(self, streets, places=None, localities=None, addresses=None,
                 *, to_metric=TO_METRIC, to_wgs=TO_WGS):
        self.to_metric = to_metric
        self.to_wgs = to_wgs
        groups = defaultdict(list)
        for row in streets:
            name = normalize(row.get("name", ""))
            if (
                len(name) < 4
                or "/" in name
                or re.match(r"(?:[us](?:\+u)?\s|polizeidirektion\s)", name)
                or row.get("highway") in {"platform", "elevator", "corridor", "steps"}
            ):
                continue
            groups[name].append(shape(row["geometry"]))
        self.names = {name: unary_union(geometries) for name, geometries in groups.items()}
        self.street_matcher = NameMatcher(
            ((alias, name) for name in self.names for alias in name_aliases(name)),
            allow_generic=True,
        )
        self.street_cache = {}
        self.localities = {
            str(row.get("id", i)): dict(row, metric=transform(self.to_metric, shape(row["geometry"])))
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
                        re.sub(r"^(?:(?:berlin|hamburg)[- ]|[us](?:\+u)?[- ](?:bahnhof\s+)?|bahnhof\s+)", "", v)
                        for v in variants
                    }
                for alias in variants:
                    place_aliases.append((alias, ident))
        self.place_matcher = NameMatcher(place_aliases)
        self.addresses = defaultdict(list)
        for row in addresses or []:
            self.addresses[(normalize(row["street"]), normalize(row["number"]).replace(" ", ""))].append(row)

    def _scope(self, district, intro):
        heading = normalize(district)
        heading_neighbourhoods = [
            row for row in self.localities.values()
            if row.get("admin_level") == "10" and normalize(row["name"]) == heading
        ]
        districts = [
            self.localities[i]
            for _, ids in self.locality_matcher.matches(heading)
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
                    r"\b(?:ortsteil|stadtteil)\s+(?:(?:berlin|hamburg)-)?$", intro[: match.start()]
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
        if districts:
            return min(districts, key=lambda r: r["metric"].area)
        return heading_neighbourhoods[0] if len(heading_neighbourhoods) == 1 else None

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
        geometry = transform(self.to_metric, shape(feature.get("location_geometry", feature["geometry"])))
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
            and re.search(r"abbog|\bbog\b|abgebogen|fuhr|stiess", sentence)
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
            road = transform(self.to_metric, self.names[name])
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
                if name in GENERIC_NAMES and not official_scene_heading(sentence, match.start()):
                    continue
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
        rows = [
            row for row in rows
            if not any(
                other["start"] <= row["start"]
                and other["end"] >= row["end"]
                and other["end"] - other["start"] > row["end"] - row["start"]
                for other in rows
            )
        ]
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
        normalized_title = normalize(title)
        normalized_body = normalize(body)
        if not district and not EXPLICITLY_UNLOCATED_SCENE.search(normalized_body):
            neighbourhood_heading = re.search(
                r"\b(?:tatort|unfallort):\s*hamburg-([\w-]+)\b(?!\s*[,/])",
                normalized_body,
            )
            if neighbourhood_heading:
                named_neighbourhoods = {
                    row["name"] for row in self.localities.values()
                    if row.get("admin_level") == "10"
                    and normalize(row["name"]) == neighbourhood_heading[1]
                }
                if len(named_neighbourhoods) == 1:
                    district = named_neighbourhoods.pop()
                    result.update(district=district, location_label=district)
        if not district and re.search(
            r"\b(?:tatort|unfallort|ort)\s*:\s*[^.;]{1,80},\s*"
            r"(?:schleswig-holstein|brandenburg|niedersachsen)\b",
            normalized_body,
        ):
            result["geocode_method"] = "outside_city_report"
            return result
        if aggregate_control_report(normalized_title, normalized_body):
            result["geocode_method"] = "multi_event_summary"
            return result
        if NON_INCIDENT.search(normalized_title) or (
            "öffentlichkeitsfahndung" in normalized_title
            and re.search(r"\bkeine hinweise auf straftaten\b", normalized_body)
        ) or (
            MEDICAL_DEATH_INVESTIGATION.search(normalized_title)
            and re.search(r"\btodesermittlungsverfahren\b", normalized_body)
        ):
            result["geocode_method"] = "non_incident_report"
            return result
        if MULTI_EVENT_SUMMARY.search(normalized_title) or re.search(
            r"\b(?:polizei zieht|ziehen\b.{0,160}?)\s+(?:eine )?(?:positive )?bilanz\b",
            normalized_body,
        ) or MULTIPLE_REPORTED_INCIDENTS.search(normalized_body):
            result["geocode_method"] = "multi_event_summary"
            return result
        if MULTI_SITE_OPERATION.search(normalized_body):
            result["geocode_method"] = "multiple_locations_review"
            return result
        if REPORTED_SITE_NOT_SCENE.search(normalized_body):
            # The source has expressly withdrawn its own earlier scene report.
            result.update(location_label="", geocode_method="reported_site_not_scene")
            return result
        woodland_scene = named_woodland_incident(title, body, district)
        if (
            OPERATION_LOCATION_ONLY.search(normalized_title)
            and re.search(r"\bzeit\s*:", normalized_body)
            and not re.search(r"\b(?:tatzeit|unfallzeit)\s*:", normalized_body)
            and re.search(r"\bort\s*:", normalized_body)
            and not re.search(r"\b(?:tatort|unfallort)\s*:", normalized_body)
            and not woodland_scene
        ):
            result["location_label"] = ""
            result["geocode_method"] = "operation_locations_only"
            return result
        if DISCOVERY_ONLY_SCENE.search(normalized_body) and re.search(
            r"\b(?:tötungsdelikt|mord)\b", normalized_title
        ):
            result["location_precision"] = "district" if district else "unknown"
            result["geocode_method"] = "discovery_only_scene_review"
            return result
        if len(OFFICIAL_LOCATION_HEADING.findall(body)) > 1:
            result["geocode_method"] = "multiple_official_scenes"
            return result
        if MOVING_ROAD_EVENT.search(normalized_title) and not SINGULAR_OFFICIAL_SCENE.search(body):
            # A race described over a route has no single incident point unless
            # the source supplies a separate, explicit scene heading.
            result["geocode_method"] = "moving_scene_review"
            return result
        if MULTIPLE_OFFICIAL_SCENES.search(body):
            # A plural official location heading can name several incident,
            # search or seizure sites. Later narrative detail cannot silently
            # reduce the announcement to one of those places.
            if (
                re.search(r"\borte\s*:", body, re.I)
                and not re.search(r"\b(?:tatorte|unfallorte)\s*:", body, re.I)
                and OPERATION_LOCATION_ONLY.search(normalized_title)
            ):
                result.update(location_label="", geocode_method="operation_locations_only")
                return result
            if (
                OPERATION_LOCATION_ONLY.search(normalized_title)
                and re.search(r"\bzunächst wird auf die pressemitteilung\b", normalized_body)
                and len(re.findall(r"\bhamburg-[^,;]+,", normalized_body.split("zunächst", 1)[0])) == 1
            ):
                result.update(location_label="", geocode_method="followup_report")
                return result
            result["geocode_method"] = "multiple_official_scenes"
            return result
        for index, sentence in enumerate(sentences):
            stop = re.search(
                r"\bin höhe (?:der )?(?:bus)?haltestelle\s+[\"„“]([^\"„“]{2,80})[\"„“]",
                sentence,
            )
            if not stop or not OFFICIAL_LOCATION_HEADING.search(sentence):
                continue
            streets = [
                match
                for match in self._matches(sentence)
                if match["kind"] == "street" and match["end"] <= stop.start()
            ]
            stop_name = stop.group(1).strip()
            result.update(
                location_label=" / ".join(
                    [*(match["alias"] for match in streets), f"bushaltestelle {stop_name}"]
                ),
                geocode_candidates=sorted(
                    {*(match["alias"] for match in streets), stop_name}
                ),
                geocode_method="named_transit_stop_review",
                geocode_evidence=[
                    *(
                        dict(
                            name=match["alias"], kind="street", role="primary",
                            sentence_index=index,
                        )
                        for match in streets
                    ),
                    dict(
                        name=stop_name, kind="source_named_stop", role="primary",
                        sentence_index=index,
                    ),
                ],
                location_selection="official_tatort_heading",
            )
            if district:
                result["location_scope"] = district
            return result
        for heading_index, heading_sentence in enumerate(sentences):
            heading = OFFICIAL_LOCATION_HEADING.search(heading_sentence)
            if not heading or not re.search(r"\(\s*bushaltestelle\s*\)", heading_sentence):
                continue
            heading_streets = [
                match
                for match in self._matches(heading_sentence)
                if match["kind"] == "street" and match["start"] >= heading.end()
            ]
            if not heading_streets:
                continue
            for stop_index in range(heading_index + 1, min(heading_index + 4, len(sentences))):
                stop_sentence = sentences[stop_index]
                stop = re.search(
                    r"\b(?:an|bei) der bushaltestelle\s+[\"„“]([^\"„“]{2,80})[\"„“]",
                    stop_sentence,
                )
                if not stop or not (
                    INCIDENT_ACTIONS.search(stop_sentence) or INCIDENT_WORDS.search(stop_sentence)
                ):
                    continue
                stop_name = stop.group(1).strip()
                road_aliases = list(dict.fromkeys(match["alias"] for match in heading_streets))
                result.update(
                    location_label=" / ".join(
                        [*road_aliases, f"bushaltestelle {stop_name}"]
                    ),
                    geocode_candidates=sorted({*road_aliases, stop_name}),
                    geocode_method="named_transit_stop_review",
                    geocode_evidence=[
                        *(
                            dict(
                                name=match["alias"], kind="street", role="primary",
                                sentence_index=heading_index,
                            )
                            for match in heading_streets
                        ),
                        dict(
                            name=stop_name, kind="source_named_stop", role="primary",
                            sentence_index=stop_index,
                        ),
                    ],
                    location_selection="official_tatort_heading",
                )
                if district:
                    result["location_scope"] = district
                return result
        official_heading = None
        for heading_index, heading_sentence in enumerate(sentences):
            heading = OFFICIAL_LOCATION_HEADING.search(heading_sentence)
            if not heading:
                continue
            heading_streets = [
                match
                for match in self._matches(heading_sentence)
                if match["kind"] == "street" and match["start"] >= heading.end()
            ]
            if heading_streets:
                official_heading = heading_index, heading_streets
                break
        if official_heading:
            heading_index, heading_streets = official_heading
            for scene_index in range(heading_index + 1, len(sentences)):
                scene_sentence = sentences[scene_index]
                scene_pair = " ".join(sentences[scene_index : scene_index + 2])
                if not (
                    re.search(r"\btreffen zweier fahrzeuge\b", scene_sentence)
                    and DRUG_HANDOVER.search(scene_pair)
                ):
                    continue
                localities = [
                    self.localities[ident]
                    for match, identifiers in self.locality_matcher.matches(scene_sentence)
                    if contextual_locality(scene_sentence, match.start())
                    for ident in sorted(identifiers)
                    if self.localities[ident].get("admin_level") == "10"
                    and normalize(self.localities[ident]["name"]) != normalize(district)
                ]
                names = list(dict.fromkeys(normalize(row["name"]) for row in localities))
                if len(names) != 1:
                    continue
                road_aliases = list(dict.fromkeys(match["alias"] for match in heading_streets))
                result.update(
                    location_label=" / ".join([*road_aliases, names[0]]),
                    geocode_candidates=sorted({*road_aliases, names[0]}),
                    geocode_method="conflicting_explicit_scenes",
                    geocode_evidence=[
                        dict(
                            name=match["alias"], kind="street", role="primary",
                            sentence_index=heading_index,
                        )
                        for match in heading_streets
                    ],
                    location_selection="official_tatort_heading",
                    other_scene_candidates=[dict(name=names[0], sentence_index=scene_index)],
                )
                if district:
                    result["location_scope"] = district
                return result
        fixed_station_attack = re.search(
            r"\b(?:haltestelle|bahnhof|station)\b.{0,80}\b(?:attack|angegriff|schlug|beleidig)",
            normalized_body,
        )
        clearly_moving_transit = re.search(
            r"\bkurz vor der haltestelle\b|\bwährend der fahrt\b|"
            r"\bkurz nach dem anfahren des (?:busses|zuges)\b|"
            r"\b(?:angreifer|täter)\b.{0,80}\bverblieb im zug\b",
            normalized_body,
        )
        moving_transit_incident = any(
            MOVING_TRANSIT_SCENE.search(sentence) and INCIDENT_WORDS.search(sentence)
            for sentence in sentences
        )
        if MOVING_TRANSIT_SCENE.search(normalized_body) and (
            clearly_moving_transit or (moving_transit_incident and not fixed_station_attack)
        ):
            result["geocode_method"] = "moving_scene_review"
            return result
        if (
            re.search(r"\bunerlaubt mit blaulicht unterwegs\b", normalized_title)
            and re.search(r"\b(?:bundesautobahn\s*\(bab\)|bundesautobahn|bab)\s*\d+\b", normalized_body)
            and re.search(
                r"\b(?:hielten|hielt|stoppten|stoppt)\b.{0,80}"
                r"\b(?:auto|pkw|fahrzeug)\b.{0,100}\b(?:im bereich|ecke)\b",
                normalized_body,
            )
        ):
            # The named street is where police stopped a car after a moving offence.
            result["geocode_method"] = "moving_scene_review"
            return result
        for index, sentence in enumerate(sentences):
            heading = OFFICIAL_LOCATION_HEADING.search(sentence)
            if not heading:
                continue
            heading_streets = sorted(
                (
                    match for match in self._matches(sentence)
                    if match["kind"] == "street"
                    and heading.end() <= match["start"] <= heading.end() + 180
                ),
                key=lambda match: match["start"],
            )
            connector = (
                sentence[heading_streets[0]["end"] : heading_streets[1]["start"]]
                if len(heading_streets) >= 2 else ""
            )
            list_connectors = [
                sentence[first["end"] : second["start"]]
                for first, second in zip(heading_streets, heading_streets[1:3])
            ]
            if len(heading_streets) >= 3 and all(
                re.fullmatch(
                    r"\s*(?:,|und|sowie)\s*(?:(?:hamburg|berlin)-[^,;]+,\s*)?",
                    value,
                )
                for value in list_connectors
            ):
                result["geocode_candidates"] = sorted(
                    {match["alias"] for match in heading_streets}
                )
                result["location_label"] = " / ".join(result["geocode_candidates"])
                result["geocode_evidence"] = [
                    dict(
                        name=match["alias"], kind="street", role="primary",
                        sentence_index=index,
                    )
                    for match in heading_streets
                ]
                result["location_selection"] = "official_tatort_heading"
                result["geocode_method"] = "multiple_locations_review"
                return result
            if len(heading_streets) >= 2 and re.fullmatch(
                r"\s+(?:und|sowie)\s+(?:(?:hamburg|berlin)-[^,;]+,\s*)?",
                connector,
            ):
                result["geocode_candidates"] = sorted(
                    {match["alias"] for match in heading_streets[:2]}
                )
                result["location_label"] = " / ".join(result["geocode_candidates"])
                result["geocode_evidence"] = [
                    dict(
                        name=match["alias"], kind="street", role="primary",
                        sentence_index=index,
                    )
                    for match in heading_streets[:2]
                ]
                result["location_selection"] = "official_tatort_heading"
                result["geocode_method"] = "multiple_locations_review"
                if len(set(re.findall(r"\bhamburg-([^,;]+),", sentence[:heading_streets[1]["end"]]))) > 1:
                    result["district"] = ""
                return result
        explicitly_unlocated = EXPLICITLY_UNLOCATED_SCENE.search(normalize(body))
        official_named_scene = any(
            any(official_scene_heading(sentence, match["start"]) for match in self._matches(sentence))
            for sentence in sentences
        )
        if explicitly_unlocated and (
            not official_named_scene or UNCERTAIN_DISCOVERY_SCENE.search(normalized_body)
        ):
            result["location_precision"] = "district" if district else "unknown"
            result["geocode_method"] = "explicitly_unlocated_scene"
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
            official_junction = self._official_junction_matches(sentence, matches)
            official_section = self._official_section_matches(sentence, matches)
            promoted = {
                (m["kind"], m["key"], m["start"], m["end"])
                for m in [*official_junction, *official_section]
            }
            primary = [
                dict(m, role="primary")
                if (m["kind"], m["key"], m["start"], m["end"]) in promoted else m
                for m in matches
                if m["role"] == "primary"
                or (m["kind"], m["key"], m["start"], m["end"]) in promoted
            ]
            ignored.extend(
                dict(name=m["alias"], role=m["role"], sentence_index=i)
                for m in matches
                if m["role"] != "primary"
                and (m["kind"], m["key"], m["start"], m["end"]) not in promoted
            )
            if primary:
                unscoped.extend(primary)
                if any(locative(sentence, m["start"]) or m["kind"] == "place" for m in primary):
                    linked = [m for m in primary if incident_at_location(sentence, m)]
                    streets = [m for m in primary if m["kind"] == "street"]
                    has_official_junction = bool(official_junction)
                    official_nearby = (
                        len(streets) >= 2
                        and any(official_scene_heading(sentence, m["start"]) for m in primary)
                        and re.search(r"\(\s*nahe\b", sentence)
                    )
                    near_junction = (
                        len(streets) >= 2
                        and re.search(r"\bkurz (?:hinter|vor) der einmündung\b", sentence)
                    )
                    if has_official_junction or official_nearby or near_junction:
                        linked = primary
                    if official_section:
                        linked = [dict(m, role="primary") for m in official_section]
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
                                    r"daraufhin|dabei|hierbei|dort|anschliessend|beim\b|als\b|in der folge|"
                                    r"im weiteren verlauf|"
                                    r"auf der kreuzung|zum selben zeitpunkt|"
                                    r"kurz (?:hinter|vor) der bushaltestelle\b|"
                                    r"(?:die|der)\s+(?:insassen|fahrer|mann|frau|tatverdächtigen|täter)\b|"
                                    r"(?:die|der|ein|eine)\s+\d{1,3}-jährig\w*\b|"
                                    r"dieses\b|dieser\b|das fahrzeug\b",
                                    following,
                                )
                                or (
                                    re.search(
                                        r"\bbefuhr\b.{0,160}\bund wollte (?:weiter )?(?:auf|in)\b",
                                        sentence,
                                    )
                                    and INCIDENT_ACTIONS.search(following)
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
            official_options = [
                option for option in scene_options
                if any(official_scene_heading(sentences[option[0]], m["start"]) for m in option[1])
            ]
            selected_index, selected = (official_options or scene_options)[0]
            selected_keys = {(m["kind"], m["key"]) for m in selected}
            if len([m for m in selected if m["kind"] == "street"]) == 1:
                for refined_index, refined in scene_options[1:]:
                    refined_keys = {(m["kind"], m["key"]) for m in refined}
                    if (
                        selected_keys < refined_keys
                        and len([m for m in refined if m["kind"] == "street"]) >= 2
                        and (
                            re.search(
                                r"\bkurz (?:hinter|vor) der einmündung\b",
                                sentences[refined_index],
                            )
                            or re.search(
                                r"\bunmittelbar hinter der kreuzung\b",
                                sentences[refined_index],
                            )
                            or (
                                re.search(
                                    r"\b(?:einmündungsbereich|kreuzungsbereich|kreuzung)\b",
                                    sentences[refined_index],
                                )
                                and (
                                    INCIDENT_ACTIONS.search(sentences[refined_index])
                                    or (
                                        refined_index + 1 < len(sentences)
                                        and re.match(
                                            r"(?:dabei|hierbei|dort)\b",
                                            sentences[refined_index + 1],
                                        )
                                        and INCIDENT_ACTIONS.search(sentences[refined_index + 1])
                                    )
                                )
                            )
                            or (
                                re.search(
                                    r"\bbefuhr\b.{0,160}\bund wollte (?:weiter )?(?:auf|in)\b",
                                    sentences[refined_index],
                                )
                                and refined_index + 1 < len(sentences)
                                and INCIDENT_ACTIONS.search(sentences[refined_index + 1])
                            )
                        )
                    ):
                        selected_index, selected = refined_index, refined
                        break
                else:
                    selected_road = next(m["key"] for m in selected if m["kind"] == "street")
                    selected_scope = self._scene_scope(district, sentences, selected_index, selected)
                    for refined_index, refined in scene_options[1:]:
                        named_areas = [
                            m for m in refined
                            if m["kind"] == "place"
                            and self.places[m["key"]]["properties"]["kind"] in {"park", "attraction"}
                            and venue_context(sentences[refined_index], m["start"])
                        ]
                        if named_areas and any(
                            self._road(selected_road, selected_scope).distance(
                                transform(
                                    self.to_metric,
                                    shape(self.places[m["key"]].get(
                                        "location_geometry", self.places[m["key"]]["geometry"]
                                    )),
                                )
                            ) <= 100
                            for m in named_areas
                        ):
                            selected_index, selected = refined_index, named_areas
                            break
            result["location_selection"] = (
                "official_tatort_heading"
                if any(official_scene_heading(sentences[selected_index], m["start"]) for m in selected)
                else "first_explicit_incident_scene"
            )
            keys = {(m["kind"], m["key"]) for m in selected}
            aliases = {normalize(m["alias"]) for m in selected}
            result["other_scene_candidates"] = [
                dict(name=m["alias"], sentence_index=i)
                for i, matches in scene_options
                if (i, matches) != (selected_index, selected)
                if not keys.intersection({(m["kind"], m["key"]) for m in matches})
                for m in matches
                if (m["kind"], m["key"]) not in keys
                and normalize(m["alias"]) not in aliases
                and not (
                    m["kind"] == "place"
                    and self.places[m["key"]]["properties"]["kind"] == "station"
                    and re.search(r"\bverbale auseinandersetzung\b", sentences[i])
                )
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
            if woodland_scene:
                result.update(
                    location_precision="district",
                    location_label=woodland_scene,
                    location_scope=district,
                    location_selection="first_explicit_incident_scene",
                    geocode_candidates=[normalize(woodland_scene)],
                    geocode_method="named_area_geometry_review",
                    geocode_evidence=[dict(name=woodland_scene, kind="source_named_area", role="primary")],
                )
                return result
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
        if (
            result.get("location_selection") == "official_tatort_heading"
            and result.get("other_scene_candidates")
            and re.search(r"\b(?:aufbruchsspuren|einbruchsspuren)\b", normalized_body)
            and OPERATION_LOCATION_ONLY.search(normalized_title)
        ):
            # An arrest heading can disagree with the independently described
            # break-in scene. Keep both names for review, without a point.
            result["geocode_candidates"] = sorted({
                *result["geocode_candidates"],
                *(row["name"] for row in result["other_scene_candidates"]),
            })
            result["location_label"] = " / ".join(result["geocode_candidates"])
            result["geocode_method"] = "conflicting_explicit_scenes"
            return result
        selected_keys = {(m["kind"], m["key"]) for m in selected}
        selected_geometry = unary_union([
            self._road(m["key"], scope)
            if m["kind"] == "street"
            else transform(
                self.to_metric,
                shape(self.places[m["key"]].get(
                    "location_geometry", self.places[m["key"]]["geometry"]
                )),
            )
            for m in selected
        ])
        conflicting = []
        for index, matches in scene_options if result["location_selection"] == "official_tatort_heading" else []:
            if index == selected_index or selected_keys.intersection(
                {(m["kind"], m["key"]) for m in matches}
            ):
                continue
            alternate_scope = self._scene_scope(district, sentences, index, matches)
            alternate_geometry = unary_union([
                self._road(m["key"], alternate_scope)
                if m["kind"] == "street"
                else transform(
                    self.to_metric,
                    shape(self.places[m["key"]].get(
                        "location_geometry", self.places[m["key"]]["geometry"]
                    )),
                )
                for m in matches
            ])
            if not alternate_geometry.is_empty and selected_geometry.distance(alternate_geometry) > 250:
                conflicting.extend(matches)
        if conflicting:
            result["geocode_candidates"] = sorted(
                {m["alias"] for m in [*selected, *conflicting]}
            )
            result["location_label"] = " / ".join(result["geocode_candidates"])
            result["geocode_method"] = "conflicting_explicit_scenes"
            return result
        place_ids = sorted({m["key"] for m in selected if m["kind"] == "place"})
        road_names = sorted({m["key"] for m in selected if m["kind"] == "street"})
        if place_ids and STATION_VICINITY.search(normalized_body) and any(
            self.places[ident]["properties"]["kind"] == "station" for ident in place_ids
        ):
            result["geocode_method"] = "named_place_area_review"
            return result
        park_vicinity = NAMED_PARK_VICINITY.search(normalized_body)
        if road_names and park_vicinity and not any(
            self.places[ident]["properties"]["kind"] == "park" for ident in place_ids
        ):
            result["location_label"] = park_vicinity[1]
            result["geocode_method"] = "named_area_geometry_review"
            return result
        if OFF_ROAD_SCENE.search(normalized_body) and not place_ids:
            result["geocode_method"] = "unnamed_area_review"
            for pattern, label in (
                (r"\bseeschiff\b", "Seeschiff"),
                (r"\bnahegelegenen feldweg\b", "Feldweg nahe den genannten Straßen"),
                (r"\buniversitätsgelände\b", "Universitätsgelände"),
                (r"\bskateparks?\b", "Unbenannter Skatepark"),
                (r"\bzentralen omnibusbahnhof\w*\b", "Zentraler Omnibusbahnhof (ZOB)"),
            ):
                if re.search(pattern, normalized_body):
                    result["location_label"] = label
                    break
            if (
                result["location_label"] == "Unbenannter Skatepark"
                and re.search(
                    r"\b(?:aus|vom) (?:dem )?(?:skate)?park\b.{0,100}\bin richtung\b",
                    normalized_body,
                )
            ):
                skatepark_index = next(
                    i for i, value in enumerate(sentences)
                    if re.search(r"\bim bereich des skateparks\b", value)
                )
                result.update(
                    geocode_candidates=[],
                    geocode_evidence=[dict(
                        name="Unbenannter Skatepark", kind="source_unnamed_area",
                        role="primary", sentence_index=skatepark_index,
                    )],
                    location_selection="first_explicit_incident_scene",
                )
                return result
            return self._candidate_road(result, self._road(road_names[0], scope)) if len(road_names) == 1 else result
        if UNCERTAIN_RAIL_UNDERPASS.search(normalized_body) and len(road_names) == 1:
            result["geocode_method"] = "rail_underpass_approach_review"
            return self._candidate_road(result, self._road(road_names[0], scope))
        if (
            len(road_names) == 1
            and result.get("location_selection") == "official_tatort_heading"
        ):
            for section_index in range(selected_index + 1, min(selected_index + 8, len(sentences))):
                section_sentence = sentences[section_index]
                between = re.search(r"\bim bereich zwischen\b", section_sentence)
                if not between or not INCIDENT_ACTIONS.search(section_sentence):
                    continue
                source_boundaries = source_section_boundaries(section_sentence)
                boundaries = sorted(
                    (
                        match
                        for match in self._matches(section_sentence)
                        if match["kind"] == "street" and match["start"] >= between.end()
                    ),
                    key=lambda match: match["start"],
                )
                if source_boundaries:
                    exact_keys = []
                    for source_boundary in source_boundaries:
                        exact = next(
                            (
                                match for match in boundaries
                                if match["start"] == source_boundary["start"]
                                and match["end"] == source_boundary["end"]
                            ),
                            None,
                        )
                        result["geocode_evidence"].append(dict(
                            name=source_boundary["name"],
                            kind="street" if exact else "source_named_street",
                            role="section_boundary",
                            sentence_index=section_index,
                        ))
                        if exact:
                            exact_keys.append(exact["key"])
                    source_names = [row["name"] for row in source_boundaries]
                    result["geocode_candidates"] = sorted(
                        set(result["geocode_candidates"]) | set(source_names)
                    )
                    if len(exact_keys) == 2 and len(set(exact_keys)) == 2:
                        return self._street_section_names(
                            road_names[0], exact_keys, scope, result
                        )
                    result["location_label"] = (
                        f"{road_names[0]} (zwischen {' / '.join(source_names)})"
                    )
                    result["geocode_method"] = "street_section_review"
                    return result
                unique_boundaries = list(dict.fromkeys(match["key"] for match in boundaries))
                if boundaries:
                    result["geocode_candidates"] = sorted(
                        set(result["geocode_candidates"]) | {match["alias"] for match in boundaries}
                    )
                    result["geocode_evidence"].extend(
                        dict(
                            name=match["alias"], kind="street", role="section_boundary",
                            sentence_index=section_index,
                        )
                        for match in boundaries
                    )
                if len(unique_boundaries) >= 2 and re.fullmatch(
                    r"\s+(?:und|bis)\s+(?:(?:der|dem|den|zur|zum)\s+)?",
                    section_sentence[boundaries[0]["end"] : boundaries[1]["start"]],
                ):
                    return self._street_section_names(
                        road_names[0], unique_boundaries[:2], scope, result
                    )
                result["location_label"] = " / ".join(result["geocode_candidates"])
                result["geocode_method"] = "street_section_review"
                return result
        if place_ids:
            return self._locate_place(place_ids, road_names, scope, result)
        roads = [self._road(name, scope) for name in road_names]
        if len(roads) == 1 and re.search(
            r"[\w-]+(?:strasse|allee|alle|damm|ring|platz|weg)\s*/\s*[\w-]+", sentence
        ):
            result["geocode_method"] = "incomplete_junction_review"
            return result
        if self._section_reference(sentence, selected):
            return self._street_section(selected, sentence, scope, result)
        if any(road.is_empty for road in roads):
            result["geocode_method"] = "locality_conflict_review"
            return result
        if len(road_names) == 1:
            refined = self._qualified_height_junction(
                road_names[0], sentences, selected_index, scope, result
            )
            if refined is not None:
                return refined
            refined = self._narrative_junction(
                road_names[0], sentences, selected_index, scope, result
            )
            if refined is not None:
                return refined
            match = next(m for m in selected if m["kind"] == "street")
            number = re.match(r"\s+(?:hausnummer\s+|nr\.?\s+)?(\d+[a-z]?)\b", sentence[match["end"] :])
            if number:
                addresses = self.addresses.get((road_names[0], number[1]), [])
                points = [transform(self.to_metric, Point(a["coordinates"])) for a in addresses]
                points = [p for p in points if not scope or scope["metric"].covers(p)]
                if points and self._span(unary_union(points)) <= 50:
                    point = min(points, key=lambda p: (p.x, p.y))
                    return self._located(
                        result, point, "osm_address", "address", self._span(unary_union(points))
                    )
        if 2 <= len(roads) <= 4 and (
            any(m["role"] == "junction_anchor" for m in selected)
            or re.search(
                r"kreuzung|kreuzungsbereich|einmündung|ecke|höhe|/|\bbog\b|\beinbog\b|abbiegen|überquer|"
                r"\b(?:fuhr|fuhren)\b.*?\bin\b.*?\bein\b|"
                r"\bbefuhr\b.{0,160}\bund wollte (?:weiter )?(?:auf|in)\b",
                sentence,
            )
        ):
            junction = self._junction(roads)
            if junction is not None:
                point, extent = junction
                if re.search(
                    r"\b(?:kurz|unmittelbar) hinter der (?:kreuzung|einmündung)\b",
                    sentence,
                ):
                    extent = max(extent, 75)
                return self._located(result, point, "named_street_intersection", "street", extent)
            result["geocode_method"] = "junction_geometry_review"
            return result
        if len(roads) != 1:
            result["geocode_method"] = "multiple_locations_review"
            return result
        road = roads[0]
        # Measure geographic extent, not the summed lengths of parallel OSM fragments.
        if self._span(road) > MAX_STREET_POINT_SPAN_M and (
            UNNAMED_VENUE.search(normalized_body)
            or UNNAMED_RESIDENTIAL_SCENE.search(normalized_body)
            or re.search(r"\b\w*(?:unfall|unfäll)\w*\b|\bkollid\w*", normalized_body)
        ):
            result["geocode_method"] = "long_or_ambiguous_street_review"
            return self._candidate_road(result, road)
        if self._span(road) > 3000:
            result["geocode_method"] = "long_or_ambiguous_street_review"
            return self._candidate_road(result, road)
        connected = road.buffer(15)
        if connected.geom_type != "Polygon":
            result["geocode_method"] = "disconnected_street_review"
            return self._candidate_road(result, road)
        point = nearest_points(connected.representative_point(), road)[1]
        return self._located(result, point, "street_representative", "street", self._span(road))

    def _candidate_road(self, result, road):
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
            result["candidate_road_geometry"] = mapping(transform(self.to_wgs, geometry))
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

    def _qualified_height_junction(self, main_road, sentences, selected_index, scope, result):
        """Use an explicitly northern/southern crossing for a fixed impact scene."""
        if result.get("location_selection") != "official_tatort_heading":
            return None
        main = self._road(main_road, scope)
        for index in range(selected_index + 1, min(selected_index + 8, len(sentences))):
            sentence = sentences[index]
            if not QUALIFIED_HEIGHT_IMPACT.search(sentence):
                continue
            for match in self._matches(sentence):
                if match["kind"] != "street" or match["key"] == main_road:
                    continue
                prefix = sentence[max(0, match["start"] - 60):match["start"]]
                qualifier = re.search(r"\bin höhe des (nördlichen|südlichen)\s+$", prefix)
                if not qualifier:
                    continue
                other = self._road(match["key"], scope)
                if main.is_empty or other.is_empty:
                    continue
                intersections = main.intersection(other)
                if intersections.geom_type == "Point":
                    points = [intersections]
                elif intersections.geom_type == "MultiPoint":
                    points = list(intersections.geoms)
                else:
                    points = []
                if len(points) != 2 or points[0].distance(points[1]) < 50:
                    result["geocode_method"] = "junction_geometry_review"
                    return result
                northern = qualifier[1] == "nördlichen"
                point = max(points, key=lambda part: part.y) if northern else min(
                    points, key=lambda part: part.y
                )
                result["geocode_candidates"] = sorted({main_road, match["alias"]})
                result["location_label"] = (
                    f"{main_road} / {match['key']} "
                    f"({'nördlicher' if northern else 'südlicher'} Anschluss)"
                )
                result["geocode_evidence"].append({
                    "name": match["alias"], "kind": "street", "role": "junction_anchor",
                    "sentence_index": index,
                })
                result["excluded_location_context"] = [
                    row for row in result["excluded_location_context"]
                    if not (row["name"] == match["alias"] and row["sentence_index"] == index)
                ]
                return self._located(result, point, "named_street_intersection", "street", 100)
        return None

    def _narrative_junction(self, main_road, sentences, selected_index, scope, result):
        """Refine an official road only when the narrative ties an impact to a named crossing."""
        if result.get("location_selection") != "official_tatort_heading":
            return None
        for index in range(selected_index + 1, min(selected_index + 8, len(sentences))):
            sentence = sentences[index]
            streets = [
                match for match in self._matches(sentence)
                if match["kind"] == "street" and match["role"] == "primary"
            ]
            anchors = [m for m in streets if m["key"] != main_road]
            if not anchors:
                continue
            near_roundabout = bool(re.search(r"\bin der nähe des kreisels\b", sentence))
            height_impact = bool(re.search(r"\b(?:auf höhe der|in höhe der einmündung)\b", sentence)
                                 and re.search(r"\b(?:kollid\w*|auffuhr|prall\w*|fuhr\b.{0,70}\bauf)\b", sentence))
            before_impact = bool(re.search(r"\bvor der\s+" + re.escape(anchors[0]["alias"]), sentence)
                                 and re.search(r"\b(?:kollid\w*|prall\w*)\b", sentence))
            stop_impact = bool(re.search(r"\bbushaltestelle\b.{0,90}/", sentence)
                               and main_road in {m["key"] for m in streets}
                               and re.search(r"\b(?:verliess|stieg aus|entriss)\b", sentence))
            turn_impact = bool(main_road in {m["key"] for m in streets}
                               and re.search(r"\bbog\b.{0,100}\bkollid\w*\b", sentence))
            street_corner = bool(
                main_road in {m["key"] for m in streets}
                and re.search(r"\bstrassenecke\b.{0,100}/", sentence)
                and (
                    INCIDENT_ACTIONS.search(sentence)
                    or re.search(r"\b(?:kette|schmuck)\b.{0,90}\b(?:riss|entriss)\b", sentence)
                )
            )
            if not any((near_roundabout, height_impact, before_impact, stop_impact,
                        turn_impact, street_corner)):
                continue
            names = list(dict.fromkeys([main_road, *(m["key"] for m in anchors)]))
            if len(names) > 4:
                continue
            roads = [self._road(name, scope) for name in names]
            if any(road.is_empty for road in roads):
                continue
            junction = self._junction(roads)
            if junction is None:
                if street_corner:
                    result["geocode_candidates"] = sorted(
                        set(result["geocode_candidates"]) | set(names)
                    )
                    result["location_label"] = " / ".join(names)
                    result["geocode_method"] = "junction_geometry_review"
                    return result
                continue
            point, extent = junction
            result["geocode_candidates"] = sorted(set(result["geocode_candidates"]) | set(names))
            result["location_label"] = " / ".join(names) + " (näherer Kreuzungsbereich)"
            result["geocode_evidence"].extend(
                dict(name=m["alias"], kind="street", role="junction_anchor", sentence_index=index)
                for m in anchors
            )
            result["excluded_location_context"] = [
                row for row in result["excluded_location_context"]
                if not (row["sentence_index"] == index and row["name"] in {m["alias"] for m in anchors})
            ]
            return self._located(result, point, "named_street_intersection", "street", max(extent, 100))
        return None

    @staticmethod
    def _official_junction_matches(sentence, matches):
        streets = sorted(
            (m for m in matches if m["kind"] == "street"),
            key=lambda m: m["start"],
        )
        for first, second in zip(streets, streets[1:]):
            if official_scene_heading(sentence, first["start"]) and re.fullmatch(
                r"\s*(?:/|\(\s*höhe\s+)\s*",
                sentence[first["end"] : second["start"]],
            ):
                return [first, second]
        return []

    @staticmethod
    def _official_section_matches(sentence, matches):
        streets = sorted(
            (m for m in matches if m["kind"] == "street"),
            key=lambda m: m["start"],
        )
        for between in re.finditer(r"\bzwischen\b", sentence):
            anchors = [
                m for m in streets
                if m["end"] <= between.start() and official_scene_heading(sentence, m["start"])
            ]
            boundaries = [m for m in streets if m["start"] >= between.end()]
            if (
                anchors
                and len(boundaries) >= 2
                and re.fullmatch(
                    r"\s*(?:(?:der|dem|den)\s+)?",
                    sentence[between.end() : boundaries[0]["start"]],
                )
                and re.fullmatch(
                    r"\s+(?:und|bis)\s+(?:(?:der|dem|den|zur|zum)\s+)?",
                    sentence[boundaries[0]["end"] : boundaries[1]["start"]],
                )
            ):
                return [anchors[-1], boundaries[0], boundaries[1]]
        return []

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
        return self._street_section_names(anchors[-1]["key"], boundaries, scope, result)

    def _street_section_names(self, main, boundaries, scope, result):
        """Resolve a named main-road section whose boundaries may be in a later sentence."""
        sections = []
        used_scope = scope
        for candidate_scope in ([scope, None] if scope else [None]):
            road = self._road(main, candidate_scope)
            ends = [
                self._junction([road, self._road(name, candidate_scope)])
                for name in boundaries
            ]
            if road.is_empty or any(end is None for end in ends):
                continue
            merged = line_merge(road)
            lines = list(merged.geoms) if merged.geom_type == "MultiLineString" else [merged]
            for line in lines:
                if line.geom_type != "LineString" or any(line.distance(end[0]) > 20 for end in ends):
                    continue
                segment = substring(line, line.project(ends[0][0]), line.project(ends[1][0]))
                if segment.geom_type == "LineString" and segment.length > 1:
                    sections.append(segment)
            if sections:
                used_scope = candidate_scope
                break
        if not sections:
            result["geocode_method"] = "street_section_review"
            return result
        geometry = unary_union(sections)
        if self._span(geometry) > 3000 or geometry.buffer(15).geom_type != "Polygon":
            result["geocode_method"] = "street_section_review"
            return result
        point = max(sections, key=lambda line: line.length).interpolate(0.5, normalized=True)
        if scope and used_scope is None:
            result.pop("location_scope", None)
        if used_scope is None:
            containing = [
                row for row in self.localities.values()
                if row.get("admin_level") == "10" and row["metric"].covers(geometry)
            ]
            if len(containing) == 1:
                result["district"] = containing[0]["name"]
                result["location_scope"] = containing[0]["name"]
        result["reported_location_geometry"] = mapping(transform(self.to_wgs, geometry))
        result["location_label"] = f"{main} (zwischen {' / '.join(boundaries)})"
        return self._located(result, point, "reported_street_section", "street", self._span(geometry))

    def _located(self, result, point, method, precision, extent):
        point = transform(self.to_wgs, point)
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
            metric = transform(self.to_metric, geometry)
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
    ("Raub", r"(?<!freiheitsbe)raub|ausgeraub|überf(?:all|äll)"),
    ("Diebstahl", r"diebstahl|diebe|trickdieb\w*|gestohlen|einbr(?:uch|üch)|einbrecher|aufbrecher"),
    (
        "Gewalt",
        r"angriff|angegriffen|angreif|greift|verletz|attack|messer|schuss|schüsse|körperverletz|getötet|tötungs|mord|geschlagen|polizist.*mitgeschleift",
    ),
    ("Sachbeschädigung", r"sachbeschädig|beschädigt|vandal|brandstift|in brand gesetzt"),
    ("Bedrohung", r"bedroht|bedrohung|erpress"),
    ("Sexualdelikt", r"sexual|sexuell|vergewaltig"),
    ("Betäubungsmittel", r"drogen|betäubungsmittel|dealer|rauschmittel|heroin|kokain"),
    ("Betrug", r"betrug|betrüger"),
    ("Waffendelikt", r"waffenhandel|waffendelikt|waffengesetz"),
    ("Eigentumsdelikt", r"geldausgabeautomat|geldautomat"),
]

TRAFFIC_TOPIC = re.compile(
    r"\b\w*(?:unfall|unfäll)\w*\b|angefahren|fährt[^.]{0,80}\ban\b|"
    r"zusammenstoß|tretroller|kollision|\bkollid\w*|fahrerflucht|"
    r"(?:auto|straßen|strassen|kraftfahrzeug|kfz)[- ]?rennen"
)
ACCIDENT_FLIGHT_TITLE = re.compile(
    r"(?:unfall|unfäll)\w*flucht|(?:unfall|unfäll)\w*.{0,50}\bflucht\b|fahrerflucht|"
    r"\bfährt\b[^.]{0,100}\ban\b[^.]{0,40}\b(?:flüchtet|flieht|floh)\b"
)
ACCIDENT_FLIGHT_BODY = re.compile(
    r"\bunerlaubt\b.{0,100}\bvom unfallort\b|"
    r"\bvom unfallort\b.{0,120}\b(?:unerlaubt|ohne\b.{0,80}\b(?:pflicht\w*|feststellung\w*))"
)
OTHER_TRAFFIC_OFFENCE = re.compile(
    r"\b(?:illegale[rsnm]?|verbotene[rsnm]?)\b.{0,30}"
    r"\b(?:auto|straßen|strassen|kraftfahrzeug|kfz)[- ]?rennen\b|"
    r"\b(?:straßen|strassen|kraftfahrzeug)[- ]?rennen\b|"
    r"\b(?:ohne|kein\w*|fehlend\w*)\b.{0,40}"
    r"\b(?:versicherungsschutz|pflichtversicherung|fahrerlaubnis)\b|"
    r"\bnicht\s+im\s+besitz\s+(?:(?:einer|der)\s+)?"
    r"(?:gültigen\s+|erforderlichen\s+)?fahrerlaubnis\b|"
    r"\bpflichtversicherungsgesetz\b"
)


def category(title, body=""):
    low = title.casefold()
    narrative = body.casefold()
    normalized_title = normalize(title)
    normalized_narrative = normalize(body)
    if re.search(r"\bverkehrssicherheitsbilanz\s+\d{4}\b", low):
        return "Unklassifiziert", False
    aggregate_report = aggregate_control_report(normalized_title, normalized_narrative)
    if aggregate_report:
        traffic_crime_total = bool(
            re.search(r"\bverkehr\w*\b", normalized_title)
            and re.search(r"\b\d[\d.]*\s+strafverfahren\b", normalized_narrative)
            and (
                OTHER_TRAFFIC_OFFENCE.search(normalized_narrative)
                or re.search(r"\btrunkenheit im strassenverkehr\b", normalized_narrative)
            )
        )
        return (
            ("Verkehr / sonstige Meldung", True)
            if traffic_crime_total else ("Unklassifiziert", False)
        )
    if re.search(
        r"\bfrühjahrstagung der arbeitsgemeinschaft der polizeipräsident|"
        r"\bsicher\.mobil\.leben\b.{0,100}\bergebnisse\b.{0,120}\bverkehrssicherheitsaktion\b",
        normalized_title,
    ):
        return "Unklassifiziert", False
    if MEDICAL_DEATH_INVESTIGATION.search(normalized_title) and re.search(
        r"\btodesermittlungsverfahren\b", normalized_narrative
    ):
        return "Unklassifiziert", False
    if (
        re.search(r"\b(?:wohnungs|gebäude|zimmer|keller)?brand\b", low)
        and re.search(r"\baus (?:bislang|noch) ungeklärter ursache\b", narrative)
        and not re.search(r"brandstift|in brand gesetzt", narrative)
    ):
        return "Unklassifiziert", False
    if re.search(r"\bauffinden eines?\b.{0,50}\bleichnams?\b", low):
        suspicious = bool(re.search(
            r"\b(?:mordkommission|verdacht\w*\b.{0,80}\b(?:gewalteinwirkung|tötung))\b",
            narrative,
        ))
        return "Unklassifiziert", suspicious
    medical_traffic_collision = bool(
        re.search(r"\bim strassenverkehr\b", normalized_title)
        and re.search(r"\b(?:auffahrunfall|verkehrsunfall|kollision|zusammenstoss)\b", normalized_narrative)
    )
    if TRAFFIC_TOPIC.search(low) or OTHER_TRAFFIC_OFFENCE.search(low) or medical_traffic_collision:
        traffic_crime = bool(
            ACCIDENT_FLIGHT_TITLE.search(low)
            or ACCIDENT_FLIGHT_BODY.search(narrative)
            or OTHER_TRAFFIC_OFFENCE.search(low)
            or OTHER_TRAFFIC_OFFENCE.search(narrative)
            or re.search(
                r"\bstrafverfahren\b.{0,100}\bverdacht\w*\b.{0,60}"
                r"\b(?:mehrere\w*\s+)?(?:verkehrs)?delikte\b",
                normalized_narrative,
            )
            or re.search(r"\bverdacht\w*\b.{0,60}\bfahrlässig\w*\s+(?:körperverletzung|tötung)\b", narrative)
            or re.search(
                r"\bverfahren\b.{0,80}\bverdacht\w*\b.{0,80}"
                r"\bgefährlich\w* eingriff\w* in den bahnverkehr\b",
                normalized_narrative,
            )
        )
        return "Verkehr / sonstige Meldung", traffic_crime
    if re.search(r"\bschussabgabe\b.{0,80}\bfenster\b", normalized_title) and re.search(
        r"\bfenster\b.{0,120}\bbeschädigt\b.{0,100}\bniemand verletzt\b",
        normalized_narrative,
    ):
        return "Sachbeschädigung", True
    if re.search(
        r"\bermittlungen\b.{0,80}\b(?:zu|wegen)\b.{0,80}\bsachbeschädigung\b",
        narrative,
    ):
        return "Sachbeschädigung", True
    if re.search(
        r"\b(?:waren|gegenstände)\b.{0,160}\bbetrügerisch (?:erworben|bezahlt)\b|"
        r"\bfachkommissariat für betrugsdelikte\b",
        narrative,
    ):
        return "Betrug", True
    if re.search(
        r"\bteil einer betrügerbande\b.{0,100}\bversucht\b",
        normalized_narrative,
    ):
        return "Betrug", True
    if re.search(
        r"\b(?:im verdacht stehen|stehen im verdacht),? mit betäubungsmitteln gehandelt zu haben\b",
        narrative,
    ):
        return "Betäubungsmittel", True
    combined_narrative = f"{normalized_title} {normalized_narrative}"
    if not re.search(r"\b(?:kriminalstatistik|statistik|bilanz)\b", normalized_title) and (
        re.search(
            r"\b(?:illegal|unerlaubt)\w*\s+handel(?:s)?\s+mit\s+cannabis\b",
            combined_narrative,
        )
        or (
            re.search(r"\b(?:handel|verkauf)\w*.{0,80}\bcannabis\b", combined_narrative)
            and re.search(r"\b(?:konsumcannabisgesetz|kcang)\b", normalized_narrative)
            and re.search(
                r"\b(?:verdacht|illegal|unerlaubt|verstoß|verstoss)\w*\b",
                combined_narrative,
            )
        )
    ):
        return "Betäubungsmittel", True
    if re.search(
        r"\bverdacht\w*\b.{0,40}\bmit waffen gehandelt\b|"
        r"\bwaffen\b.{0,100}\bgewinnbringend veräussern\b",
        normalized_narrative,
    ) and re.search(r"\bwaffengesetz\b|\bwaffen gehandelt\b", normalized_narrative):
        return "Waffendelikt", True
    if re.search(r"\bermittlungen?\b.{0,80}\bwegen des verdachts der hehlerei\b", narrative):
        return "Eigentumsdelikt", True
    if "hasskriminalität" in low and re.search(r"\bkörperverletzung\w*|\bschlugen und traten\b", narrative):
        return "Gewalt", True
    if re.search(r"\bermittlungen zu den einzelnen eingeleiteten ermittlungsverfahren\b", narrative):
        return "Unklassifiziert", True
    for label, pattern in CATEGORY_RULES:
        if re.search(pattern, low):
            return label, True
    if re.search(r"\btatort\s*:", body, re.IGNORECASE) and re.search(
        r"\b(?:beraubt|raubte|raubten)\b",
        body,
        re.IGNORECASE,
    ):
        return "Raub", True
    if re.search(r"\b(?:freiheitsberaubung|tödlich\w*\s+auseinandersetzung)\b", low):
        return "Gewalt", True
    if re.search(r"\b(?:metallspäne|nägel|scherben)\b.{0,160}\bbeschädig", narrative):
        return "Sachbeschädigung", True
    if re.search(
        r"\b(?:geschlagen|schlug|attackier\w*|angegriff\w*|stichverletz\w*|"
        r"tödlich\w*\s+verletz\w*|gefährlich\w*\s+körperverletzung)\b",
        narrative,
    ):
        return "Gewalt", True
    if re.search(r"\b(?:rassistisch|antisemitisch|homophob|transfeindlich)\w*\s+beleidig", low):
        return "Unklassifiziert", True
    if "hasskriminalität" in low and re.search(r"\b(?:beleidig|bedroh)\w*\b", narrative):
        return "Unklassifiziert", True
    if "hasskriminalität im internet" in low and re.search(
        r"\bermittlungsverfahren wegen des verdachts der volksverhetzung\b", narrative
    ):
        return "Unklassifiziert", True
    if re.search(r"\b(?:verdacht\w*\s+(?:des\s+)?|wegen\s+(?:des\s+)?)betrug(?:s|es)?\b", narrative):
        return "Betrug", True
    if re.search(
        r"\bmittels\s+gefälscht\w*\b.{0,120}\b(?:kredit|darlehen)\b.{0,160}"
        r"\brechtswidrig\w*\s+verschafft\b",
        narrative,
    ):
        return "Betrug", True
    if re.search(
        r"\b(?:verdacht\w*|verstoß\w*|ermittlung\w*|strafbar\w*)\b.{0,100}"
        r"\bmarkengesetz\b|strafbare kennzeichenverletzung|produktpiraterie",
        low,
    ):
        return "Unklassifiziert", True
    if re.search(
        r"\b(?:verdacht\w*|ermittlung\w*|strafverfahren)\b.{0,120}"
        r"\b(?:verstoß\w*\s+gegen\s+das\s+)?markengesetz\b",
        narrative,
    ):
        return "Unklassifiziert", True
    if (
        OTHER_TRAFFIC_OFFENCE.search(narrative)
        and re.search(
            r"\b(?:pkw|auto|fahrzeug\w*|fahrer\w*|verkehr\w*|raser|kontroll\w*|führerschein)\b",
            low,
        )
        and not re.search(r"\bbilanz\b|\bkontrolltage\b", low)
    ):
        return "Verkehr / sonstige Meldung", True
    if (
        re.search(r"\bnicht im besitz einer sprengstoffrechtlichen erlaubnis\b", narrative)
        and re.search(r"\bselbstgefertigte pyrotechnische\b", narrative)
    ):
        return "Unklassifiziert", True
    if re.search(r"\bgewalt- und eigentumsdelikt", low) or re.search(
        r"\bermittlungsverfahren eingeleitet\b.{0,220}\bwegen des verdachts\b",
        narrative,
    ):
        return "Unklassifiziert", True
    return "Unklassifiziert", False


SOURCE_REPORT_LINK = re.compile(
    r"https?://(?:www\.)?presseportal\.de/blaulicht/pm/\d+/(\d+)"
)
CASE_UPDATE_TITLE = re.compile(
    r"\b(?:tataufklärung|festnahm\w*|verhaft\w*|zuführung\w*|haftbefehl\w*|"
    r"öffentlichkeitsfahndung|ermittelt\w*\s+tatverdächtig\w*|"
    r"tatverdächtig\w*\s+stellt\s+sich|veröffentlicht\s+foto)\b|"
    r"\bnimmt\b.{0,80}\bfest\b"
)
INDEPENDENT_FOLLOWUP_OFFENCE = re.compile(
    r"\bverstoss(?:es)? gegen das waffengesetz\b|"
    r"\bverdacht\w*\b.{0,80}\billegal\w*\s+aufenthalt\w*\b"
)
CASE_SIGNATURES = (
    ("homicide", re.compile(r"\b(?:versucht\w*\s+)?tötungsdelikt\b|\bmord\b")),
    ("sexual", re.compile(r"\bsexualdelikt\b|\bsexuell\w*\s+(?:übergriff|belästigung)\w*\b")),
    ("shooting", re.compile(r"\bschussabgab\w*\b|\bschusswaffe\b")),
    ("fatal_assault", re.compile(r"\bkörperverletzung\b.{0,40}\btodesfolge\b")),
    ("bias_assault", re.compile(r"\bkörperverletzung\b.{0,100}\brassistisch\w*\b")),
    ("senior_robbery", re.compile(r"\büberfall\w*\b.{0,80}\bsenior\w*\b")),
    ("body_found", re.compile(r"\bauffinden\b.{0,80}\bleichnam\w*\b")),
)


def case_signatures(title):
    return {name for name, pattern in CASE_SIGNATURES if pattern.search(title)}


def incident_header_times(body):
    """Extract incident times from the source header, excluding later operational times."""
    header = normalize(body)[:500]
    return set(re.findall(r"\b\d{2}\.\d{2}\.\d{4},?\s*\d{1,2}:\d{2}\b", header))


def pure_source_followup(row, previous, time_key):
    """Require source-backed same-case evidence beyond the mere presence of a link."""
    title = normalize(row["title"])
    body = normalize(row["body"])
    previous_title = previous["title"]
    missing_search = bool(
        re.search(r"\berledigung der vermisstenfahndung\b", title)
        and re.search(r"\bvermisstenfahndung\b", previous_title)
        and re.search(r"\bhinweise auf straftaten liegen nicht vor\b", body)
    )
    if missing_search:
        return "missing_search"
    traffic_death = bool(
        re.search(r"\bverstirbt nach (?:verkehrs)?unfall\b", title)
        and re.search(r"\b(?:verkehrs)?unf(?:all|äll)\w*\b", previous_title)
        and re.search(r"\b(?:verstarb|starb|erlag)\b", body)
    )
    if traffic_death:
        return "traffic_death"
    signatures = case_signatures(title) & previous["case_signatures"]
    if not signatures or not CASE_UPDATE_TITLE.search(title):
        return None
    if INDEPENDENT_FOLLOWUP_OFFENCE.search(body):
        return None
    current_header_times = incident_header_times(row["body"])
    previous_header_times = previous["header_times"]
    if (
        previous_header_times
        and len(current_header_times) > len(previous_header_times)
        and not current_header_times.issubset(previous_header_times)
    ):
        return None
    same_time = bool(
        time_key and (
            time_key in previous["reported_times"]
            or time_key in previous_header_times
        )
    )
    district = normalize(row["district"])
    same_district = bool(
        district and (
            district == normalize(previous["district"])
            or district in previous["reported_districts"]
        )
    )
    return "case_update" if same_time or same_district else None


def attach_scene_locations(row, location, reviewed_decision=None, source_hashes=None):
    """Preserve every sourced scene while projecting at most one count point."""
    if reviewed_decision is None:
        # A rule may flag an article for review, but it must not invent the
        # semantic inventory that the source-first LLM is meant to produce.
        if location.get("geocode_method") == "multiple_official_scenes":
            location["scene_review_required"] = True
        return
    scenes = validated_scene_decision(row, reviewed_decision, source_hashes)
    # A source-first LLM review may find scenes that the rule candidate missed.
    # The reviewed inventory overrides that initial classification.
    if reviewed_decision is not None:
        location["geocode_method"] = "multiple_official_scenes"
        location.pop("scene_review_required", None)
    location["scene_locations"] = scenes
    location.pop("candidate_road_geometry", None)
    location.pop("reported_location_geometry", None)
    location.pop("location_extent_m", None)
    location.pop("other_scene_candidates", None)
    primaries = [scene for scene in scenes if scene["primary_for_count"]]
    if len(primaries) > 1:
        raise ValueError(f"Multiple scene count points for {row['id']}")
    if not primaries:
        location.update(
            coordinates=None,
            location_precision="unknown",
            location_label="",
            district="",
            geocode_candidates=[],
            geocode_evidence=[],
            location_object_ids=[],
        )
        return
    primary = primaries[0]
    location.update(
        coordinates=primary["coordinates"],
        location_precision=primary["location_precision"],
        location_label=primary["label"],
        location_object_ids=primary.get("location_object_ids", []),
        location_selection="first_explicit_incident_scene",
        geocode_candidates=[primary["label"]],
        geocode_evidence=[primary["evidence_quote"]],
    )


def events_from_db(db, gazetteer, scene_decisions=None):
    rows = []
    earlier = {}
    scene_decisions = scene_decisions or {}
    used_scene_decisions = set()
    source_hashes = {
        str(row["id"]): row["sha256"]
        for row in db.execute("SELECT id,sha256 FROM reports WHERE body IS NOT NULL")
    }
    for r in db.execute("SELECT * FROM reports WHERE body IS NOT NULL ORDER BY published,id"):
        label, crime = category(r["title"], r["body"])
        location = gazetteer.locate(r["body"], title=r["title"], district=r["district"])
        time_key = re.search(
            r"\b(?:unfallzeit|tatzeit)\s*:\s*(\d{2}\.\d{2}\.\d{4},?\s*\d{1,2}:\d{2})",
            normalize(r["body"]),
        )
        references = list(dict.fromkeys(
            reference
            for reference in SOURCE_REPORT_LINK.findall(r["body"])
            if reference in earlier
        ))
        followup_kind = None
        previous = None
        if len(references) == 1:
            previous = earlier[references[0]]
            followup_kind = pure_source_followup(
                r, previous, time_key[1] if time_key else None
            )
        if followup_kind:
            location["followup_of_source_id"] = references[0]
            location.update(
                coordinates=None,
                location_precision="unknown",
                location_object_ids=[],
            )
            location.pop("location_extent_m", None)
            if followup_kind == "missing_search":
                # This closes a non-crime search; keep that publication status.
                location["geocode_method"] = "non_incident_report"
            elif previous["location"].get("geocode_method") == "rail_underpass_approach_review":
                # Preserve the earlier bounded road range, without creating a second point.
                location.update(
                    geocode_method="rail_underpass_approach_review",
                    candidate_road_geometry=previous["location"].get("candidate_road_geometry"),
                )
                location.pop("reported_location_geometry", None)
            else:
                location["geocode_method"] = "followup_report"
                location.pop("candidate_road_geometry", None)
                location.pop("reported_location_geometry", None)
        elif references:
            location["source_reference_ids"] = references
        reviewed_scene = scene_decisions.get(str(r["id"]))
        reviewed_semantics = (
            validated_article_semantics(r, reviewed_scene, source_hashes)
            if reviewed_scene is not None else {}
        )
        if "category" in reviewed_semantics:
            label = reviewed_semantics["category"]
            crime = reviewed_semantics["is_crime_report"]
        attach_scene_locations(
            r, location, reviewed_scene, source_hashes,
        )
        if reviewed_scene is not None:
            used_scene_decisions.add(str(r["id"]))
        reviewed_followup = reviewed_semantics.get("followup_of_source_id")
        if reviewed_followup:
            existing_followup = location.get("followup_of_source_id")
            if existing_followup and existing_followup != reviewed_followup:
                raise ValueError(f"Conflicting reviewed followup for {r['id']}")
            location["followup_of_source_id"] = reviewed_followup
        poi_kinds = mentions(r["body"])
        if location["location_precision"] == "place":
            poi_kinds = sorted(
                set(poi_kinds)
                | {gazetteer.places[i]["properties"]["kind"] for i in location["location_object_ids"]}
            )
        corrected_district = location.pop("district", None)
        reported_district = r["district"]
        # A source heading can describe a corridor (for example, neighbourhood A
        # to neighbourhood B).  Keep that wording as a label, not as one district.
        if re.search(r"\bbis\b", normalize(reported_district)):
            reported_district = ""
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
                district="" if location["geocode_method"] in {
                    "operation_locations_only", "reported_site_not_scene"
                } else corrected_district if corrected_district is not None else reported_district,
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
        earlier[r["id"]] = dict(
            time_key=time_key[1] if time_key else None,
            header_times=incident_header_times(r["body"]),
            reported_times=set(re.findall(
                r"\b\d{2}\.\d{2}\.\d{4},?\s*\d{1,2}:\d{2}",
                normalize(r["body"]),
            )),
            reported_districts=set(re.findall(
                r"\bhamburg-([a-zäöüß-]+)\b", normalize(r["body"]),
            )),
            district=r["district"], title=normalize(r["title"]),
            case_signatures=case_signatures(normalize(r["title"])), location=location,
        )
    unused = set(scene_decisions) - used_scene_decisions
    if unused:
        raise ValueError("Scene decisions do not match current reports: " + ", ".join(sorted(unused)))
    return rows
