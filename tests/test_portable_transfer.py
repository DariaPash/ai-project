"""Temporary test-* stores only; no network/model calls or benchmark."""

from io import BytesIO

import pytest

from tools.contracts import digest, sha
from tools.errors import CoreError
from tools.safeio import SafeRoot, canonical, parse_json
from tools.store import Store
from tools.transfer import export_case, import_case
from .helpers import add, artifact, make_project

import zipfile


CASE = "test-portable"
BUNDLE = "input/backups/demo.zip"


def fixture_bundle(tmp_path, *, origin="synthetic_fixture", processing=True, transfer=False):
    source = make_project(tmp_path / "source")
    with Store(source, CASE) as store:
        store.init("test")
    raw = b"Owned synthetic technical fixture, not actual customer data.\n"
    art = artifact(source, raw, case=CASE, origin=origin)
    add(
        source,
        "source",
        {
            "title": "Synthetic transfer fixture",
            "location": "fixture.txt",
            "origin": origin,
            "retrieved_at": "2026-11-08T00:00:00Z",
            "published_at": "unknown",
            "sha256": sha(raw),
            "status": "available",
            "rights": {"processing": processing, "external_transfer": transfer, "publication": False},
            "artifact_ref": art,
        },
        case=CASE,
    )
    with Store(source, CASE) as store:
        exported = export_case(store, "backup", "output/backups/demo.zip")
        archive = store.io.read("output/backups/demo.zip")
    destination = tmp_path / "destination"
    destination.mkdir()
    with SafeRoot(destination) as root:
        root.write(BUNDLE, archive)
    return source, destination, archive, exported


def rewrite_archive(raw, *, manifest_edit=None, member_edit=None):
    with zipfile.ZipFile(BytesIO(raw)) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    if manifest_edit:
        manifest = parse_json(files["manifest.json"])
        manifest_edit(manifest)
        files["manifest.json"] = canonical(manifest)
    if member_edit:
        member_edit(files)
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def test_fresh_root_digest_restore_preserves_exact_history_and_local_only_receipt(tmp_path, monkeypatch):
    source, destination, raw, exported = fixture_bundle(tmp_path)
    with zipfile.ZipFile(BytesIO(raw)) as archive:
        manifest = parse_json(archive.read("manifest.json"))
        history = {name: archive.read(name) for name in manifest["files"]}
    assert not manifest["external_transfer_allowed"]
    # A portable restore must never open the original Store, even if available.
    original_init = Store.__init__

    def no_original(self, project, case_id):
        assert str(project) != str(source)
        original_init(self, project, case_id)

    monkeypatch.setattr(Store, "__init__", no_original)
    result = import_case(destination, BUNDLE, CASE, "test", trusted_bundle_sha256=sha(raw))
    assert result["case_revision"] == exported["case_revision"]
    with Store(destination, CASE) as restored:
        snapshot, warnings, _ = restored._load()
        assert not warnings
        assert digest(snapshot) == manifest["snapshot_digest"]
        assert snapshot["namespace"] == "test"
        for name, content in history.items():
            assert restored.io.read(name) == content
        records = restored.records(snapshot)
        src = next(r for r in records.values() if r["kind"] == "source")
        assert src["payload"]["rights"] == {"processing": True, "external_transfer": False, "publication": False}
        receipt_path = result["data"]["local_consent_receipt"]
        assert receipt_path == ".local/import-consents/" + sha(raw) + ".json"
        receipt = restored.io.json(receipt_path)
        assert receipt["archive_sha256"] == sha(raw)
        assert receipt["snapshot_digest"] == digest(snapshot)
        assert receipt["local_processing"] is True
        assert receipt["model_transfer"] is False and receipt["publication"] is False
        assert receipt["rightsholder_identity_verified"] is False
        assert result["data"]["scoped_transfer"] is None
        assert result["data"]["capabilities_inherited"] is False
        assert result["data"]["credentials_imported"] is False
        export_case(restored, "backup", "output/backups/restored.zip")
        with zipfile.ZipFile(BytesIO(restored.io.read("output/backups/restored.zip"))) as archive:
            assert not any("import-consents" in name for name in archive.namelist())
        with pytest.raises(CoreError, match="publication rights") as error:
            export_case(restored, "public", "output/backups/public.zip")
        assert error.value.code == "PUBLICATION_DENIED"


@pytest.mark.parametrize("provided", ["0" * 64, "abc", "", 123])
def test_wrong_digest_rejected_before_any_write_or_staging(tmp_path, monkeypatch, provided):
    _, destination, _, _ = fixture_bundle(tmp_path)

    def no_write(*args, **kwargs):
        pytest.fail("Digest failure must precede every write/staging operation")

    monkeypatch.setattr(SafeRoot, "write", no_write)
    monkeypatch.setattr(SafeRoot, "mkdir_exclusive", no_write)
    with pytest.raises(CoreError) as error:
        import_case(destination, BUNDLE, CASE, "test", trusted_bundle_sha256=provided)
    assert error.value.code == "TRUSTED_BUNDLE_HASH"
    assert not (destination / ".local").exists()


