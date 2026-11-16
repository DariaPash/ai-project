import json

import pytest

from tools.contracts import sha
from tools.store import Store
from .helpers import FIXTURES, cli, init, record_cli, revision, write_request


@pytest.mark.parametrize(
    "args,exit_code",
    [
        ((), 2),
        (("--help",), 0),
        (("record", "--help"), 0),
        (("approval", "request", "--help"), 0),
        (("record", "--case", "test-core"), 2),
        (("doctor", "--live", "mcp"), 3),
    ],
)
def test_cli_errors_and_help_are_one_json_object(project, args, exit_code):
    _, result = cli(project, *args, expected=exit_code)
    assert result["code"] in {"HELP", "ARGUMENTS", "LIVE_UNIMPLEMENTED"}


def test_init_never_overwrites(project):
    first = init(project)
    assert first["case_revision"] == 0
    journal = project / "cases/test-core/events.jsonl"
    before = journal.read_bytes()
    init_args = ("init", "--case", "test-core", "--namespace", "test")
    cli(project, *init_args, expected=7)
    assert journal.read_bytes() == before
    cli(project, "init", "--case", "official", "--namespace", "official", expected=3)
    assert not (project / "cases/official").exists()
    cli(project, "init", "--case", "not-a-test", "--namespace", "test", expected=4)


def test_record_idempotency_and_readonly_status(project):
    init(project)
    payload = json.loads((FIXTURES / "brief.json").read_text())["payload"]
    first = record_cli(project, "brief", payload)
    second = record_cli(project, "brief", payload)
    assert second["data"]["reused"] is True
    assert first["action_id"] == second["action_id"]
    assert first["case_revision"] == second["case_revision"] == 1
    journal = project / "cases/test-core/events.jsonl"
    before = journal.read_bytes()
    _, status = cli(project, "status", "--case", "test-core")
    assert journal.read_bytes() == before
    assert status["data"]["record_count"] == 1
    assert status["data"]["telemetry"]["persisted"] is False
    cli(project, "validate", "--case", "test-core")


def test_revision_conflict_and_old_records_are_immutable(project):
    init(project)
    payload = {"goal": "First", "constraints": [], "open_questions": []}
    first = record_cli(project, "brief", payload)
    original = project / "cases/test-core/records/brief/BRF-001/1.json"
    raw = original.read_bytes()
    changed = record_cli(project, "brief", {**payload, "goal": "Second"}, entity_id="BRF-001")
    assert changed["data"]["ref"]["revision"] == 2
    assert original.read_bytes() == raw
    request = write_request(project, {"payload": {**payload, "goal": "Third"}})
    cli(
        project,
        "record",
        "--case",
        "test-core",
        "--kind",
        "brief",
        "--file",
        request,
        "--expected-revision",
        0,
        expected=7,
    )


def test_stale_known_projection_is_not_used_as_authority(project):
    init(project)
    path = project / "cases/test-core/state.json"
    value = json.loads(path.read_text())
    value["next_action"] = "Untrusted stale projection instruction"
    path.write_text(json.dumps(value))
    _, status = cli(project, "status", "--case", "test-core")
    assert status["warnings"]
    assert status["data"]["state"]["next_action"] != value["next_action"]
    cli(project, "validate", "--case", "test-core", expected=6)
    cli(
        project,
        "checkpoint",
        "--case",
        "test-core",
        "--reason",
        "rebuild stale projections",
        "--expected-revision",
        status["case_revision"],
    )
    cli(project, "validate", "--case", "test-core")


@pytest.mark.parametrize("raw", [b"broken JSON", b'{"schema_version":999}'])
def test_bad_state_stops_without_reset(project, raw):
    init(project)
    path = project / "cases/test-core/state.json"
    path.write_bytes(raw)
    cli(project, "status", "--case", "test-core", expected=6)
    cli(
        project,
        "checkpoint",
        "--case",
        "test-core",
        "--reason",
        "must not overwrite",
        "--expected-revision",
        0,
        expected=6,
    )
    assert path.read_bytes() == raw


def test_committed_record_tamper_is_not_repaired(project):
    init(project)
    record_cli(project, "brief", {"goal": "First", "constraints": [], "open_questions": []})
    path = project / "cases/test-core/records/brief/BRF-001/1.json"
    path.write_bytes(b"tampered")
    cli(project, "status", "--case", "test-core", expected=6)
    cli(project, "recover", "--case", "test-core", expected=6)
    assert path.read_bytes() == b"tampered"
