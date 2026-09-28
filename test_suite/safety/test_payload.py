from crimemapsberlin.payload import canonical_events, compact
from crimemapsberlin.review import fingerprint
from crimemapsberlin.spatial import cell_for, hexagons


def test_compact_keeps_public_scene_geometry_and_order():
    event = dict(
        id="1",
        location_geometry={"type": "Point", "coordinates": [13.4, 52.5]},
        scene_locations=[
            dict(label="incident", primary_for_count=True,
                 coordinates=[13.40000049, 52.50000049],
                 geometry={"type": "Point", "coordinates": [13.40000049, 52.50000049]}),
            dict(label="road review", primary_for_count=False,
                 candidate_road_geometry={"type": "LineString", "coordinates": [
                     [13.40100049, 52.5], [13.40200049, 52.5],
                 ]}),
            dict(label="discovery area", primary_for_count=False,
                 geometry={"type": "Polygon", "coordinates": [[
                     [13.4, 52.5], [13.41, 52.5], [13.41, 52.51],
                     [13.4, 52.5],
                 ]]}),
        ],
    )
    result = compact(event)
    assert "location_geometry" not in result
    assert [scene["label"] for scene in result["scene_locations"]] == [
        "incident", "road review", "discovery area",
    ]
    assert result["scene_locations"][0]["coordinates"] == [13.4, 52.5]
    assert result["scene_locations"][0]["geometry"]["coordinates"] == [13.4, 52.5]
    assert result["scene_locations"][1]["candidate_road_geometry"]["coordinates"][0] == [
        13.401, 52.5,
    ]
    assert result["scene_locations"][2]["geometry"]["type"] == "Polygon"


def test_build_uses_reviewed_rounding_for_hex_boundary():
    raw_point = [13.404104545655915, 52.4997182981576]
    raw = dict(
        id="boundary", category="Raub", coordinates=raw_point,
        location_precision="street", location_label="Junction",
        scene_locations=[dict(
            label="Junction", role="incident", location_precision="street",
            geocode_method="junction", coordinates=raw_point,
            primary_for_count=True,
        )],
    )
    candidate = canonical_events([raw])[0]
    assert candidate["coordinates"] == candidate["scene_locations"][0]["coordinates"]
    assert fingerprint(candidate) != fingerprint(raw)
    assert cell_for(*raw_point, 275)[0] != cell_for(*candidate["coordinates"], 275)[0]
    assert hexagons([candidate], 275)["features"][0]["properties"]["id"] == cell_for(
        *candidate["coordinates"], 275,
    )[0]
