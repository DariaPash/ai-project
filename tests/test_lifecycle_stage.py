import pytest

from tools import store as module
from tools.store import Store, lifecycle_stage


@pytest.mark.parametrize(
    "kinds,pending,status,revision,expected",
    [
        ([], None, None, 1, "brief"),
        (["research_plan"], None, None, 1, "research_plan"),
        (["research_plan", "claim"], None, None, 1, "research"),
        (["option"], "option_choice", None, 1, "options"),
        (["option", "strategy", "promise"], None, None, 1, "strategy"),
        (["decision"], "final_decision", "pending", 1, "decision"),
        (["decision"], "reconsideration", "pending", 2, "reconsideration"),
        (["decision"], None, "review_required", 2, "reconsideration"),
        (["decision"], None, "confirmed", 2, "follow_up"),
    ],
)
def test_semantic_stages(kinds, pending, status, revision, expected):
    records = {
        f"R{i}@{revision}": {"kind": kind, "revision": revision, "payload": {"status": status}}
        for i, kind in enumerate(kinds)
    }
    snapshot = {
        "active": {f"R{i}": revision for i in range(len(kinds))},
        "runtime": {"stage": "brief", "awaiting_human": pending},
    }
    assert lifecycle_stage(snapshot, records) == expected
    assert snapshot["runtime"] == {"stage": "brief", "awaiting_human": pending}


OPTION = {
    "option_type": "improve",
    "mechanism": "Local review",
    "audience": "Fixture",
    "basis_refs": [],
    "strongest_objection": "No demand evidence",
    "minimal_test": "Observe with consent",
}


def test_commit_updates_stage_without_confirming_human(project):
    with Store(project, "test-stage") as store:
        store.init("test")
        assert store.status()["data"]["state"]["stage"] == "brief"
        store.record("option", {"payload": OPTION}, 0)
        assert store.status()["data"]["state"]["stage"] == "options"
        store.record(
            "strategy", {"payload": {"strategy_type": "product", "text": "Fixture proposal", "basis_refs": []}}, 1
        )
        assert store.status()["data"]["state"]["stage"] == "strategy"
        store.record("action", {"payload": {"operation": "note", "runtime": {"awaiting_human": "reconsideration"}}}, 2)
        state = store.status()["data"]["state"]
        assert state["stage"] == "reconsideration" and state["awaiting_human"] == "reconsideration"


def test_legacy_snapshot_projection_readonly_and_next_checkpoint(project, monkeypatch):
    with Store(project, "test-stage") as store:
        store.init("test")
        with monkeypatch.context() as patch:
            patch.setattr(module, "lifecycle_stage", lambda *unused: "brief")
            store.record("option", {"payload": OPTION}, 0)
        base = project / "cases/test-stage"
        old_snapshots = {p: p.read_bytes() for p in (base / "journal").rglob("snapshot.json")}
        projections = {p: p.read_bytes() for p in (base / "state.json", base / "handoff.md", base / "events.jsonl")}
        status = store.status()
        assert status["data"]["state"]["stage"] == "brief" and status["warnings"] == []
        store.validate()
        assert all(p.read_bytes() == raw for p, raw in projections.items())
        store.checkpoint("legitimate next checkpoint", 1)
        assert store.status()["data"]["state"]["stage"] == "options"
        assert all(p.read_bytes() == raw for p, raw in old_snapshots.items())
        store.validate()


def test_plan_stage_on_actual_commit(project):
    with Store(project, "test-plan") as store:
        store.init("test")
        question = store.record(
            "question",
            {
                "payload": {
                    "contract_version": 3,
                    "text": "Which observation changes the direction?",
                    "affected_choice": "Improve versus close",
                    "priority": "high",
                    "minimal_evidence": "A consented observation",
                    "stop_condition": "No permission",
                    "outcome": {"status": "gap", "text": "No real evidence", "basis_refs": []},
                }
            },
            0,
        )["data"]["ref"]
        store.record(
            "research_plan",
            {
                "payload": {
                    "contract_version": 3,
                    "decision_question": "What should be validated?",
                    "question_refs": [question],
                    "criteria": {"scale": "0-4", "weights": {"risk": 1}, "sensitivity_weights": [{"risk": 1}]},
                    "limitations": ["Technical fixture only"],
                }
            },
            1,
        )
        assert store.status()["data"]["state"]["stage"] == "research_plan"


def test_second_pending_revision_is_not_necessarily_reconsideration():
    records = {
        "DEC-001@1": {"id": "DEC-001", "kind": "decision", "revision": 1, "payload": {"status": "proposed"}},
        "DEC-001@2": {"id": "DEC-001", "kind": "decision", "revision": 2, "payload": {"status": "pending"}},
    }
    snapshot = {"active": {"DEC-001": 2}, "runtime": {"awaiting_human": None}}
    assert lifecycle_stage(snapshot, records) == "decision"
