import copy
import pytest
from tools.contracts import key
from tools.errors import CoreError
from .step03_helpers import build_research, add_options, complete_fixture


def test_model_lineage_to_both_strategies_and_decision(project):
    f = complete_fixture(add_options(build_research(project, quantitative=False)))
    records = f.records()
    for r in [*f.simulations, *f.options, f.product, f.communication, f.confirmed]:
        assert {"model_simulation", "synthetic_fixture"} <= set(records[key(r)]["lineage_roots"])
    with pytest.raises(CoreError) as error:
        f.record(
            "claim",
            {
                "text": "Demand proven by three model roles",
                "type": "fact",
                "status": "supported",
                "support_scope": "real_world",
                "support_review": "not empirical",
                "origin": "public_source",
                "basis_refs": f.simulations,
                "evidence": [f.quote("capabilities.txt", 3)],
                "counterevidence": [],
                "limitations": [],
            },
        )
    assert error.value.code == "SYNTHETIC_AS_REAL"


def test_receipt_turns_and_usage(project):
    f = build_research(project, quantitative=False)
    sim = f.simulation("fixture", [f.analysis])
    original = f.records()[key(sim)]["payload"]
    for defect, code in [
        ("mode", "SIMULATION_RECEIPT"),
        ("turns", "DIALOGUE_TURNS"),
        ("usage", "UNKNOWN_USAGE"),
        ("note", "RESEARCH_REF_KIND"),
    ]:
        p = copy.deepcopy(original)
        if defect == "mode":
            p["execution"]["mode"] = "host_inline"
        if defect == "turns":
            p["turns"][1]["speaker"] = "interviewer"
        if defect == "usage":
            p["execution"]["usage"]["money"]["amount"] = 0
        if defect == "note":
            p["transcript_ref"] = f.record("action", {"operation": "note", "note": "Not execution"})
        with pytest.raises(CoreError) as error:
            f.record("simulation", p)
        assert error.value.code == code
