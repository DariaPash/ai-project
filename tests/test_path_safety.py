import os

import pytest

from tools.errors import CoreError
from tools.safeio import SafeRoot
from tools.sources import ingest
from tools.store import Store
from .helpers import init
from .step02_helpers import prepare, source_spec


@pytest.mark.parametrize("path", ["../outside", "/etc/passwd", ".env", "cases/test-other/input/file.txt"])
def test_ingest_unapproved_paths(project, path):
    init(project)
    _, spec = source_spec("policy-v1")
    with Store(project, "test-core") as store:
        with pytest.raises(CoreError) as error:
            ingest(store, path, spec, 0)
        assert error.value.exit_code == 4


def test_symlink_hardlink_and_parent_swap_cannot_redirect_reads(project, tmp_path, monkeypatch):
    prepare(project)
    init(project)
    path, spec = source_spec("policy-v1")
    canary = tmp_path / "canary.txt"
    canary.write_text("safe-canary-not-a-real-secret")
    (project / "tests/fixtures/sources/link.txt").symlink_to(canary)
    os.link(canary, project / "tests/fixtures/sources/hard.txt")
    with Store(project, "test-core") as store:
        for filename in ("link.txt", "hard.txt"):
            with pytest.raises(CoreError) as error:
                ingest(store, "tests/fixtures/sources/" + filename, spec, 0)
            assert error.value.exit_code == 4
    # Swap the parent name AFTER directory fd acquisition. The fd still selects
    # the original directory, never the new symlink target.
    original_open = os.open
    swapped = []

    def racing_open(name, flags, *args, **kwargs):
        fd = original_open(name, flags, *args, **kwargs)
        if name == "sources" and not swapped:
            swapped.append(True)
            (project / "tests/fixtures/sources").rename(project / "tests/fixtures/sources-old")
            (project / "tests/fixtures/sources").symlink_to(tmp_path, target_is_directory=True)
        return fd

    monkeypatch.setattr(os, "open", racing_open)
    with SafeRoot(project) as root:
        raw = root.read(path)
    assert b"Technical activation policy" in raw and b"safe-canary" not in raw