def test_manifest_flags_or_embedded_digest_cannot_grant_consent(tmp_path):
    _, destination, raw, _ = fixture_bundle(tmp_path)

    def grant(manifest):
        manifest.update(external_transfer_allowed=True, trusted_bundle_sha256=sha(raw), local_processing=True)

    altered = rewrite_archive(raw, manifest_edit=grant)
    with SafeRoot(destination) as root:
        root.write(BUNDLE, altered)
    with pytest.raises(CoreError) as error:
        import_case(destination, BUNDLE, CASE, "test")
    assert error.value.code == "TRANSFER_DENIED"
    assert not (destination / "cases" / CASE).exists()
    assert not (destination / ".local/import-consents").exists()


@pytest.mark.parametrize(
    "origin,processing",
    [("owner_observation", True), ("public_source", True), ("unknown", True), ("synthetic_fixture", False)],
)
def test_digest_does_not_authorize_real_unknown_or_processing_denied_sources(tmp_path, origin, processing):
    _, destination, raw, _ = fixture_bundle(tmp_path, origin=origin, processing=processing)
    with pytest.raises(CoreError) as error:
        import_case(destination, BUNDLE, CASE, "test", trusted_bundle_sha256=sha(raw))
    assert error.value.code == "LOCAL_CONSENT_SCOPE"
    assert not (destination / "cases" / CASE).exists()
    assert not (destination / ".local/import-consents").exists()


def test_digest_cannot_bypass_historical_processing_denial(tmp_path):
    source, destination, _, _ = fixture_bundle(tmp_path, processing=False)
    with Store(source, CASE) as store:
        snapshot, _, _ = store._load()
        source_record = next(r for r in store.records(snapshot).values() if r["kind"] == "source")
        payload = source_record["payload"]
        payload["rights"]["processing"] = True
        store.record("source", {"id": source_record["id"], "payload": payload}, snapshot["case_revision"])
        export_case(store, "backup", "output/backups/later.zip")
        raw = store.io.read("output/backups/later.zip")
    with SafeRoot(destination) as root:
        root.write(BUNDLE, raw)
    with pytest.raises(CoreError) as error:
        import_case(destination, BUNDLE, CASE, "test", trusted_bundle_sha256=sha(raw))
    assert error.value.code == "LOCAL_CONSENT_SCOPE"


@pytest.mark.parametrize("namespace,case_id", [("demo", CASE), ("official", CASE), ("test", "test-other")])
def test_namespace_or_logical_id_cannot_be_changed(tmp_path, namespace, case_id):
    _, destination, raw, _ = fixture_bundle(tmp_path)
    with pytest.raises(CoreError) as error:
        import_case(destination, BUNDLE, case_id, namespace, trusted_bundle_sha256=sha(raw))
    assert error.value.code in {"NAMESPACE", "IMPORT_IDENTITY"}
    assert not (destination / "cases").exists()


def test_tampered_bytes_fail_trusted_hash_even_when_zip_is_well_formed(tmp_path):
    _, destination, raw, _ = fixture_bundle(tmp_path)
    altered = rewrite_archive(raw, manifest_edit=lambda manifest: manifest.update(limitations="tampered"))
    with SafeRoot(destination) as root:
        root.write(BUNDLE, altered)
    with pytest.raises(CoreError) as error:
        import_case(destination, BUNDLE, CASE, "test", trusted_bundle_sha256=sha(raw))
    assert error.value.code == "TRUSTED_BUNDLE_HASH"
    assert not (destination / ".local").exists()


def test_matching_digest_does_not_bypass_member_hash_validation(tmp_path):
    _, destination, raw, _ = fixture_bundle(tmp_path)
    altered = rewrite_archive(
        raw, member_edit=lambda files: files.update({"cases/" + CASE + "/events.jsonl": b"changed\n"})
    )
    with SafeRoot(destination) as root:
        root.write(BUNDLE, altered)
    with pytest.raises(CoreError) as error:
        import_case(destination, BUNDLE, CASE, "test", trusted_bundle_sha256=sha(altered))
    assert error.value.code == "IMPORT_HASH"
    assert not (destination / ".local").exists()


def test_local_digest_and_scoped_owner_paths_are_explicitly_distinct(tmp_path):
    source, destination, raw, _ = fixture_bundle(tmp_path)
    with pytest.raises(CoreError) as error:
        import_case(
            destination,
            BUNDLE,
            CASE,
            "test",
            authorization_project=source,
            approval="APR-001",
            trusted_bundle_sha256=sha(raw),
        )
    assert error.value.code == "TRANSFER_SCOPE"
    assert not (destination / ".local").exists()
