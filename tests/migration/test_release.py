import hashlib
import gzip
import importlib.util
import io
import json
from pathlib import Path
import tarfile

import pytest

PATH = Path(__file__).resolve().parents[2] / "scripts/migration/verify_release.py"
SPEC = importlib.util.spec_from_file_location("release", PATH)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def write_acceptance(tmp_path, **changes):
    value = {"schema_version": 1, "city": "essen", "repository": "LN6666/crimemaps-Essen",
             "code_commit": "a" * 40, "release_status": "accepted_for_publication",
             "languages": ["de", "en", "zh"], "artifact_receipt_sha256": "b" * 64,
             "checks": {k: {"status": "passed", "evidence_sha256": "c" * 64} for k in release.CHECKS},
             "input_bindings": {k: "d" * 64 for k in release.BINDINGS}}
    value.update(changes)
    path = tmp_path / "acceptance.json"
    path.write_text(json.dumps(value))
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_detached_acceptance_rejects_stale_commit_and_cross_city(tmp_path):
    path, digest = write_acceptance(tmp_path)
    release.acceptance(path, digest, "essen", "LN6666/crimemaps-Essen", "a" * 40)
    with pytest.raises(ValueError, match="stale"):
        release.acceptance(path, digest, "essen", "LN6666/crimemaps-Essen", "e" * 40)
    with pytest.raises(ValueError, match="stale"):
        release.acceptance(path, digest, "berlin", "LN6666/crimemaps-Berlin", "a" * 40)


def test_detached_acceptance_rejects_mutation_and_unconfigured_services(tmp_path):
    path, digest = write_acceptance(tmp_path)
    value = json.loads(path.read_text())
    value["checks"]["feedback"]["status"] = "implemented_service_unconfigured"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="trusted"):
        release.acceptance(path, digest, "essen", "LN6666/crimemaps-Essen", "a" * 40)
    with pytest.raises(ValueError, match="Unpassed"):
        release.acceptance(path, release.sha(path), "essen", "LN6666/crimemaps-Essen", "a" * 40)


def archive(tmp_path, members):
    path = tmp_path / "site.tar.gz"
    with tarfile.open(path, "w:gz") as stream:
        for name, kind in members:
            item = tarfile.TarInfo(name)
            if kind == "link":
                item.type = tarfile.SYMTYPE
                item.linkname = "/etc/passwd"
                stream.addfile(item)
            else:
                item.size = 4
                stream.addfile(item, io.BytesIO(b"test"))
    return path


@pytest.mark.parametrize("members", [
    [("site/../escape.txt", "file")],
    [("/site/escape.txt", "file")],
    [("site/data.json", "link")],
    [("site/data.json", "file"), ("site/data.json", "file")],
])
def test_untrusted_archive_rejected_before_output(tmp_path, members):
    path = archive(tmp_path, members)
    with pytest.raises(ValueError):
        release.unpack(path, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_safe_unpack_preserves_bytes_and_previous_output(tmp_path):
    path = archive(tmp_path, [("site/assets/main.js", "file")])
    output = tmp_path / "output"
    release.unpack(path, output)
    assert (output / "assets/main.js").read_bytes() == b"test"
    with pytest.raises(ValueError, match="Output exists"):
        release.unpack(path, output)


def test_extended_metadata_rejected_before_tarfile_parses_it(tmp_path):
    path = tmp_path / "pax.tar.gz"
    with tarfile.open(path, "w:gz", format=tarfile.PAX_FORMAT) as stream:
        member = tarfile.TarInfo("site/index.html")
        member.size = 4
        member.pax_headers = {"comment": "x" * (2 * 1024 * 1024)}
        stream.addfile(member, io.BytesIO(b"test"))
    with pytest.raises(ValueError, match="Extended metadata"):
        release.unpack(path, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_actual_decompression_stream_is_bounded(tmp_path, monkeypatch):
    path = archive(tmp_path, [("site/index.html", "file")])
    monkeypatch.setattr(release, "MAX_TAR_STREAM_BYTES", 1024)
    with pytest.raises(ValueError, match="stream exceeds"):
        release.unpack(path, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_nonzero_directory_cannot_hide_pax_from_header_precheck(tmp_path):
    nested = io.BytesIO()
    with tarfile.open(fileobj=nested, mode="w", format=tarfile.PAX_FORMAT) as stream:
        member = tarfile.TarInfo("site/index.html")
        member.size = 4
        member.pax_headers = {"comment": "x" * (2 * 1024 * 1024)}
        stream.addfile(member, io.BytesIO(b"test"))
    directory = tarfile.TarInfo("site")
    directory.type = tarfile.DIRTYPE
    directory.size = len(nested.getvalue())
    path = tmp_path / "hidden-pax.tar.gz"
    path.write_bytes(gzip.compress(directory.tobuf(format=tarfile.USTAR_FORMAT) + nested.getvalue()))
    with pytest.raises(ValueError, match="Directory TAR member"):
        release.unpack(path, tmp_path / "output")
    assert not (tmp_path / "output").exists()
