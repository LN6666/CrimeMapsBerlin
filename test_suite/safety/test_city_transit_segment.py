import pytest
from shapely.geometry import box

from crimemapsberlin.city_transit_segment import source_track_segment
from crimemapsberlin.geometry_decisions import _derived_geometry


def way(ident, coordinates):
    return {"id": f"osm/way/{ident}", "names": ["U1"],
            "tags": {"railway": "subway"},
            "geometry": {"type": "LineString", "coordinates": coordinates}}


def stop(ident, coordinate):
    return {"id": f"osm/node/{ident}", "tags": {
        "public_transport": "stop_position", "subway": "yes"},
        "geometry": {"type": "Point", "coordinates": coordinate}}


def test_original_stops_cut_both_overhanging_ways_and_preserve_direction():
    tracks = [way(1, [(0, 0), (1, 0), (2, 1)]),
              way(2, [(2, 1), (3, 1), (4, 1)])]
    segment = source_track_segment(tracks, [stop(8, (3, 1)), stop(9, (1, 0))],
                                   line="U1", mode="subway")
    assert list(segment.coords) == [(3, 1), (2, 1), (1, 0)]


def test_nearby_off_track_station_cannot_be_projected_onto_track():
    with pytest.raises(ValueError, match="original mode stop"):
        source_track_segment([way(1, [(0, 0), (1, 0), (2, 0)])],
                             [stop(8, (0, 0)), stop(9, (1, .000001))],
                             line="U1", mode="subway")


def test_disconnected_track_cannot_be_filled_with_invented_connection():
    with pytest.raises(ValueError, match="connected path"):
        source_track_segment([way(1, [(0, 0), (1, 0)]), way(2, [(2, 0), (3, 0)])],
                             [stop(8, (0, 0)), stop(9, (3, 0))],
                             line="U1", mode="subway")


def test_station_label_point_cannot_replace_a_source_stop_position():
    label = stop(9, (1, 0))
    label["tags"]["public_transport"] = "station"
    with pytest.raises(ValueError, match="original mode stop"):
        source_track_segment([way(1, [(0, 0), (1, 0)])], [stop(8, (0, 0)), label],
                             line="U1", mode="subway")


def test_geometry_gate_retains_stop_provenance_and_rejects_full_line_substitution():
    rows = [way(1, [(0, 0), (1, 0), (2, 0)]), stop(8, (0, 0)), stop(9, (1, 0))]
    objects = {row["id"]: row for row in rows}
    decision = {"verdict": "resolved", "method": "osm_transit_segment",
                "osm_object_groups": [["osm/way/1"], ["osm/node/8"], ["osm/node/9"]]}
    request = {"geometry_task": "checked_transit_route_geometry_required",
               "precision": "route", "transit_route": {
                   "line": "U1", "mode": "subway", "extent": "source_segment"}}
    derived = _derived_geometry(decision, request, objects, box(-1, -1, 3, 1), "nuremberg")
    assert derived["geometry"]["coordinates"] == ((0., 0.), (1., 0.))
    assert derived["source_object_ids"] == ["osm/way/1", "osm/node/8", "osm/node/9"]
    assert "count_point" not in derived
    request["transit_route"]["extent"] = "full_line"
    with pytest.raises(ValueError, match="reviewed source segment"):
        _derived_geometry(decision, request, objects, box(-1, -1, 3, 1), "nuremberg")


def test_bus_mode_cannot_reuse_light_rail_tracks():
    track = way(1, [(0, 0), (1, 0)])
    track["tags"]["railway"] = "light_rail"
    stops = [stop(8, (0, 0)), stop(9, (1, 0))]
    for row in stops:
        row["tags"]["bus"] = "yes"
    with pytest.raises(ValueError, match="subway or tram only"):
        source_track_segment([track], stops, line="U1", mode="bus")
