import copy

import pytest

from tools.contracts import business_digest
from tools.errors import CoreError
from tools.store import Store
from .helpers import add, approval, artifact, init


def decision_fixture(project):
    options = []
    for option_type in ("status_quo", "improve", "refocus", "close"):
        options.append(
            add(
                project,
                "option",
                {
                    "option_type": option_type,
                    "mechanism": "Technical contract fixture: " + option_type,
                    "audience": "Artificial",
                    "basis_refs": [],
                    "strongest_objection": "No real evidence",
                    "minimal_test": "Obtain real data",
                },
            )
        )
    strategies = [
        add(
            project,
            "strategy",
            {"strategy_type": kind, "text": "Not a real strategy; contract fixture", "basis_refs": [options[1]]},
        )
        for kind in ("product", "communication")
    ]
    experiment = add(
        project,
        "experiment",
        {
            "hypothesis": "Technical fixture",
            "baseline": None,
            "metric": "unknown",
            "comparison": "Not yet designed",
            "horizon": "unknown",
            "guardrails": [],
            "limitations": ["Synthetic"],
        },
    )
    payload = {
        "status": "pending",
        "selected_option_ref": options[1],
        "rejected_refs": [options[i] for i in (0, 2, 3)],
        "basis_refs": [],
        "strategy_refs": strategies,
        "experiment_ref": experiment,
        "owner": "unassigned",
        "due": "unknown",
        "metrics": ["unknown"],
        "triggers": ["Real evidence arrives"],
    }
    return add(project, "decision", payload), payload


def test_fixture_confirmation_has_no_circular_approval_digest(project):
    init(project)
    proposal, payload = decision_fixture(project)
    apr = approval(project, "final_decision", targets=[proposal])
    confirmed = {
        **payload,
        "status": "confirmed",
        "approved_proposal_ref": proposal,
        "approval_ref": apr,
        "business_content_digest": business_digest(payload),
    }
    result = add(project, "decision", confirmed, entity_id=proposal["entity_id"])
    assert result["revision"] == 2
    with Store(project, "test-core") as store:
        assert store.validate()["data"]["validation"] == "structural_only"
    changed = {**confirmed, "owner": "invented_new_owner"}
    with pytest.raises(CoreError) as exc:
        add(project, "decision", changed, entity_id=proposal["entity_id"])
    assert exc.value.code == "DECISION_CHANGED"


def test_missing_confirmation_and_wrong_reference_kind_fail(project):
    init(project)
    proposal, payload = decision_fixture(project)
    with pytest.raises(CoreError) as exc:
        add(project, "decision", {**payload, "status": "confirmed"}, entity_id=proposal["entity_id"])
    assert exc.value.code == "HUMAN_REQUIRED"
    bad = {**payload, "selected_option_ref": payload["experiment_ref"]}
    with pytest.raises(CoreError) as exc:
        add(project, "decision", bad)
    assert exc.value.code == "DECISION_REF_KIND"


def test_relabeling_synthetic_receipt_as_real_is_blocked(project):
    init(project)
    with pytest.raises(CoreError) as exc:
        approval(project, "source_access", approval_kind="real")
    assert exc.value.code == "SYNTHETIC_APPROVAL"


def test_a_request_cannot_receive_conflicting_responses(project):
    init(project)
    apr = approval(project, "source_access")
    with Store(project, "test-core") as store:
        snapshot, _, _ = store._load()
        payload = copy.deepcopy(store.records(snapshot)[f"{apr['entity_id']}@1"]["payload"])
    payload["status"] = "reject"
    with pytest.raises(CoreError) as exc:
        add(project, "approval", payload)
    assert exc.value.code == "APPROVAL_ANSWERED"
