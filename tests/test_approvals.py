import copy
import pytest
from tools.contracts import business_digest, key, target_digest
from tools.errors import CoreError
from .step03_helpers import build_research, add_options, complete_fixture


@pytest.fixture
def proposed(project):
    return add_options(build_research(project, quantitative=False))


@pytest.mark.parametrize("defect", ["empty", "missing", "outside", "kind", "legacy"])
def test_exact_option_bundle(proposed, defect):
    f = proposed
    terms = copy.deepcopy(f.choice_terms)
    targets = copy.deepcopy(f.choice_targets)
    if defect == "empty":
        targets = []
    if defect == "missing":
        targets.pop(0)
    if defect == "outside":
        terms["selected_option_ref"] = f.analysis
    if defect == "kind":
        targets[0] = f.analysis
    if defect == "legacy":
        targets = []
        terms = {}
    with pytest.raises(CoreError) as error:
        f.approve("option_choice", targets, terms)
    assert error.value.code == ("OPTION_CHOICE_REQUIRED" if defect == "legacy" else "OPTION_BUNDLE")


@pytest.mark.parametrize("response", ["reject", "revise"])
def test_rejected_or_revised_is_not_approval(proposed, response):
    f = proposed
    receipt = f.approve("option_choice", f.choice_targets, f.choice_terms, status=response)
    with pytest.raises(CoreError) as error:
        f.strategy(
            "product",
            f.options[1],
            receipt,
            [],
            {
                k: "fixture"
                for k in [
                    "segment_job",
                    "alternatives",
                    "choice_refusals",
                    "value_economics",
                    "dependencies",
                    "next_experiment",
                ]
            },
        )
    assert error.value.code == "OPTION_CHOICE_REQUIRED"


def test_changed_plan_invalidates_receipt(proposed):
    f = proposed
    p = {
        "scope": "option_choice",
        "targets": f.choice_targets,
        "terms": f.choice_terms,
        "question": "Fixture?",
        "status": "requested",
        "target_digest": target_digest("option_choice", f.choice_targets, f.records(), f.choice_terms),
    }
    request = f.record("approval", p)
    plan = copy.deepcopy(f.records()[key(f.plan)]["payload"])
    plan["criteria"]["scale"] += " changed"
    f.record("research_plan", plan, f.plan["entity_id"])
    with pytest.raises(CoreError) as error:
        f.record(
            "approval",
            {
                **p,
                "status": "approve",
                "request_ref": request,
                "approval_kind": "fixture",
                "actor": "fixture",
                "channel": "fixture",
                "timestamp": "2026-11-08T00:00:00Z",
                "evidence_ref": f.artifact(b"fixture", media="text/plain"),
            },
        )
    assert error.value.code == "APPROVAL_STALE"


def test_two_h_stages_and_exact_business_digest(proposed):
    f = complete_fixture(proposed)
    assert f.final != f.choice and f.confirmed["revision"] == 2
    for field, value in [
        ("owner", "invented owner"),
        ("metrics", ["new metric"]),
        ("strategy_refs", [f.communication, f.product]),
    ]:
        p = {
            **f.decision_payload,
            "status": "confirmed",
            "approved_proposal_ref": f.proposal,
            "approval_ref": f.final,
            "business_content_digest": business_digest(f.decision_payload),
            field: value,
        }
        with pytest.raises(CoreError) as error:
            f.record("decision", p, f.proposal["entity_id"])
        assert error.value.code == "DECISION_CHANGED"
    with pytest.raises(CoreError) as error:
        f.record("decision", {**f.decision_payload, "status": "confirmed"}, f.proposal["entity_id"])
    assert error.value.code == "HUMAN_REQUIRED"
