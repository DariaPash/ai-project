import copy
import pytest
from tools.contracts import key, validate_payload
from tools.errors import CoreError
from tools.store import Store
from .step03_helpers import build_research


def test_plan_weights_questions_and_no_legacy_downgrade(project):
    f = build_research(project, quantitative=False)
    plan = f.records()[key(f.plan)]["payload"]
    assert len(plan["question_refs"]) == 3
    bad = copy.deepcopy(plan)
    bad["criteria"]["weights"]["value"] = 0.9
    with pytest.raises(CoreError) as error:
        f.record("research_plan", bad)
    assert error.value.code == "CRITERIA_WEIGHTS"
    with pytest.raises(CoreError) as error:
        f.record("strategy", {"strategy_type": "product", "text": "legacy bypass", "basis_refs": []})
    assert error.value.code == "CONTRACT_VERSION"
    with pytest.raises(CoreError) as error:
        validate_payload("research_plan", {"contract_version": 4})
    assert error.value.code == "CONTRACT_VERSION"
    with Store(project, "test-core") as store:
        assert store.validate()["warnings"] == []
