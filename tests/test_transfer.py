"""Transfer/storage regressions, all in temporary test-* fixture roots."""

from io import BytesIO
import os
import sys
import zipfile

import pytest

from tools.contracts import sha
from tools.errors import CoreError
from tools.safeio import SafeRoot, canonical, parse_json
from tools.store import Store
from tools.transfer import import_case
from .test_portable_transfer import BUNDLE, CASE, fixture_bundle, rewrite_archive


def test_same_root_restricted_backup_still_uses_original_local_receipt(tmp_path):
    source, _, raw, _ = fixture_bundle(tmp_path)
    with SafeRoot(source) as root:
        root.mkdir_exclusive("retained")
        root.promote_directory("cases/" + CASE, "retained/" + CASE)
    result = import_case(source, "output/backups/demo.zip", CASE, "test")
    assert result["data"]["local_consent_receipt"] is None
    with Store(source, CASE) as store:
        assert not store._load()[1]
        assert store.io.json(".local/backup-receipts/" + sha(raw) + ".json")["case_id"] == CASE


def test_transfer_permitted_sources_keep_existing_fresh_root_path(tmp_path):
    _, destination, _, _ = fixture_bundle(tmp_path, transfer=True)
    result = import_case(destination, BUNDLE, CASE, "test")
    assert result["data"]["local_consent_receipt"] is None
    with Store(destination, CASE) as store:
        assert not store._load()[1]


def test_existing_target_is_never_overwritten(tmp_path):
    _, destination, raw, _ = fixture_bundle(tmp_path)
    with SafeRoot(destination) as root:
        root.write("cases/" + CASE + "/sentinel.txt", b"original")
    with pytest.raises(CoreError) as error:
        import_case(destination, BUNDLE, CASE, "test", trusted_bundle_sha256=sha(raw))
    assert error.value.code == "IMPORT_EXISTS"
    assert (destination / "cases" / CASE / "sentinel.txt").read_bytes() == b"original"
    assert not (destination / "cases" / CASE / "events.jsonl").exists()


def test_native_atomic_promotion_will_not_replace_even_empty_directory(tmp_path):
    with SafeRoot(tmp_path) as root:
        root.mkdir_exclusive("staged")
        root.mkdir_exclusive("existing")
        root.write("staged/data.txt", b"keep")
        with pytest.raises(CoreError) as error:
            root.promote_directory("staged", "existing")
        assert error.value.code == "IMPORT_EXISTS"
        assert root.read("staged/data.txt") == b"keep"
        assert root.listdir("existing") == []


@pytest.mark.parametrize("point", ["staging-write", "promotion"])
def test_interrupted_installation_has_no_partial_accepted_target(tmp_path, monkeypatch, point):
    _, destination, raw, _ = fixture_bundle(tmp_path)
    original_write = SafeRoot.write
    calls = []

    def interrupted_write(self, path, content, **kwargs):
        if "/import-staging/" in str(self.path):
            calls.append(path)
            if len(calls) == 2:
                raise CoreError("INJECTED_WRITE_FAILURE", "Bounded technical fault injection", 5)
        return original_write(self, path, content, **kwargs)

    def interrupted_promotion(self, source, target):
        calls.append(source)
        assert target == "cases/" + CASE
        assert not self.exists(target)
        with self.subroot(source.rsplit("/cases/", 1)[0]) as staged_root:
            with Store(staged_root, CASE) as staged:
                assert not staged._load()[1]  # Complete verified image, before the single rename.
        raise CoreError("INJECTED_PROMOTION_FAILURE", "Bounded technical fault injection", 5)

    if point == "staging-write":
        monkeypatch.setattr(SafeRoot, "write", interrupted_write)
    else:
        monkeypatch.setattr(SafeRoot, "promote_directory", interrupted_promotion)
    with pytest.raises(CoreError) as error:
        import_case(destination, BUNDLE, CASE, "test", trusted_bundle_sha256=sha(raw))
    assert error.value.code.startswith("INJECTED_")
    assert calls
    assert not (destination / "cases" / CASE).exists()
    stages = list((destination / ".local/import-staging").iterdir())
    assert len(stages) == 1  # Failure evidence retained, never broad-deleted.


def test_unsupported_atomic_primitive_fails_closed_without_plain_rename(tmp_path, monkeypatch):
    _, destination, raw, _ = fixture_bundle(tmp_path)
    original = SafeRoot.promote_directory

    def unsupported(self, source, target):
        with monkeypatch.context() as patch:
            patch.setattr(sys, "platform", "unsupported-fixture-os")
            return original(self, source, target)

    monkeypatch.setattr(SafeRoot, "promote_directory", unsupported)
    with pytest.raises(CoreError) as error:
        import_case(destination, BUNDLE, CASE, "test", trusted_bundle_sha256=sha(raw))
    assert error.value.code == "ATOMIC_DIRECTORY_UNAVAILABLE"
    assert not (destination / "cases" / CASE).exists()


def test_pinned_subroot_and_store_clone_survive_ancestor_rename(tmp_path):
    with SafeRoot(tmp_path) as root:
        root.mkdir_exclusive("pinned")
        with root.subroot("pinned") as pinned, SafeRoot(pinned) as clone:
            os.rename(tmp_path / "pinned", tmp_path / "moved")
            root.mkdir_exclusive("pinned")
            clone.write("fixture.txt", b"descriptor anchored")
            assert pinned.read("fixture.txt") == b"descriptor anchored"
            assert not root.exists("pinned/fixture.txt")
            assert root.read("moved/fixture.txt") == b"descriptor anchored"


def test_manifest_cannot_smuggle_extra_uncommitted_files(tmp_path):
    _, destination, raw, _ = fixture_bundle(tmp_path)

    def add_file(files):
        name = "cases/" + CASE + "/artifacts/sha256/" + "0" * 64
        manifest = parse_json(files["manifest.json"])
        manifest["files"][name] = sha(b"uncommitted")
        files["manifest.json"] = canonical(manifest)
        files[name] = b"uncommitted"

    altered = rewrite_archive(raw, member_edit=add_file)
    with SafeRoot(destination) as root:
        root.write(BUNDLE, altered)
    with pytest.raises(CoreError) as error:
        import_case(destination, BUNDLE, CASE, "test", trusted_bundle_sha256=sha(altered))
    assert error.value.code == "ARCHIVE_MANIFEST"
    assert not (destination / "cases" / CASE).exists()


@pytest.mark.parametrize("kind", ["traversal", "symlink", "ratio", "expanded-cap"])
def test_archive_safety_caps_survive_trusted_digest(tmp_path, monkeypatch, kind):
    _, destination, _, _ = fixture_bundle(tmp_path)
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo("../escape" if kind == "traversal" else "payload")
        info.compress_type = zipfile.ZIP_DEFLATED
        if kind == "symlink":
            info.external_attr = 0o120777 << 16
        size = 2 * 1024 * 1024 if kind == "ratio" else 4096 if kind == "expanded-cap" else 10
        archive.writestr(info, b"x" * size)
    raw = output.getvalue()
    with SafeRoot(destination) as root:
        root.write(BUNDLE, raw)
    if kind == "expanded-cap":
        import tools.transfer as module

        monkeypatch.setattr(module, "CAP", 1024)
    with pytest.raises(CoreError) as error:
        import_case(destination, BUNDLE, CASE, "test", trusted_bundle_sha256=sha(raw))
    assert error.value.exit_code == 4
    assert not (destination / ".local").exists()
