import copy
import json

import pytest

from tools.contracts import schema_registry, validate_records, validate_schema
from tools.errors import CoreError
from tools.store import Store
from .helpers import FIXTURES, add, artifact, init, record_cli, source_and_extraction


def hypothesis(**updates):
    payload = {
        "text": "Technical hypothesis, not market evidence",
        "type": "hypothesis",
        "status": "unverified",
        "origin": "synthetic_fixture",
        "evidence": [],
        "counterevidence": [],
        "limitations": ["Artificial fixture"],
        "basis_refs": [],
    }
    return {**payload, **updates}


def test_schemas_and_development_registry():
    schemas, _ = schema_registry()
    assert {
        "record",
        "snapshot",
        "claim",
        "source",
        "artifact",
        "extraction",
        "calculation",
        "approval",
        "payloads",
        "common",
        "development-progress",
        "adapter",
    }.issubset(schemas)
    assert all(value["$schema"].endswith("2020-12/schema") for value in schemas.values())
    from pathlib import Path

    validate_schema("development-progress", json.loads(Path("planning/progress.json").read_text()))


@pytest.mark.parametrize("invalid", ["../escape", "a/b", "A", "x" * 65, "test-../x", "a\\b"])
def test_case_slugs_reject_paths(project, invalid):
    with pytest.raises(CoreError) as exc:
        Store(project, invalid)
    assert exc.value.exit_code == 4


def test_missing_src_is_rejected_without_content_commit(project):
    init(project)
    request = json.loads((FIXTURES / "missing-ref.json").read_text())
    result = record_cli(project, "claim", request["payload"], expected=2)
    assert result["code"] == "MISSING_REF"
    with Store(project, "test-core") as store:
        assert store.status()["data"]["record_count"] == 0


def test_fact_is_not_automatically_supported(project):
    init(project)
    add(project, "claim", hypothesis(type="fact"))
    with pytest.raises(CoreError) as exc:
        add(project, "claim", hypothesis(status="supported"))
    assert exc.value.code == "SUPPORT_MISSING"


def test_quote_and_exact_fragment_and_synthetic_lineage(project):
    init(project)
    source, locator = source_and_extraction(project)
    payload = hypothesis(
        origin="public_source",
        evidence=[{"ref": source, "locator": locator}],
        status="supported",
        support_scope="technical_fixture",
        support_review="self-check of fixture only",
    )
    claim = add(project, "claim", payload)
    with Store(project, "test-core") as store:
        snap, _, _ = store._load()
        saved = store.records(snap)[f"{claim['entity_id']}@1"]
        assert saved["lineage_roots"] == ["public_source", "synthetic_fixture"]
    with pytest.raises(CoreError) as exc:
        add(project, "claim", {**payload, "support_scope": "real_world"})
    assert exc.value.exit_code == 4
    for change in (
        {"exact_quote": "A number that is absent"},
        {"coordinates": {"start": 1, "end": 1}},
        {"source_revision": 999},
    ):
        bad = copy.deepcopy(payload)
        bad["evidence"][0]["locator"].update(change)
        with pytest.raises(CoreError):
            add(project, "claim", bad)


def test_dag_cycle_fails_but_related_cycles_are_not_evidence(project):
    init(project)
    a = add(project, "claim", hypothesis(text="A"))
    b = add(project, "claim", hypothesis(text="B", basis_refs=[a]))
    with pytest.raises(CoreError) as exc:
        add(project, "link", {"from_ref": b, "to_ref": a, "relation": "evidence"})
    assert exc.value.code == "EVIDENCE_CYCLE"
    add(project, "link", {"from_ref": b, "to_ref": a, "relation": "related_to"})
    add(project, "link", {"from_ref": a, "to_ref": b, "relation": "related_to"})


def test_refs_cannot_cross_cases(project):
    init(project)
    with pytest.raises(CoreError) as exc:
        add(project, "claim", hypothesis(basis_refs=[{"case_id": "test-other", "entity_id": "CLM-001", "revision": 1}]))
    assert exc.value.code == "MISSING_REF"


def test_lineage_cannot_be_erased_on_a_derived_record(project):
    init(project)
    add(project, "claim", hypothesis())
    with Store(project, "test-core") as store:
        snap, _, _ = store._load()
        records = store.records(snap)
        next(iter(records.values()))["lineage_roots"] = ["public_source"]
        with pytest.raises(CoreError) as exc:
            validate_records(records, "test", "test-core", store.blob)
        assert exc.value.code == "LINEAGE_MISMATCH"
