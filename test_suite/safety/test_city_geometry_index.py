import json

import pytest
from shapely.geometry import LineString, Point, box, mapping

from crimemapsberlin.city_geometry_index import (
    native_unnamed_way_object,
    validate_geometry_index,
    write_geometry_index,
)


def _fixture():
    source = {
        "sha256": "a" * 64,
        "pbf_timestamp": "2026-09-28T20:21:22Z",
    }
    border = box(6.70, 51.15, 6.90, 51.35)
    boundary = {
        "id": "osm/relation/62539",
        "source_pbf_sha256": source["sha256"],
        "geometry": mapping(border),
    }
    objects = [
        {
            "id": "osm/node/1",
            "source_url": "https://www.openstreetmap.org/node/1",
            "roles": ["named_object"],
            "names": ["Bolker Stern"],
            "tags": {"place": "square"},
            "dimension": "point",
            "geometry": mapping(Point(6.77, 51.23)),
        },
        {
            "id": "osm/way/2",
            "source_url": "https://www.openstreetmap.org/way/2",
            "roles": ["road", "named_object"],
            "names": ["Ratinger Straße", "Ratinger Str."],
            "tags": {"highway": "residential"},
            "dimension": "line",
            "geometry": mapping(LineString([(6.76, 51.22), (6.78, 51.24)])),
        },
    ]
    return source, border, boundary, objects


def test_geometry_index_is_source_bound_and_performs_no_semantic_match(tmp_path):
    source, border, boundary, objects = _fixture()
    output = tmp_path / "geometry-index.json"
    result = write_geometry_index(
        city="dusseldorf",
        objects=objects,
        border=border,
        boundary_metadata=boundary,
        source_metadata=source,
        output=output,
    )
    assert result["object_count"] == 2
    assert result["name_index"]["ratinger strasse"] == ["osm/way/2"]
    assert result["semantic_matching_performed"] is False
    assert result["publication_ready"] is False
    readback = json.loads(output.read_text())
    assert validate_geometry_index(
        readback,
        city="dusseldorf",
        border=border,
        boundary_metadata=boundary,
        source_metadata=source,
    ) == {"passed": True, "errors": []}


def test_geometry_index_readback_rejects_tampering(tmp_path):
    source, border, boundary, objects = _fixture()
    output = tmp_path / "geometry-index.json"
    result = write_geometry_index(
        city="dusseldorf",
        objects=objects,
        border=border,
        boundary_metadata=boundary,
        source_metadata=source,
        output=output,
    )
    result["objects"][0]["geometry"]["coordinates"] = [7.5, 52.0]
    validation = validate_geometry_index(
        result,
        city="dusseldorf",
        border=border,
        boundary_metadata=boundary,
        source_metadata=source,
    )
    assert validation["passed"] is False
    assert any("outside boundary" in error for error in validation["errors"])
    assert any("digest differs" in error for error in validation["errors"])

    result = json.loads(output.read_text())
    result["role_counts"] = {"named_object": 999}
    validation = validate_geometry_index(
        result,
        city="dusseldorf",
        border=border,
        boundary_metadata=boundary,
        source_metadata=source,
    )
    assert "role counts differ" in validation["errors"]


def test_closed_pedestrian_area_and_explicit_nonarea_keep_osm_dimensions(tmp_path):
    from crimemapsberlin.city_geometry_index import GeometryScanner

    osm = tmp_path / "source.osm"
    osm.write_text("""<osm version="0.6">
      <node id="1" lat="51.22" lon="6.76"/>
      <node id="2" lat="51.22" lon="6.78"/>
      <node id="3" lat="51.24" lon="6.78"/>
      <node id="4" lat="51.24" lon="6.76"/>
      <way id="10"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="1"/>
        <tag k="name" v="Pedestrian square"/><tag k="highway" v="pedestrian"/>
        <tag k="area" v="yes"/></way>
      <way id="11"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="1"/>
        <tag k="name" v="Circular road"/><tag k="highway" v="residential"/></way>
      <way id="12"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="1"/>
        <tag k="name" v="Explicit line"/><tag k="area" v="no"/></way>
    </osm>""")
    scanner = GeometryScanner(box(6.70, 51.15, 6.90, 51.35))
    scanner.apply_file(str(osm), locations=True)
    objects = {row["id"]: row for row in scanner.objects}
    assert objects["osm/way/10"]["geometry"]["type"] == "Polygon"
    assert "road" in objects["osm/way/10"]["roles"]
    assert objects["osm/way/11"]["geometry"]["type"] == "LineString"
    assert objects["osm/way/12"]["geometry"]["type"] == "LineString"


def test_osm_aliases_modes_and_highway_refs_retain_raw_provenance():
    from crimemapsberlin.city_geometry_index import _object

    row = _object(
        ident="osm/way/1", geometry=LineString([(6.76, 51.22), (6.78, 51.24)]),
        dimension="line", tags={"highway": "motorway", "ref": "A 6"},
    )
    assert row["names"] == ["A 6"]
    assert row["tags"]["ref"] == "A 6"
    platform = _object(
        ident="osm/way/2", geometry=box(6.76, 51.22, 6.78, 51.24),
        dimension="polygon", tags={"name": "New square", "old_name": "Old square",
        "area": "yes", "level": "-2", "subway": "yes"},
    )
    assert platform["tags"]["name"] == "New square"
    assert platform["tags"]["old_name"] == "Old square"
    assert platform["tags"]["level"] == "-2"
    assert platform["tags"]["subway"] == "yes"


