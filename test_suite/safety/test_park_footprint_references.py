import copy

import pytest
from shapely.geometry import box, mapping

from crimemapsberlin.city_geometry_index import validate_geometry_index, write_geometry_index
from crimemapsberlin.geometry_decisions import compile_geometry_decisions
from crimemapsberlin.map_decisions import _count_point
from crimemapsberlin.park_footprint_references import METHOD, digest, park_footprint_reference


def inputs():
    rows = []
    for ident, left, name in [(1, 10, "Example park"), (2, 10.02, None), (3, 10.04, "Example park")]:
        tags = {"leisure": "park", **({"name": name} if name else {})}
        geometry = {"type": "Polygon", "coordinates": [[[left, 53], [left + .01, 53],
            [left + .01, 53.01], [left, 53.01], [left, 53]]]}
        nodes = [{"id": ident * 10 + i, "coordinates": xy}
                 for i, xy in enumerate(geometry["coordinates"][0][:-1])]
        nodes.append(copy.deepcopy(nodes[0]))
        way = {"id": ident, "tags": tags, "nodes": nodes}
        rows.append({"id": f"osm/way/{ident}", "source_url": f"https://www.openstreetmap.org/way/{ident}",
            "roles": sorted(["native_park_footprint", *(["named_object"] if name else [])]),
            "names": [name] if name else [], "tags": tags, "geometry": geometry,
            "geometry_sha256": digest(geometry), "dimension": "polygon",
            "native_park_source_proof": {"schema_version": 1, "reference_only": True,
                "source_pbf_sha256": "a" * 64, "source_way": way, "source_way_sha256": digest(way)}})
    request = {"source_id": "source-1", "source_sha256": "b" * 64, "decision_sha256": "c" * 64,
        "location_id": "source-1:location:1", "geometry_request_sha256": "d" * 64,
        "geometry_task": "checked_point_geocode_required", "precision": "place", "city_scope": "in_city",
        "coordinates": None, "transit_review": {"status": "not_applicable"},
        "poi_review": {"status": "context_only"}, "poi_contexts": [{"kind": "park"}]}
    decision = {"schema_version": 1, "city": "hamburg", "method": METHOD, "verdict": "resolved",
        "osm_object_groups": [[r["id"] for r in rows]],
        **{k: request[k] for k in ["source_id", "source_sha256", "decision_sha256", "location_id", "geometry_request_sha256"]},
        "review_note": "Original three park faces are context only; actual event position is unknown.",
        "reviewer": "test", "reviewed_at": "2026-10-02T00:00:00Z"}
    return decision, request, {r["id"]: r for r in rows}, box(9, 52, 11, 54)


def test_complete_native_faces_include_unnamed_middle_without_inventing_its_name_or_point(tmp_path):
    d, r, objects, border = inputs()
    source = {"sha256": "a" * 64, "pbf_timestamp": "2026-09-27T20:23:36Z"}
    boundary = {"id": "osm/relation/1", "source_pbf_sha256": "a" * 64, "geometry": mapping(border)}
    index = write_geometry_index(city="hamburg", objects=list(objects.values()), border=border,
        source_metadata=source, boundary_metadata=boundary, output=tmp_path / "index.json", pipeline_version=4)
    # The unnamed original face remains nameless and outside the name index.
    assert next(o for o in index["objects"] if o["id"] == "osm/way/2")["names"] == []
    assert "osm/way/2" not in index["name_index"]["example park"]
    assert validate_geometry_index(index, city="hamburg", border=border,
        source_metadata=source, boundary_metadata=boundary)["passed"]
    inventory = {"city": "hamburg", "inventory_digest": "e" * 64,
        "geometry_requests": [r], "all_current_reviews_supported": True}
    env = {"schema_version": 1, "city": "hamburg", "inventory_digest": "e" * 64,
        "geometry_index_sha256": index["index_sha256"], "decisions": [d]}
    compiled = compile_geometry_decisions(inventory=inventory, geometry_index=index,
        decision_envelope=env, border=border)
    row = compiled["decisions"][0]
    derived = row["derived_geometry"]
    assert derived["type"] == "MultiPolygon" and len(derived["geometry"]["coordinates"]) == 3
    assert derived["actual_event_position_known"] is False
    assert derived["complete_park_boundary_known"] is False
    assert not {"count_point", "representative_point", "coordinates"} & derived.keys()
    assert _count_point(row) is None
    derived["count_point"] = {"type": "Point", "coordinates": [10, 53]}
    assert _count_point(row) is None


@pytest.mark.parametrize("change", ["stale_pbf", "node", "geometry", "name", "tags", "proof", "outside", "different_park", "unnamed_only"])
def test_rejects_unbound_native_faces_or_mixed_park_identity(change):
    d, r, objects, border = inputs()
    row = objects["osm/way/2"]
    if change == "stale_pbf": row["native_park_source_proof"]["source_pbf_sha256"] = "0" * 64
    elif change == "node":
        proof = row["native_park_source_proof"]
        proof["source_way"]["nodes"].pop(1)
        proof["source_way_sha256"] = digest(proof["source_way"])
    elif change == "geometry":
        row["geometry"]["coordinates"][0][1][0] += .001
        row["geometry_sha256"] = digest(row["geometry"])
    elif change == "name": row["names"] = ["Invented name"]
    elif change == "tags": row["tags"]["leisure"] = "playground"
    elif change == "proof": row["native_park_source_proof"]["source_way_sha256"] = "0" * 64
    elif change == "outside": border = box(0, 0, 1, 1)
    elif change == "different_park":
        other = objects["osm/way/3"]
        other["tags"]["name"] = "Another park"
        other["names"] = ["Another park"]
        other["native_park_source_proof"]["source_way_sha256"] = digest(other["native_park_source_proof"]["source_way"])
    else: d["osm_object_groups"] = [["osm/way/2"]]
    with pytest.raises(ValueError): park_footprint_reference(d, r, objects, border, "a" * 64)


@pytest.mark.parametrize("change", [{"precision": "point"}, {"coordinates": [10, 53]},
    {"city_scope": "uncertain"}, {"transit_route": {"mode": "bus"}},
    {"transit_review": {"status": "reviewed_route"}}, {"poi_contexts": []}])
def test_rejects_turning_a_park_context_into_a_point_or_route(change):
    d, r, objects, border = inputs()
    r.update(copy.deepcopy(change))
    with pytest.raises(ValueError): park_footprint_reference(d, r, objects, border, "a" * 64)
