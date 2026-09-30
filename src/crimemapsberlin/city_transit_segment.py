"""Cut selected subway or tram tracks at two original OSM stop nodes."""

from shapely.geometry import LineString, shape
from shapely.ops import linemerge, substring, unary_union


def source_track_segment(track_rows: list[dict], stop_rows: list[dict],
                         *, line: str, mode: str):
    """Require one connected path and stop coordinates present in source ways.

    The caller chooses the ways, line, mode and stop nodes. No announcement,
    nearest station or timetable is interpreted here.
    """
    if mode not in {"subway", "tram"}:
        raise ValueError("source track segments support subway or tram only")
    if not track_rows or len(stop_rows) != 2:
        raise ValueError("transit segment needs track ways and two stop nodes")
    tracks = []
    vertices = set()
    for row in track_rows:
        tags = row.get("tags", {})
        geometry = shape(row["geometry"])
        if (not row["id"].startswith("osm/way/")
                or line not in row.get("names", [])
                or geometry.geom_type != "LineString"
                or tags.get("railway") not in {mode, "light_rail"}
                or any(tags.get(key) not in {None, "", "no", "false", "0"}
                       for key in ("construction:railway", "proposed:railway",
                                   "disused:railway", "abandoned:railway"))):
            raise ValueError("segment track must be an operational source way of the selected line")
        tracks.append(geometry)
        vertices.update(geometry.coords)
    stops = []
    for row in stop_rows:
        tags = row.get("tags", {})
        point = shape(row["geometry"])
        if (not row["id"].startswith("osm/node/")
                or point.geom_type != "Point"
                or tags.get("public_transport") != "stop_position"
                or tags.get(mode) != "yes"
                or tuple(point.coords[0]) not in vertices):
            raise ValueError("segment endpoint must be an original mode stop node on a selected source way")
        stops.append(point)
    merged = unary_union(tracks)
    if merged.geom_type != "LineString":
        merged = linemerge(merged)
    if merged.geom_type != "LineString" or not merged.is_simple:
        raise ValueError("segment ways must form one unbranched connected path")
    start, end = (merged.project(point) for point in stops)
    if start == end:
        raise ValueError("segment stop nodes must be distinct")
    segment = substring(merged, start, end)
    coordinates = list(segment.coords)
    # Preserve the exact original stop coordinates after linear referencing.
    coordinates[0], coordinates[-1] = stops[0].coords[0], stops[1].coords[0]
    return LineString(coordinates)
