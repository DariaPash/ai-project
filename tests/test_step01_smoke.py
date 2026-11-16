import json

from .helpers import FIXTURES, PROJECT, cli, init, record_cli, revision


def test_full_core_smoke_uses_frozen_spec_and_oracle(project):
    spec = json.loads((PROJECT / "tests/specs/01-core.json").read_text())
    oracle = json.loads((PROJECT / spec["oracle"]).read_text())
    assert spec["smoke_sequence"] == ["init", "record brief", "record action", "checkpoint", "status", "validate"]
    init(project)
    brief = json.loads((FIXTURES / "brief.json").read_text())["payload"]
    action = json.loads((FIXTURES / "action.json").read_text())["payload"]
    record_cli(project, "brief", brief)
    record_cli(project, "action", action)
    cli(
        project,
        "checkpoint",
        "--case",
        "test-core",
        "--reason",
        "pause core smoke",
        "--expected-revision",
        revision(project),
    )
    _, status = cli(project, "status", "--case", "test-core")
    assert status["data"]["state"]["stage"] == oracle["resume"]["stage"]
    assert status["data"]["state"]["next_action"] == oracle["resume"]["next_action"]
    assert list(status["data"]["active"]).count("BRF-001") == oracle["resume"]["brief_count"]
    assert status["data"]["state"]["awaiting_human"]
    assert oracle["resume"]["next_action"] in (project / "cases/test-core/handoff.md").read_text()
    usage = [json.loads(line) for line in (project / "cases/test-core/usage.jsonl").read_text().splitlines()]
    assert len(usage) == status["data"]["action_count"]
    assert all(row["action_id"].startswith("ACT-") and row["usage"]["money"]["amount"] is None for row in usage)
    cli(project, "validate", "--case", "test-core")
    # A new subprocess is a real CLI invocation, NOT a new LLM session.
    _, restored = cli(project, "status", "--case", "test-core")
    assert restored["data"]["snapshot_digest"] == status["data"]["snapshot_digest"]
