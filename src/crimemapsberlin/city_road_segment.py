"""Retain an explicitly reviewed road range between native OSM junctions.

The reviewer selects every path and its two endpoint-road groups, and checks
shared source nodes and grade separation in the PBF. This calculation neither
searches a road network nor invents endpoints at projected line crossings.
"""

from shapely.geometry import LineString, shape
from shapely.ops import linemerge, unary_union


def _roads(rows: list[dict]) -> list[LineString]:
    if not rows:
        raise ValueError("road segment needs nonempty road groups")
    lines = []
    for row in rows:
        geometry = shape(row["geometry"])
        if (
            "road" not in row.get("roles", [])
            or geometry.geom_type not in {"LineString", "MultiLineString"}
            or row.get("tags", {}).get("highway") in {
                "construction", "proposed", "platform", "bus_stop"
            }
        ):
            raise ValueError("road segment groups must contain operational checked roads")
        lines.extend(geometry.geoms if geometry.geom_type == "MultiLineString" else [geometry])
    return lines


def _endpoint(rows: list[dict]):
    """Only native motorway junctions or explicitly source-proved vertices."""
    if len(rows) == 1:
        row = rows[0]
        geometry = shape(row["geometry"])
        proof = row.get("native_road_vertex_source_proof", {})
        source_node = proof.get("source_node", {})
        if (row.get("id") == f"osm/node/{source_node.get('id')}"
                and "road" in row.get("roles", []) and geometry.geom_type == "Point"
                and proof.get("schema_version") == 1 and proof.get("usage") == "native_road_endpoint_only"
                and tuple(source_node.get("coordinates", [])) == tuple(geometry.coords[0])):
            return geometry, {tuple(geometry.coords[0])}
        if (
            row.get("id", "").startswith("osm/node/")
            and "road" in row.get("roles", [])
            and row.get("tags", {}).get("highway") == "motorway_junction"
            and geometry.geom_type == "Point"
        ):
            return geometry, {tuple(geometry.coords[0])}
    lines = _roads(rows)
    return unary_union(lines), {tuple(point) for line in lines for point in line.coords}


def source_linear_segments(groups: list[list[dict]], *, path_lines):
    """Cut explicitly selected native paths at actual endpoint-road vertices.

    Separate carriageways can have separate triples. Each selected path must
    merge to one nonbranching, noncyclic line. Endpoints must be actual vertices
    shared with the selected endpoint roads or selected native motorway-junction
    nodes. Preserve only intervening source vertices, never a midpoint,
    nearest-road snap or interpolated endpoint.
    """
    if not groups or len(groups) % 3:
        raise ValueError("road segment needs path/start/end road-group triples")
    segments = []
    for offset in range(0, len(groups), 3):
        selected_lines = path_lines(groups[offset])
        joined = unary_union(selected_lines)
        path = joined if joined.geom_type == "LineString" else linemerge(joined)
        if path.geom_type != "LineString" or not path.is_simple or path.is_ring:
            raise ValueError("selected road path must be one nonbranching, noncyclic line")
        path_vertices = {tuple(point) for line in selected_lines for point in line.coords}
        coordinates = list(path.coords)
        endpoints = []
        for endpoint_group in groups[offset + 1:offset + 3]:
            endpoint_geometry, endpoint_vertices = _endpoint(endpoint_group)
            crossing = path.intersection(endpoint_geometry)
            if crossing.geom_type != "Point" or crossing.is_empty:
                raise ValueError("each road-segment endpoint needs one unique junction")
            coordinate = tuple(crossing.coords[0])
            if (
                coordinate not in path_vertices
                or coordinate not in endpoint_vertices
                or coordinate not in coordinates
            ):
                raise ValueError("road-segment endpoints must be shared native source vertices")
            endpoints.append(coordinates.index(coordinate))
        start, end = endpoints
        if start == end:
            raise ValueError("road-segment endpoints must be distinct")
        selected = coordinates[min(start, end):max(start, end) + 1]
        segments.append(LineString(selected if start < end else selected[::-1]))
    return unary_union(segments)


def source_road_segments(groups: list[list[dict]]):
    """Each triple is [operational road path, start roads, end roads]."""
    return source_linear_segments(groups, path_lines=_roads)
