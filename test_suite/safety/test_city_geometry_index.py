import json

from shapely.geometry import LineString, Point, box, mapping

from crimemapsberlin.city_geometry_index import (
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
