import copy
import pytest
from tools.contracts import key
from tools.errors import CoreError
from tools.store import Store
from .step03_helpers import build_research, add_options, complete_fixture


@pytest.fixture
def full(project):
    return complete_fixture(add_options(build_research(project, quantitative=False)))


def test_exact_strategy_artifacts_and_unknown_baseline(full):
    f = full
    records = f.records()
    for kind, r in [("product", f.product), ("communication", f.communication)]:
        assert (f.root / f"cases/{f.case}/output/{kind}-strategy.md").read_text() == records[key(r)]["payload"]["text"]
    assert f.experiment_payload["baseline"] is None
    for defect, code in [
        ("text", "STRATEGY_ARTIFACT"),
        ("hash", "STRATEGY_ARTIFACT"),
        ("kind", "RESEARCH_REF_KIND"),
        ("choice", "OPTION_CHOICE_REQUIRED"),
    ]:
        p = copy.deepcopy(records[key(f.product)]["payload"])
        if defect == "text":
            p["text"] += "Changed"
        if defect == "hash":
            p["content_sha256"] = "0" * 64
        if defect == "kind":
            p["artifact_ref"] = f.imports["capabilities.txt"]["source_ref"]
        if defect == "choice":
            p["option_choice_ref"] = f.final
        with pytest.raises(CoreError) as error:
            f.record("strategy", p)
        assert error.value.code == code
    p = copy.deepcopy(f.experiment_payload)
    p["baseline"] = 42
    with pytest.raises(CoreError) as error:
        f.record("experiment", p)
    assert error.value.code == "BASELINE_UNKNOWN"
    p["baseline_status"] = "measured"
    p["baseline_ref"] = f.analysis
    with pytest.raises(CoreError) as error:
        f.record("experiment", p)
    assert error.value.code == "SYNTHETIC_AS_REAL"


def test_unapproved_strategy_revision_does_not_change_pinned_projection(full):
    f = full
    old = f.records()[key(f.product)]["payload"]
    f.strategy(
        "product",
        f.options[1],
        f.choice,
        old["basis_refs"],
        old["sections"],
        text=old["text"] + "\nUnapproved\n",
        entity_id=f.product["entity_id"],
    )
    output = f.root / f"cases/{f.case}/output/product-strategy.md"
    assert output.read_text() == old["text"]
    output.write_text("tampered projection")
    with Store(f.root, f.case) as store:
        assert store.status()["warnings"]
        store.checkpoint("restore projection", store.status()["case_revision"])
        assert store.validate()["warnings"] == []
    assert output.read_text() == old["text"]
