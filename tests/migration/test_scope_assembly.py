import importlib.util
import json
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[2] / "scripts/migration/assemble_scope.py"
SPEC = importlib.util.spec_from_file_location("assembly", PATH)
assembly = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(assembly)


def fixture(tmp_path):
    source, overlay = tmp_path / "source", tmp_path / "overlay"
    source.mkdir()
    overlay.mkdir()
    generation = "a" * 16 + "-20261002T120000"
    manifest = {"city": "Essen", "generation": generation, "months": {"2026-01": {"count": 1}},
                "categories": ["sonstige"], "tile_index": {"pois": ["context/1_2"], "roads": []},
                "metadata": {}, "publication_ready": False}
    files = {"search.json": [], "boundary.geojson": {"type": "FeatureCollection", "features": []},
             "roads-overview.json": {"type": "FeatureCollection", "features": []},
             "months/2026-01.json": {"events": [{"id": "e1", "coordinates": None}],
                                    "hex": {"overview": {"features": []}}, "links": [{"poi_id": "osm/node/1"}]},
             "pois/context/1_2.json": {"type": "FeatureCollection", "features": []}}
    for relative, value in files.items():
        path = source / generation / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
    (source / "manifest.json").write_text(json.dumps(manifest))
    candidate = dict(manifest, tile_index={"pois": [], "roads": []})
    (overlay / "manifest.candidate.json").write_text(json.dumps(candidate))
    receipt = {"native_geometry_changed": False, "reviewed_records_changed": False,
               "all_protected_ids_retained": True, "publication_ready": False,
               "input_manifest_file_sha256": assembly.sha(source / "manifest.json"),
               "input_file_sha256": {generation + "/" + key: assembly.sha(source / generation / key) for key in files},
               "overlay_file_sha256": {}, "removed_files": [generation + "/pois/context/1_2.json"]}
    (overlay / "poi-scope-receipt.json").write_text(json.dumps(receipt))
    return source, overlay, generation


def run(source, overlay, output, manifest_sha=None):
    return assembly.assemble(source, overlay, assembly.sha(overlay / "poi-scope-receipt.json"),
                             output, output.parent / "report.json", overlay_manifest_sha=manifest_sha or
                             assembly.sha(overlay / "manifest.candidate.json"))


def test_new_generation_preserves_month_unknown_geometry_links_and_hex(tmp_path):
    source, overlay, old = fixture(tmp_path)
    result = run(source, overlay, tmp_path / "new")
    generation = result["generation"]
    assert generation != old
    assert (tmp_path / "new" / generation / "months/2026-01.json").read_bytes() == (source / old / "months/2026-01.json").read_bytes()
    assert not (tmp_path / "new" / generation / "pois/context/1_2.json").exists()
    with pytest.raises(ValueError, match="output must be new"):
        run(source, overlay, tmp_path / "new")


def test_tampered_overlay_manifest_rejected_before_output(tmp_path):
    source, overlay, _ = fixture(tmp_path)
    bound = assembly.sha(overlay / "manifest.candidate.json")
    (overlay / "manifest.candidate.json").write_text("{}")
    with pytest.raises(ValueError, match="detached binding"):
        run(source, overlay, tmp_path / "new", bound)
    assert not (tmp_path / "new").exists()


def test_changed_source_or_unbound_boundary_rejected_before_output(tmp_path):
    source, overlay, old = fixture(tmp_path)
    (source / old / "boundary.geojson").write_text("{}")
    with pytest.raises(ValueError, match="source payload changed"):
        run(source, overlay, tmp_path / "new")
    assert not (tmp_path / "new").exists()