def test_legacy_index_still_requires_valid_digest(tmp_path):
    from crimemapsberlin.city_geometry_index import _digest

    source, border, boundary, objects = _fixture()
    result = write_geometry_index(
        city="dusseldorf", objects=objects, border=border, boundary_metadata=boundary,
        source_metadata=source, output=tmp_path / "geometry-index.json",
    )
    result["pipeline_version"] = 1
    core = {key: value for key, value in result.items() if key in {
        "schema_version", "pipeline_version", "city", "source_pbf_sha256",
        "source_pbf_timestamp", "boundary_source_id", "boundary_sha256",
        "objects", "name_index",
    }}
    result["index_sha256"] = _digest(core)
    assert validate_geometry_index(
        result, city="dusseldorf", border=border, boundary_metadata=boundary,
        source_metadata=source,
    )["passed"] is True
    result["objects"][0]["tags"]["old_name"] = "Tampered alias"
    assert "index digest differs" in validate_geometry_index(
        result, city="dusseldorf", border=border, boundary_metadata=boundary,
        source_metadata=source,
    )["errors"]


def _native_unnamed(source, border):
    return native_unnamed_way_object(
        source_way={"id": 42, "tags": {"highway": "footway", "layer": "-1", "tunnel": "yes"},
                    "node_ids": [101, 102, 103],
                    "geometry": mapping(LineString([(6.76, 51.22), (6.77, 51.23), (6.78, 51.24)]))},
        source_metadata=source, border=border,
    )


def test_unnamed_native_way_requires_opt_in_and_does_not_invent_name(tmp_path):
    source, border, boundary, objects = _fixture()
    row = _native_unnamed(source, border)
    assert row["names"] == [] and row["roles"] == ["road"]
    assert row["tags"]["layer"] == "-1"
    assert row["native_unnamed_way_source_proof"]["source_way"]["node_ids"] == [101, 102, 103]
    with pytest.raises(ValueError, match="invalid native unnamed way proof"):
        write_geometry_index(city="dusseldorf", objects=[*objects, row], border=border,
                             boundary_metadata=boundary, source_metadata=source,
                             output=tmp_path / "legacy.json")
    output = tmp_path / "native.json"
    result = write_geometry_index(city="dusseldorf", objects=[*objects, row], border=border,
                                 boundary_metadata=boundary, source_metadata=source,
                                 output=output, pipeline_version=4)
    assert result["pipeline_version"] == 4
    assert not any("osm/way/42" in ids for ids in result["name_index"].values())
    assert validate_geometry_index(json.loads(output.read_text()), city="dusseldorf", border=border,
                                   boundary_metadata=boundary, source_metadata=source)["passed"]
    result["pipeline_version"] = 3
    assert any("native unnamed way proof" in e for e in validate_geometry_index(
        result, city="dusseldorf", border=border, boundary_metadata=boundary, source_metadata=source)["errors"])


@pytest.mark.parametrize("change", ["source_hash", "source_digest", "geometry", "alias", "roles", "tags"])
def test_unnamed_native_way_readback_binds_source_and_geometry(tmp_path, change):
    source, border, boundary, _ = _fixture()
    result = write_geometry_index(city="dusseldorf", objects=[_native_unnamed(source, border)],
                                 border=border, boundary_metadata=boundary, source_metadata=source,
                                 output=tmp_path / "native.json", pipeline_version=4)
    row = result["objects"][0]
    if change == "source_hash":
        row["native_unnamed_way_source_proof"]["source_pbf_sha256"] = "b" * 64
    elif change == "source_digest":
        row["native_unnamed_way_source_proof"]["source_way"]["node_ids"][1] = 999
    elif change == "geometry":
        row["geometry"] = mapping(LineString([(6.76, 51.22), (6.775, 51.235)]))
    elif change == "alias":
        row["names"] = ["Guessed bridge path"]
    elif change == "roles":
        row["roles"] = ["named_object", "road"]
    else:
        row["tags"]["layer"] = "1"
    assert any("native unnamed way proof" in e for e in validate_geometry_index(
        result, city="dusseldorf", border=border, boundary_metadata=boundary, source_metadata=source)["errors"])


@pytest.mark.parametrize("tags", [
    {"highway": "platform"}, {"highway": "bus_stop"}, {"highway": "construction"},
    {"highway": "footway", "construction:highway": "footway"},
    {"highway": "service", "disused:highway": "service"},
    {"highway": "pedestrian", "area": "yes"},
    {"highway": "footway", "public_transport": "platform"},
    {"highway": "footway", "name": "Already named"},
])
def test_unnamed_native_way_rejects_inactive_platform_area_and_named(tags):
    source, border, _, _ = _fixture()
    with pytest.raises(ValueError):
        native_unnamed_way_object(source_way={"id": 42, "tags": tags, "node_ids": [101, 102],
            "geometry": mapping(LineString([(6.76, 51.22), (6.78, 51.24)]))},
            source_metadata=source, border=border)


def test_unnamed_native_way_rejects_missing_native_nodes():
    source, border, _, _ = _fixture()
    with pytest.raises(ValueError, match="complete node sequence"):
        native_unnamed_way_object(source_way={"id": 42, "tags": {"highway": "motorway_link"},
            "node_ids": [101], "geometry": mapping(LineString([(6.76, 51.22), (6.78, 51.24)]))},
            source_metadata=source, border=border)
