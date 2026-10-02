import pytest
from shapely.geometry import LineString, Point, mapping

from crimemapsberlin.city_road_segment import source_road_segments


def road(points, **tags):
    return {"roles": ["road"], "tags": {"highway": "secondary", **tags},
            "geometry": mapping(LineString(points))}


def triple(y=0):
    return [[road([(0, y), (1, y), (2, y), (3, y)]), road([(3, y), (4, y)])],
            [road([(1, y - 0.2), (1, y), (1, y + 0.2)])],
            [road([(3, y - 0.2), (3, y), (3, y + 0.2)])]]


def test_segment_preserves_only_native_vertices_between_explicit_junctions():
    segment = source_road_segments(triple())
    assert set(segment.coords) == {(1, 0), (2, 0), (3, 0)}
    assert segment.length == 2


def test_separate_carriageways_keep_both_checked_ranges_without_connecting_them():
    segment = source_road_segments(triple() + triple(1))
    assert segment.geom_type == "MultiLineString"
    assert segment.length == 4
    assert len(segment.geoms) == 2


def motorway_junction(x, y=0):
    return {"id": "osm/node/123", "roles": ["road", "named_object"],
            "tags": {"highway": "motorway_junction", "name": "Selected exit", "ref": "20"},
            "geometry": mapping(Point(x, y))}


def test_native_motorway_junction_nodes_bound_only_original_path_vertices():
    groups = triple()
    groups[1], groups[2] = [motorway_junction(3)], [motorway_junction(1)]
    segment = source_road_segments(groups)
    assert list(segment.coords) == [(3, 0), (2, 0), (1, 0)]


@pytest.mark.parametrize("mutation,error", [
    ("mid_edge", "shared native"),
    ("not_on_path", "unique junction"),
    ("ordinary_point", "operational"),
    ("not_node", "operational"),
    ("missing_role", "operational"),
    ("multiple_nodes", "operational"),
])
def test_motorway_node_endpoints_do_not_accept_arbitrary_points(mutation, error):
    groups = triple()
    groups[1] = [motorway_junction(1)]
    if mutation == "mid_edge":
        groups[1] = [motorway_junction(1.5)]
    elif mutation == "not_on_path":
        groups[1] = [motorway_junction(8)]
    elif mutation == "ordinary_point":
        groups[1][0]["tags"]["highway"] = "traffic_signals"
    elif mutation == "not_node":
        groups[1][0]["id"] = "osm/way/123"
    elif mutation == "missing_role":
        groups[1][0]["roles"] = ["named_object"]
    elif mutation == "multiple_nodes":
        groups[1].append(motorway_junction(2))
    with pytest.raises(ValueError, match=error):
        source_road_segments(groups)


@pytest.mark.parametrize("mutation, error", [
    ("mid_edge", "shared native"),
    ("no_junction", "unique junction"),
    ("two_junctions", "unique junction"),
    ("branch", "nonbranching"),
    ("disconnected", "nonbranching"),
    ("closed", "noncyclic"),
    ("same_endpoint", "distinct"),
    ("construction", "operational"),
    ("point", "operational"),
])
def test_invalid_segment_choices_fail_closed(mutation, error):
    groups = triple()
    if mutation == "mid_edge":
        groups[1] = [road([(1.5, -0.2), (1.5, 0), (1.5, 0.2)])]
    elif mutation == "no_junction":
        groups[1] = [road([(8, -0.2), (8, 0), (8, 0.2)])]
    elif mutation == "two_junctions":
        groups[1] += [road([(2, -0.2), (2, 0), (2, 0.2)])]
    elif mutation == "branch":
        groups[0] += [road([(2, 0), (2, 1)])]
    elif mutation == "disconnected":
        groups[0] += [road([(6, 0), (7, 0)])]
    elif mutation == "closed":
        groups[0] = [road([(0, 0), (1, 0), (3, 0), (0, 1), (0, 0)])]
    elif mutation == "same_endpoint":
        groups[2] = groups[1]
    elif mutation == "construction":
        groups[0][0]["tags"]["highway"] = "construction"
    elif mutation == "point":
        groups[1][0]["geometry"] = {"type": "Point", "coordinates": [1, 0]}
    with pytest.raises(ValueError, match=error):
        source_road_segments(groups)


@pytest.mark.parametrize("groups", [[], [[road([(0, 0), (1, 0)])]], [[], [], []]])
def test_incomplete_group_choices_are_rejected(groups):
    with pytest.raises(ValueError, match="road.*group"):
        source_road_segments(groups)
