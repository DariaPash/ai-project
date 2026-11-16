import json

import pytest

from tools.errors import CoreError
from tools.store import Store, unknown_usage
from .helpers import FIXTURES, add, artifact, init, permission, record_cli


def reserve(permission_ref, operation_key="test-operation", **updates):
    return {
        "operation": "reserve",
        "operation_key": operation_key,
        "permission_ref": permission_ref,
        "external": False,
        "adapter": "offline-test-double",
        "estimated_money": None,
        **updates,
    }


def test_count_reservation_is_committed_and_exhaustion_checkpoints(project):
    oracle = json.loads((FIXTURES / "oracle.json").read_text())["budget"]
    init(project)
    allowed = permission(project)
    first = record_cli(project, "action", reserve(allowed))
    attempt_id = first["data"]["reserved_attempt_id"]
    blocked = record_cli(
        project, "action", reserve(allowed, "different-operation"), expected=oracle["second_distinct_operation_exit"]
    )
    assert blocked["code"] == "BUDGET_EXHAUSTED"
    with Store(project, "test-core") as store:
        status = store.status()
        attempts = status["data"]["attempts"]
        assert list(attempts) == [attempt_id]
        assert attempts[attempt_id]["status"] == oracle["first_reservation"]
        assert attempts[attempt_id]["usage"]["money"]["amount"] is oracle["unknown_money_amount"]
        assert status["data"]["state"]["awaiting_human"]
        snapshot, _, _ = store._load()
        assert list(snapshot["actions"].values())[-1]["status"] == "blocked"
        assert list(snapshot["actions"])[-1] not in snapshot["runtime"]["completed_actions"]


def test_unknown_outcome_never_auto_repeats_or_becomes_zero(project):
    init(project)
    allowed = permission(project, calls=2)
    first = record_cli(project, "action", reserve(allowed))
    attempt = first["data"]["reserved_attempt_id"]
    record_cli(
        project,
        "action",
        {"operation": "settle", "attempt_id": attempt, "status": "outcome_unknown", "usage": unknown_usage()},
    )
    blocked = record_cli(project, "action", reserve(allowed), expected=3)
    assert blocked["code"] == "OUTCOME_UNKNOWN"
    record_cli(
        project,
        "action",
        {"operation": "reconcile", "attempt_id": attempt, "status": "succeeded", "usage": unknown_usage()},
        expected=3,
    )
    evidence = artifact(project, b"Test-only provider receipt, not a real external call")
    record_cli(
        project,
        "action",
        {
            "operation": "reconcile",
            "attempt_id": attempt,
            "status": "succeeded",
            "usage": unknown_usage(),
            "provider_request_id": "fixture-receipt",
            "evidence_ref": evidence,
        },
    )
    result = record_cli(project, "action", reserve(allowed), expected=3)
    assert result["code"] == "ATTEMPT_FINISHED"


def test_pending_attempt_is_not_a_license_to_repeat(project):
    init(project)
    allowed = permission(project, calls=3)
    record_cli(project, "action", reserve(allowed))
    result = record_cli(project, "action", reserve(allowed), expected=3)
    assert result["code"] == "ATTEMPT_PENDING"


def test_fixture_approval_cannot_authorize_external_call(project):
    init(project)
    allowed = permission(project)
    record_cli(project, "action", reserve(allowed, external=True), expected=4)
    with Store(project, "test-core") as store:
        assert not store.status()["data"]["attempts"]


def test_unknown_money_cannot_pass_strict_money_cap(project):
    init(project)
    allowed = permission(project, money_limit=10, allow_unknown=False)
    result = record_cli(project, "action", reserve(allowed), expected=3)
    assert result["code"] == "BUDGET_EXHAUSTED"


def test_settled_adapter_usage_is_projected_once(project):
    init(project)
    allowed = permission(project)
    first = record_cli(project, "action", reserve(allowed))
    attempt = first["data"]["reserved_attempt_id"]
    usage = unknown_usage()
    usage["money"] = {"amount": 0.25, "currency": "RUB", "basis": "estimated"}
    record_cli(project, "action", {"operation": "settle", "attempt_id": attempt, "status": "failed", "usage": usage})
    rows = [json.loads(line) for line in (project / "cases/test-core/usage.jsonl").read_text().splitlines()]
    adapter_rows = [row for row in rows if row.get("entry_kind") == "adapter_attempt"]
    assert len(adapter_rows) == 1
    assert adapter_rows[0]["attempt_id"] == attempt
    assert adapter_rows[0]["usage"]["money"] == usage["money"]
    assert adapter_rows[0]["status"] == "failed"


def test_unknown_cost_cannot_be_written_as_zero(project):
    init(project)
    allowed = permission(project)
    attempt = record_cli(project, "action", reserve(allowed))["data"]["reserved_attempt_id"]
    usage = unknown_usage()
    usage["money"]["amount"] = 0
    result = record_cli(
        project,
        "action",
        {"operation": "settle", "attempt_id": attempt, "status": "failed", "usage": usage},
        expected=2,
    )
    assert result["code"] == "UNKNOWN_COST"
    with Store(project, "test-core") as store:
        assert store.status()["data"]["attempts"][attempt]["status"] == "reserved"


def test_strict_money_currency_must_match(project):
    from .helpers import approval

    init(project)
    terms = {
        "scope": "development_resource",
        "call_limit": 2,
        "external_allowed": False,
        "money_limit": 10,
        "currency": "RUB",
        "allow_unknown_money": False,
    }
    apr = approval(project, "development_resource", terms=terms)
    allowed = add(project, "permission", {**terms, "approval_ref": apr})
    bad = record_cli(project, "action", reserve(allowed, estimated_money=1, estimated_currency="USD"), expected=3)
    assert bad["code"] == "CURRENCY_REQUIRED"
    first = record_cli(project, "action", reserve(allowed, estimated_money=1, estimated_currency="RUB"))
    usage = unknown_usage()
    usage["money"] = {"amount": 1, "currency": "USD", "basis": "actual"}
    result = record_cli(
        project,
        "action",
        {"operation": "settle", "attempt_id": first["data"]["reserved_attempt_id"], "status": "failed", "usage": usage},
        expected=2,
    )
    assert result["code"] == "CURRENCY_MISMATCH"


def test_cloned_permission_does_not_reset_approval_quota(project):
    init(project)
    allowed = permission(project)
    record_cli(project, "action", reserve(allowed))
    with Store(project, "test-core") as store:
        snapshot, _, _ = store._load()
        original = store.records(snapshot)[f"{allowed['entity_id']}@1"]["payload"]
        clone = store.record(
            "permission", {"payload": original, "created_by": "different_metadata_label"}, snapshot["case_revision"]
        )["data"]["ref"]
    assert clone != allowed
    result = record_cli(project, "action", reserve(clone, "new-operation-with-cloned-permission"), expected=3)
    assert result["code"] == "BUDGET_EXHAUSTED"
