import json

import pytest

from .helpers import FIXTURES, cli, init, record_cli, revision, write_request


@pytest.mark.parametrize("point", ["before_prepare", "after_prepare", "after_commit", "during_projection"])
def test_real_process_crash_boundaries(project, point):
    oracle = json.loads((FIXTURES / "oracle.json").read_text())["accepted_content_records"]
    init(project)
    request = write_request(project, json.loads((FIXTURES / "brief.json").read_text()))
    process, _ = cli(
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
        expected=97,
        env={"STRATEGIST_TEST_MODE": "1", "STRATEGIST_TEST_FAILPOINT": point},
    )
    assert process.returncode == 97
    _, status = cli(project, "status", "--case", "test-core")
    assert status["data"]["record_count"] == oracle[point]
    if oracle[point]:
        assert status["case_revision"] == 1
        assert status["warnings"]
    else:
        assert status["case_revision"] == 0
        # Aborted IDs are not handed to a different later record.
        result = record_cli(
            project, "brief", {"goal": "Retry after an aborted write", "constraints": [], "open_questions": []}
        )
        assert result["data"]["ref"]["entity_id"] == "BRF-002"
    cli(
        project,
        "checkpoint",
        "--case",
        "test-core",
        "--reason",
        "recover projections",
        "--expected-revision",
        revision(project),
    )
    cli(project, "validate", "--case", "test-core")


def test_torn_tail_diagnose_then_explicit_quarantine(project):
    init(project)
    path = project / "cases/test-core/events.jsonl"
    complete = path.read_bytes()
    tail = b'{"unfinished":'
    path.write_bytes(complete + tail)
    cli(project, "status", "--case", "test-core", expected=6)
    _, diagnosis = cli(project, "recover", "--case", "test-core")
    assert diagnosis["data"]["tail_bytes"] == len(tail)
    assert path.read_bytes() == complete + tail
    _, repaired = cli(
        project, "recover", "--case", "test-core", "--repair-tail", "--expected-revision", diagnosis["case_revision"]
    )
    assert (project / repaired["data"]["tail_saved"]).read_bytes() == tail
    cli(project, "validate", "--case", "test-core")
    cli(
        project,
        "recover",
        "--case",
        "test-core",
        "--repair-tail",
        "--expected-revision",
        diagnosis["case_revision"],
        expected=2,
    )


def test_middle_corruption_and_newline_terminated_garbage_are_not_tail_repair(project):
    init(project)
    path = project / "cases/test-core/events.jsonl"
    raw = path.read_bytes()
    lines = raw.splitlines(keepends=True)
    corrupted = lines[0] + b"not JSON\n" + b"".join(lines[1:])
    path.write_bytes(corrupted)
    cli(project, "recover", "--case", "test-core", "--repair-tail", "--expected-revision", 0, expected=6)
    assert path.read_bytes() == corrupted
    path.write_bytes(raw + b"not JSON\n")
    cli(project, "recover", "--case", "test-core", expected=6)
    assert path.read_bytes() == raw + b"not JSON\n"
