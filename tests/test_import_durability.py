"""IR03: bounded post-rename fsync fault, temporary fixture roots only."""

import os

import pytest

from tools.contracts import sha
from tools.errors import CoreError
from tools.safeio import SafeRoot
from tools.store import Store
from tools.transfer import import_case
from .test_portable_transfer import BUNDLE, CASE, fixture_bundle


def test_post_rename_fsync_failure_requires_read_only_reconciliation(tmp_path, monkeypatch):
    _, destination, raw, _ = fixture_bundle(tmp_path)
    original = SafeRoot.promote_directory

    def promote(self, source, target):
        def fail(fd):
            raise OSError("injected post-rename durability failure")

        with monkeypatch.context() as patch:
            patch.setattr(os, "fsync", fail)
            return original(self, source, target)

    monkeypatch.setattr(SafeRoot, "promote_directory", promote)
    with pytest.raises(CoreError) as caught:
        import_case(destination, BUNDLE, CASE, "test", trusted_bundle_sha256=sha(raw))
    error = caught.value
    assert error.code == "DIRECTORY_DURABILITY_UNKNOWN"
    assert error.data["target"] == "cases/" + CASE
    assert error.data["archive_sha256"] == sha(raw)
    assert (destination / error.data["staging"]).is_dir()
    assert (destination / error.data["local_consent_receipt"]).is_file()
    assert "do not retry" in error.next_action and "read-only" in error.next_action
    assert error.saved
    with Store(destination, CASE) as store:
        snapshot, warnings, _ = store._load()
        from tools.contracts import digest

        assert not warnings
        assert digest(snapshot) == error.data["snapshot_digest"]
