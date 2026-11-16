import json
import os
from pathlib import Path
import socket

import pytest

from tools.cli import main
from tools.contracts import target_digest
from tools.errors import CoreError
from tools.safeio import SafeRoot, parse_json
from tools.store import Store
from .helpers import FIXTURES, add, approval, artifact, cli, init, record_cli, write_request


@pytest.mark.parametrize("value", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}'])
def test_ambiguous_json_is_rejected(value):
    with pytest.raises(CoreError):
        parse_json(value)


def test_input_roots_symlinks_and_special_files(project, tmp_path):
    init(project)
    outside = tmp_path / "outside.json"
    outside.write_text('{"payload":{"operation":"note"}}')
    root = project / "cases/test-core/requests"
    root.mkdir()
    (root / "link.json").symlink_to(outside)
    for name in (
        "cases/test-core/requests/link.json",
        "../outside.json",
        str(outside),
        "cases/test-other/input/file.json",
        ".env",
    ):
        cli(
            project,
            "record",
            "--case",
            "test-core",
            "--kind",
            "action",
            "--file",
            name,
            "--expected-revision",
            0,
            expected=4,
        )
    fifo = root / "fifo"
    os.mkfifo(fifo)
    with SafeRoot(project) as safe:
        with pytest.raises(CoreError):
            safe.read("cases/test-core/requests/fifo")
    assert outside.read_text() == '{"payload":{"operation":"note"}}'


def test_directory_descriptor_cannot_be_redirected_after_open(project, tmp_path):
    original = project / "input"
    original.mkdir()
    (original / "file.txt").write_text("safe")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "file.txt").write_text("wrong")
    with SafeRoot(project) as safe:
        with safe.directory(("input",)) as directory:
            original.rename(project / "moved")
            original.symlink_to(outside, target_is_directory=True)
            fd = os.open("file.txt", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            try:
                assert os.read(fd, 100) == b"safe"
            finally:
                os.close(fd)
        with pytest.raises(CoreError):
            safe.read("input/file.txt")


def test_fixture_approval_denied_in_demo_and_terms_cannot_expand(project):
    config = project / "config/gates.json"
    gates = json.loads(config.read_text())
    gates["gates"]["D"].update(status="confirmed", evidence=["TEST-ONLY scenario setup; not real project approval"])
    config.write_text(json.dumps(gates))
    cli(project, "init", "--case", "demo", "--namespace", "demo")
    with pytest.raises(CoreError) as exc:
        approval(project, "source_access", case="demo")
    assert exc.value.code == "FIXTURE_APPROVAL"
    init(project)
    terms = {
        "scope": "development_resource",
        "call_limit": 1,
        "external_allowed": False,
        "money_limit": None,
        "allow_unknown_money": True,
    }
    apr = approval(project, "development_resource", terms=terms)
    with pytest.raises(CoreError) as exc:
        add(project, "permission", {**terms, "call_limit": 999, "approval_ref": apr})
    assert exc.value.code == "PERMISSION_APPROVAL"


def test_untrusted_text_stays_data_no_dynamic_execution_or_network(project, monkeypatch, capsys):
    init(project)
    before = (project / "config/budget.json").read_bytes()
    text = (FIXTURES / "injection.txt").read_text()
    request = write_request(project, {"payload": {"operation": "note", "note": text}})
    calls = []

    def denied(*args, **kwargs):
        calls.append(True)
        raise AssertionError("Core must not perform egress")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.chdir(project)
    assert (
        main(["record", "--case", "test-core", "--kind", "action", "--file", request, "--expected-revision", "0"]) == 0
    )
    assert json.loads(capsys.readouterr().out)["ok"]
    assert calls == []
    assert (project / "config/budget.json").read_bytes() == before
    assert not (project / "private").exists()


def test_error_diagnostics_do_not_echo_untrusted_values(project):
    init(project)
    request = write_request(project, {"payload": {"operation": "DO-NOT-LOG-THIS-SECRET"}})
    process, result = cli(
        project,
        "record",
        "--case",
        "test-core",
        "--kind",
        "action",
        "--file",
        request,
        "--expected-revision",
        0,
        expected=2,
    )
    assert "DO-NOT-LOG-THIS-SECRET" not in process.stdout + process.stderr
    assert "DO-NOT-LOG-THIS-SECRET" not in (project / "cases/test-core/events.jsonl").read_text()


def test_fault_switch_cannot_enable_production_failpoints(project):
    config = project / "config/gates.json"
    gates = json.loads(config.read_text())
    gates["gates"]["D"].update(status="confirmed", evidence=["Test-only setup"])
    config.write_text(json.dumps(gates))
    cli(project, "init", "--case", "demo", "--namespace", "demo")
    request = write_request(project, {"payload": {"operation": "note"}}, case="demo")
    cli(
        project,
        "record",
        "--case",
        "demo",
        "--kind",
        "action",
        "--file",
        request,
        "--expected-revision",
        0,
        expected=4,
        env={"STRATEGIST_TEST_MODE": "1", "STRATEGIST_TEST_FAILPOINT": "after_commit"},
    )


def test_cli_transient_error_envelope_mapping(project, monkeypatch, capsys):
    import tools.cli as entry

    def test_only_adapter_error(*args):
        raise CoreError("TRANSIENT_TIMEOUT", "Injected adapter timeout; no real service called", 5)

    monkeypatch.setattr(entry, "dispatch", test_only_adapter_error)
    assert entry.main(["doctor"]) == 5
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["code"] == "TRANSIENT_TIMEOUT"
    assert envelope["ok"] is False
