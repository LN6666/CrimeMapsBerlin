import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[2] / "scripts/migration/city_artifact.py"
spec = importlib.util.spec_from_file_location("city_artifact", MODULE)
artifact = importlib.util.module_from_spec(spec)
spec.loader.exec_module(artifact)


class ArtifactIsolationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.source = self.root / "source"
        generation = "0123456789abcdef-20261003T000000"
        manifest = {"schema_version": 2, "city": "Essen", "generation": generation,
                    "months": {"2026-01": {"count": 1}}, "tile_index": {"pois": [], "roads": []}}
        files = {"manifest.json": manifest,
                 f"{generation}/months/2026-01.json": {"event_ids": ["a"], "events": [{"id": "a", "month": "2026-01", "coordinates": None}]},
                 f"{generation}/roads-overview.json": {}, f"{generation}/search.json": [],
                 f"{generation}/boundary.geojson": {}}
        for name, value in files.items():
            target = self.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(value))
        self.provenance = self.root / "proof.json"
        self.proof = {"city": "essen", "manifest_sha256": artifact.digest(self.source / "manifest.json"),
                      "files": {k: artifact.digest(self.source / k) for k in files}}
        self.save_proof()

    def tearDown(self):
        self.directory.cleanup()

    def save_proof(self):
        self.provenance.write_text(json.dumps(self.proof))

    def package(self, city="essen", virtual_carrier=False):
        return artifact.package(self.source, self.root / "out", city,
                                artifact.digest(self.source / "manifest.json"), self.provenance,
                                artifact.digest(self.provenance), self.root / "receipt.json",
                                virtual_carrier=virtual_carrier)

    def add_translation(self, **changes):
        manifest_path = self.source / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["translations"] = {"en": {"2026-01": "translations/en/2026-01.json"}}
        manifest_path.write_text(json.dumps(manifest))
        name = f"{manifest['generation']}/translations/en/2026-01.json"
        path = self.source / name
        path.parent.mkdir(parents=True)
        value = {"schema_version": 1, "locale": "en", "city": "essen", "month": "2026-01",
                 "source_generation": manifest["generation"], "texts": {"a" * 64: "A public description"}}
        value.update(changes)
        path.write_text(json.dumps(value))
        self.proof["manifest_sha256"] = artifact.digest(manifest_path)
        self.proof["files"]["manifest.json"] = self.proof["manifest_sha256"]
        self.proof["files"][name] = artifact.digest(path)
        self.save_proof()
        return name, path

    def make_virtual(self):
        self.proof.update(virtual_allowlist_only=True, raw_or_private_provenance_copied=False,
                          scientific_judgments_changed=False, source_data_byte_changes=0,
                          manifest_path=str(self.source.resolve() / "manifest.json"))
        files = {}
        for name, sha in self.proof["files"].items():
            path = (self.source / name).resolve()
            files[name] = {"path": str(path), "sha256": sha, "bytes": path.stat().st_size}
        self.proof["files"] = files
        self.save_proof()

    def test_preserves_unknown_and_copies_only_bound_files(self):
        (self.source / "private-body.txt").write_text("private")
        result = self.package()
        self.assertEqual(result["map_announcement_count"], 1)
        month = next((self.root / "out/safety").glob("*/months/*.json"))
        self.assertIsNone(json.loads(month.read_text())["events"][0]["coordinates"])
        self.assertFalse((self.root / "out/safety/private-body.txt").exists())

    def test_rejects_cross_city_provenance(self):
        with self.assertRaisesRegex(ValueError, "Provenance city"):
            self.package("berlin")
        self.assertFalse((self.root / "out").exists())

    def test_rejects_changed_month_and_keeps_previous_good_output(self):
        month = next(self.source.glob("*/months/*.json"))
        month.write_text("{}")
        with self.assertRaisesRegex(ValueError, "hash changed"):
            self.package()
        self.assertFalse((self.root / "out").exists())

    def test_rejects_symlink_and_path_traversal(self):
        target = next(self.source.glob("*/search.json"))
        copy = self.root / "search.json"
        copy.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(copy)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.package()
        with self.assertRaises(ValueError):
            artifact.safe_relative("../berlin/manifest.json")

    def test_materializes_checked_public_translation_from_virtual_allowlist(self):
        name, path = self.add_translation()
        self.make_virtual()
        private = self.source / "full-body-and-review.json"
        private.write_text('{"private": "retained locally"}')
        external = self.root.resolve() / "checked-pack.json"
        external.write_bytes(path.read_bytes())
        path.unlink()
        self.proof["files"][name]["path"] = str(external)
        self.save_proof()
        result = self.package(virtual_carrier=True)
        self.assertEqual((self.root / "out/safety" / name).read_bytes(), external.read_bytes())
        self.assertFalse((self.root / "out/safety/full-body-and-review.json").exists())
        self.assertEqual(result["translation_pack_count"], 1)
        self.assertTrue(result["virtual_carrier_materialized"])
        self.assertFalse(result["publication_gate_passed"])

    def test_rejects_cross_city_translation_even_with_bound_hash(self):
        self.add_translation(city="berlin")
        with self.assertRaisesRegex(ValueError, "Translation identity"):
            self.package()
        self.assertFalse((self.root / "out").exists())

    def test_rejects_private_translation_extension_even_with_bound_hash(self):
        self.add_translation(raw_body="This must remain private")
        with self.assertRaisesRegex(ValueError, "private pack extension"):
            self.package()
        self.assertFalse((self.root / "out").exists())

    def test_rejects_stale_translation_generation(self):
        self.add_translation(source_generation="fedcba9876543210-20261002T000000")
        with self.assertRaisesRegex(ValueError, "Translation identity"):
            self.package()

    def test_rejects_virtual_symlink_without_creating_output(self):
        name, path = self.add_translation()
        self.make_virtual()
        external = self.root / "external.json"
        external.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(external)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.package(virtual_carrier=True)
        self.assertFalse((self.root / "out").exists())

    def test_rejects_translation_path_in_another_generation(self):
        self.add_translation()
        manifest_path = self.source / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["translations"]["en"]["2026-01"] = "../private/full-body.json"
        manifest_path.write_text(json.dumps(manifest))
        self.proof["manifest_sha256"] = artifact.digest(manifest_path)
        self.proof["files"]["manifest.json"] = self.proof["manifest_sha256"]
        self.save_proof()
        with self.assertRaisesRegex(ValueError, "unsafe path"):
            self.package()

    def test_virtual_carrier_requires_explicit_option_and_checked_flags(self):
        self.make_virtual()
        with self.assertRaisesRegex(ValueError, "hash changed"):
            self.package()
        self.proof["raw_or_private_provenance_copied"] = True
        self.save_proof()
        with self.assertRaisesRegex(ValueError, "Unchecked"):
            self.package(virtual_carrier=True)

    def test_virtual_manifest_cannot_be_replaced_by_another_bound_file(self):
        self.make_virtual()
        other = self.root.resolve() / "other-manifest.json"
        other.write_text('{"city": "Berlin"}')
        self.proof["files"]["manifest.json"] = {"path": str(other), "sha256": artifact.digest(other), "bytes": other.stat().st_size}
        self.save_proof()
        with self.assertRaisesRegex(ValueError, "Manifest file binding"):
            self.package(virtual_carrier=True)
        self.assertFalse((self.root / "out").exists())


if __name__ == "__main__":
    unittest.main()
