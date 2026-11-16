import copy
from io import BytesIO
import json
import zipfile

import pytest

from tools.contracts import key, sha
from tools.errors import CoreError
from tools.sources import ingest, parse_bytes, search_local, zip_preflight
from tools.store import Store
from .helpers import PROJECT, init
from .step02_helpers import SOURCES, prepare, source_spec


@pytest.mark.parametrize("name", [s["name"] for s in SOURCES["sources"]])
def test_real_parser_import_locators_and_lineage(project, name):
    prepare(project)
    init(project)
    path, spec = source_spec(name)
    with Store(project, "test-core") as store:
        result = ingest(store, path, spec, 0)
        snap, _, _ = store._load()
        records = store.records(snap)
        ext = records[key(result["data"]["extraction_ref"])]
        assert ext["payload"]["text"].strip() and ext["payload"]["fragments"]
        assert ext["lineage_roots"] == ["synthetic_fixture"]
        assert ext["payload"]["source_hash"] == sha((project / path).read_bytes())
        if name in {"policy-v1", "policy-v2"}:
            oracle = json.loads((PROJECT / "tests/fixtures/sources/oracle.json").read_text())
            expected = oracle["md" if name == "policy-v1" else "txt"]
            fragment = ext["payload"]["fragments"][expected["line"] - 1]
            assert fragment["text"] == expected["text"]
            assert fragment["coordinates"]["start"] == fragment["coordinates"]["end"] == expected["line"]
            coordinates = fragment["coordinates"]
            assert (project / path).read_text()[coordinates["char_start"] : coordinates["char_end"]] == expected["text"]
        assert (project / "cases/test-core/extracted" / ext["id"] / "manifest.json").is_file()
        if name == "pdf":
            oracle = json.loads((PROJECT / "tests/fixtures/sources/oracle.json").read_text())
            assert [f["text"].strip() for f in ext["payload"]["fragments"]] == oracle["pdf"]["pages"]
        if name == "html":
            assert "throw new Error" not in ext["payload"]["text"]
            assert ext["payload"]["coverage"]["scripts_executed"] is False
            hit = search_local(store, "Automated exports")["data"]["hits"][0]
            assert hit["locator"]["coordinates"]["id"] == "capability"
        if name == "multiline":
            bundle = json.loads(store.blob(records[key(ext["payload"]["tables_ref"])]["payload"]["sha256"]))
            row = bundle["tables"]["csv"]["rows"][0]
            assert row["coordinates"] == {"start": 2, "end": 3, "row": 1}
            assert row["values"]["note"] == "First line\nSecond line"
        assert store.validate()["warnings"] == []


def test_repeat_skips_parser_changed_bytes_revisions_and_revert(project, monkeypatch):
    prepare(project)
    init(project)
    path, spec = source_spec("policy-v1")
    with Store(project, "test-core") as store:
        first = ingest(store, path, spec, 0)
        old = (project / path).read_bytes()
        import tools.sources as sources

        original = sources.parse_snapshot
        monkeypatch.setattr(sources, "parse_snapshot", lambda *_: pytest.fail("identical import parsed again"))
        second = ingest(store, path, spec, first["case_revision"])
        assert second["data"]["reused"] and second["case_revision"] == first["case_revision"]
        monkeypatch.setattr(sources, "parse_snapshot", original)
        (project / path).write_bytes(old + b"Changed version.\n")
        changed = ingest(store, path, spec, second["case_revision"])
        assert changed["data"]["source_ref"]["entity_id"] == first["data"]["source_ref"]["entity_id"]
        assert changed["data"]["source_ref"]["revision"] == 2
        (project / path).write_bytes(old)
        reverted = ingest(store, path, spec, changed["case_revision"])
        assert reverted["data"]["source_ref"]["revision"] == 3 and not reverted["data"]["reused"]
        spec["options"]["encoding"] = "utf-8-sig"
        reparse = ingest(store, path, spec, reverted["case_revision"])
        assert reparse["data"]["source_ref"] == reverted["data"]["source_ref"]
        assert reparse["data"]["extraction_ref"] != reverted["data"]["extraction_ref"]


