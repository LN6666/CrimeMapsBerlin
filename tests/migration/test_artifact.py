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

    def package(self, city="essen"):
        return artifact.package(self.source, self.root / "out", city,
                                artifact.digest(self.source / "manifest.json"), self.provenance,
                                artifact.digest(self.provenance), self.root / "receipt.json")

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


if __name__ == "__main__":
    unittest.main()
