import copy
import json
import pytest
from tools.errors import CoreError
from .helpers import PROJECT
from .step03_helpers import build_research


def test_observer_key_is_not_generator_input(project):
    f = build_research(project, quantitative=False)
    oracle = json.loads((PROJECT / "tests/fixtures/research/oracle.json").read_text())
    theme = f.analysis_payload["themes"][0]
    assert [q["locator"]["exact_quote"] for q in theme["quotes"]] == [q["text"] for q in oracle["quotes"]]
    assert theme["counterexample"]["locator"]["exact_quote"] == oracle["counterexample"]["text"]
    assert (
        not f.analysis_payload["fieldwork_conducted"] and not (project / "tests/fixtures/research/oracle.json").exists()
    )


@pytest.mark.parametrize(
    "defect,code",
    [
        ("wrong", "QUOTE_MISMATCH"),
        ("missing", "SCHEMA_INVALID"),
        ("duplicate", "INTERVIEW_QUOTES"),
        ("outside", "INTERVIEW_QUOTES"),
        ("consent", "CONSENT_REQUIRED"),
    ],
)
def test_quotes_and_consent(project, defect, code):
    f = build_research(project, quantitative=False)
    p = copy.deepcopy(f.analysis_payload)
    if defect == "wrong":
        p["themes"][0]["quotes"][0]["locator"]["exact_quote"] = "Fabricated quote"
    if defect == "missing":
        del p["themes"][0]["quotes"][0]["locator"]["exact_quote"]
    if defect == "duplicate":
        p["themes"][0]["quotes"][1] = copy.deepcopy(p["themes"][0]["quotes"][0])
    if defect == "outside":
        p["themes"][0]["counterexample"] = f.quote("capabilities.txt", 3)
    if defect == "consent":
        p["corpus_kind"] = "real_interview"
        p["fieldwork_conducted"] = True
    before = f.status()["case_revision"]
    with pytest.raises(CoreError) as error:
        f.record("interview_analysis", p)
    assert error.value.code == code and f.status()["case_revision"] == before