@pytest.mark.parametrize(
    "filename,profile,exit_code",
    [("image-only.pdf", "pdf", 3), ("corrupt.pdf", "pdf", 2), ("corrupt.xlsx", "workbook", 2)],
)
def test_negative_formats_have_no_fabricated_content(project, filename, profile, exit_code):
    prepare(project)
    init(project)
    _, spec = source_spec(profile)
    with Store(project, "test-core") as store:
        with pytest.raises(CoreError) as error:
            ingest(store, "tests/fixtures/sources/" + filename, spec, 0)
        assert error.value.exit_code == exit_code
        assert store.status()["data"]["record_count"] == 0
        assert any(row["type"] == "ERROR" for row in store.rows)


@pytest.mark.parametrize("raw", [b"a,a\n1,2\n", b"a,b\n1,2,3\n", b'a,b\n1,"unclosed\n'])
def test_bad_csv_is_rejected(raw):
    from tools.sources import parse_snapshot

    _, spec = source_spec("multiline")
    spec["options"]["expected_columns"] = []
    with pytest.raises(CoreError) as error:
        parse_snapshot(raw, spec)
    assert error.value.exit_code == 2


@pytest.mark.parametrize("kind", ["traversal", "symlink", "ratio", "entity", "external", "duplicates"])
def test_archive_security_preflight(kind):
    _, spec = source_spec("workbook")
    out = BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        name = "../escape.xml" if kind == "traversal" else "sheet.xml"
        info = zipfile.ZipInfo(name)
        info.compress_type = zipfile.ZIP_DEFLATED
        if kind == "symlink":
            info.external_attr = 0o120777 << 16
        raw = (
            b"x" * 100000
            if kind == "ratio"
            else b'<!DOCTYPE x [<!ENTITY x SYSTEM "file:///canary">]>'
            if kind == "entity"
            else b"<x/>"
        )
        if kind == "external":
            info.filename = "xl/externalLinks/link.xml"
        archive.writestr(info, raw)
        if kind == "duplicates":
            with pytest.warns(UserWarning):
                archive.writestr(info, b"duplicate")
    with pytest.raises(CoreError) as error:
        zip_preflight(out.getvalue(), spec["limits"])
    assert error.value.exit_code == 4


def test_input_caps_empty_rights_and_encoding(project):
    prepare(project)
    init(project)
    path, spec = source_spec("policy-v1")
    with Store(project, "test-core") as store:
        spec["rights"]["processing"] = False
        with pytest.raises(CoreError) as error:
            ingest(store, path, spec, 0)
        assert error.value.exit_code == 4
        spec["rights"]["processing"] = True
        spec["limits"]["max_bytes"] = 1
        with pytest.raises(CoreError) as error:
            ingest(store, path, spec, 0)
        assert error.value.exit_code == 4
    _, spec = source_spec("policy-v1")
    from tools.sources import parse_snapshot

    for raw, code in [(b"", 3), (b"\xff", 2)]:
        with pytest.raises(CoreError) as error:
            parse_snapshot(raw, spec)
        assert error.value.exit_code == code


def test_snapshot_not_reopened_after_source_changes(project, monkeypatch):
    import tools.sources as module

    prepare(project)
    init(project)
    path, spec = source_spec("policy-v1")
    original = (project / path).read_bytes()
    parser = module.parse_snapshot

    def changed(raw, profile):
        (project / path).write_bytes(b"Changed after descriptor snapshot.\n")
        return parser(raw, profile)

    monkeypatch.setattr(module, "parse_snapshot", changed)
    with Store(project, "test-core") as store:
        saved = ingest(store, path, spec, 0)
        assert saved["data"]["source_sha256"] == sha(original)
        assert store.blob(sha(original)) == original


def test_parser_timeout_kills_one_attempt_and_journals_error(project, monkeypatch):
    import subprocess
    import tools.sources as module

    prepare(project)
    init(project)
    path, spec = source_spec("policy-v1")
    killed = []
    launched = []

    class Process:
        def communicate(self, *_args, **kwargs):
            if kwargs.get("timeout"):
                raise subprocess.TimeoutExpired("test-parser", 1)
            return b"", b""

        def kill(self):
            killed.append(True)

    def launch(*args, **kwargs):
        launched.append(args)
        return Process()

    monkeypatch.setattr(module.subprocess, "Popen", launch)
    with Store(project, "test-core") as store:
        with pytest.raises(CoreError) as error:
            ingest(store, path, spec, 0)
        assert error.value.exit_code == 5 and len(killed) == len(launched) == 1
        assert store.status()["data"]["record_count"] == 0
        assert store.rows[-1]["code"] == "PARSER_TIMEOUT"
