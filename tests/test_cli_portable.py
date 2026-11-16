"""Production CLI wiring; temporary synthetic stores only."""

import pytest

from tools.cli import dispatch, parser
from tools.contracts import sha
from tools.errors import CoreError
from tools.store import Store
from .test_portable_transfer import BUNDLE, CASE, fixture_bundle


def arguments(digest=None):
    args = ["import-case", "--case", CASE, "--namespace", "test", "--bundle", BUNDLE]
    if digest is not None:
        args += ["--trusted-bundle-sha256", digest]
    return parser().parse_args(args)


def test_cli_restores_independent_synthetic_bundle(tmp_path):
    _, destination, raw, exported = fixture_bundle(tmp_path)
    result = dispatch(destination, arguments(sha(raw)))
    assert result["case_revision"] == exported["case_revision"]
    with Store(destination, CASE) as store:
        assert store.status()["case_revision"] == exported["case_revision"]


@pytest.mark.parametrize("digest,code", [(None, "TRANSFER_DENIED"), ("0" * 64, "TRUSTED_BUNDLE_HASH")])
def test_cli_does_not_implicitly_trust_zip(tmp_path, digest, code):
    _, destination, _, _ = fixture_bundle(tmp_path)
    with pytest.raises(CoreError) as error:
        dispatch(destination, arguments(digest))
    assert error.value.code == code
    assert not (destination / "cases" / CASE).exists()
