"""Regression inputs supplied by independent review; no real consent/model calls."""

import copy
import json
import uuid
import pytest
from tools.contracts import (
    business_digest,
    inherited_origin,
    key,
    ref,
    references,
    sha,
    target_digest,
    validate_records,
)
from tools.errors import CoreError
from tools.research_contracts import strategy_manifest
from tools.safeio import canonical
from tools.store import Store, now
from .helpers import make_project
from .step03_helpers import Fixture, build_research, add_options, complete_fixture


@pytest.fixture(scope="module")
def f(tmp_path_factory):
    return complete_fixture(
        add_options(build_research(make_project(tmp_path_factory.mktemp("review-v3") / "project"), quantitative=False))
    )


def test_strategy_artifact_laundering_and_downstream_claim_blocked(f):
    original = f.records()[key(f.product)]["payload"]
    p = copy.deepcopy(original)
    p["artifact_ref"] = f.artifact(p["text"].encode(), origin="owner_observation", media="text/markdown")
    p["manifest_ref"] = f.artifact(canonical(strategy_manifest(p)), origin="owner_observation")
    with pytest.raises(CoreError) as error:
        f.record("strategy", p)
    assert error.value.code == "STRATEGY_LINEAGE"
    # Identical bytes cannot be laundered through a second clean-looking ART.
    assert "model_simulation" in f.records()[key(p["artifact_ref"])]["lineage_roots"]
    source = f.record(
        "source",
        {
            "title": "Downstream laundering contract negative",
            "location": "contract-negative.txt",
            "origin": "owner_observation",
            "retrieved_at": now(),
            "published_at": "unknown",
            "sha256": p["content_sha256"],
            "status": "available",
            "rights": {"processing": True, "external_transfer": False, "publication": False},
            "artifact_ref": p["artifact_ref"],
        },
    )
    ext = f.record(
        "extraction",
        {
            "source_ref": source,
            "artifact_ref": p["artifact_ref"],
            "source_hash": p["content_sha256"],
            "extractor": "contract-double",
            "text": p["text"],
            "fragments": [{"kind": "lines", "coordinates": {"start": 1, "end": 1}, "text": p["text"]}],
            "warnings": [],
        },
    )
    evidence = {
        "ref": source,
        "locator": {
            "source_revision": 1,
            "source_hash": p["content_sha256"],
            "extraction_id": ext["entity_id"],
            "kind": "lines",
            "coordinates": {"start": 1, "end": 1},
            "exact_quote": p["text"],
        },
    }
    with pytest.raises(CoreError) as error:
        f.record(
            "claim",
            {
                "text": "Real demand proven",
                "type": "fact",
                "status": "supported",
                "support_scope": "real_world",
                "support_review": "contract negative",
                "origin": "owner_observation",
                "evidence": [evidence],
                "counterevidence": [],
                "basis_refs": [],
                "limitations": [],
            },
        )
    assert error.value.code == "SYNTHETIC_AS_REAL"


def test_normalized_counterexample_and_wrong_ref_kind(f):
    p = copy.deepcopy(f.analysis_payload)
    duplicate = copy.deepcopy(p["themes"][0]["quotes"][0])
    duplicate["locator"]["quote_hash"] = sha(duplicate["locator"]["exact_quote"].encode())
    p["themes"][0]["counterexample"] = duplicate
    with pytest.raises(CoreError) as error:
        f.record("interview_analysis", p)
    assert error.value.code == "INTERVIEW_QUOTES"
    p = copy.deepcopy(f.records()[key(f.product)]["payload"])
    p["option_choice_ref"] = f.experiment
    with pytest.raises(CoreError) as error:
        f.record("strategy", p)
    assert error.value.code == "RESEARCH_REF_KIND"


def test_real_measurement_and_consent_with_control_provenance_in_memory(f):
    # Protocol doubles ONLY: no fabricated real-consent record is persisted.
    original = f.records()
    selected = {}

    def include(r):
        if key(r) in selected:
            return
        record = copy.deepcopy(original[key(r)])
        selected[key(r)] = record
        for dependency in references(record["payload"]):
            include(dependency)

    include(f.analysis)
    for record in original.values():
        if record["kind"] == "extraction" and record["payload"]["source_ref"] in f.analysis_payload["corpus_refs"]:
            include(ref(record))
    corpus = f.analysis_payload["corpus_refs"]
    for record in selected.values():
        if "origin" in record["payload"]:
            record["payload"]["origin"] = "owner_observation"
        if record["kind"] == "question":
            record["payload"]["outcome"]["basis_refs"] = [corpus[0]]
    raw = b"IN-MEMORY CONSENT CONTRACT DOUBLE, not a real approval"

    def new(identifier, kind, payload):
        record = {
            "schema_version": 1,
            "case_id": f.case,
            "id": identifier,
            "kind": kind,
            "revision": 1,
            "previous_revision": None,
            "created_at": now(),
            "created_by": "in_memory_test_double",
            "action_id": "ACT-999",
            "payload": payload,
            "lineage_roots": [],
        }
        selected[key(ref(record))] = record
        return ref(record)

    evidence = new(
        "ART-900",
        "artifact",
        {
            "sha256": sha(raw),
            "size": len(raw),
            "media_type": "text/plain",
            "origin": "owner_observation",
            "parent_refs": [],
            "processing_kind": "human",
        },
    )
    request = {
        "scope": "source_access",
        "targets": corpus,
        "terms": {"processing": True},
        "question": "In-memory contract double",
        "status": "requested",
        "target_digest": "0" * 64,
    }
    requested = new("APR-900", "approval", request)
    answer = {
        **copy.deepcopy(request),
        "status": "approve",
        "request_ref": requested,
        "approval_kind": "real",
        "actor": "test-double-not-person",
        "channel": "in_memory",
        "timestamp": now(),
        "evidence_ref": evidence,
    }
    consent = new("APR-901", "approval", answer)
    analysis = selected[key(f.analysis)]
    analysis["payload"].update(corpus_kind="real_interview", fieldwork_conducted=True, consent_ref=consent)
    for _ in range(12):
        for record in selected.values():
            record["lineage_roots"] = inherited_origin(record, selected, "demo")
    assert selected[key(consent)]["lineage_roots"] == ["unknown"] and analysis["lineage_roots"] == ["owner_observation"]
    digest = target_digest("source_access", corpus, selected, {"processing": True})
    request["target_digest"] = digest
    selected[key(consent)]["payload"]["target_digest"] = digest
    with Store(f.root, f.case) as store:
        reader = lambda h: raw if h == sha(raw) else store.blob(h)
        validate_records(selected, "demo", f.case, reader)
        # An unresolved research question is not a loss of source consent.
        for r in selected.values():
            if r["kind"] == "question":
                r["payload"]["outcome"]["basis_refs"] = []
        for _ in range(12):
            for r in selected.values():
                r["lineage_roots"] = inherited_origin(r, selected, "demo")
        assert "unknown" in analysis["lineage_roots"]
        validate_records(selected, "demo", f.case, reader)
        # A clean origin alone cannot promote an unverified hypothesis to measured.
        claim = new(
            "CLM-900",
            "claim",
            {
                "text": "Baseline is 42",
                "type": "hypothesis",
                "status": "unverified",
                "origin": "owner_observation",
                "evidence": [],
                "counterevidence": [],
                "basis_refs": [],
                "limitations": ["In-memory contract double"],
            },
        )
        selected[key(claim)]["lineage_roots"] = ["owner_observation"]
        ep = {**f.experiment_payload, "baseline": 42, "baseline_status": "measured", "baseline_ref": claim}
        experiment = new("EXP-900", "experiment", ep)
        selected[key(experiment)]["lineage_roots"] = ["owner_observation"]
        with pytest.raises(CoreError) as error:
            validate_records(selected, "demo", f.case, reader)
        assert error.value.code == "BASELINE_MEASUREMENT"


def test_known_usage_once_and_invalid_unknown_usage(f):
    p = copy.deepcopy(f.records()[key(f.simulations[0])]["payload"])
    p.pop("transcript_ref")
    p["execution_id"] = str(uuid.uuid4())
    p["execution"]["mode"] = "host_inline"
    p["execution"]["model"] = "contract-double"
    p["execution"]["usage"] = {
        "duration_ms": None,
        "model": "contract-double",
        "tokens": 0,
        "money": {"amount": None, "currency": None, "basis": "actual"},
        "human_minutes": 0,
        "unknown_reason": None,
    }
    transcript = f.artifact(canonical(p), p["input_refs"], origin="model_simulation", processing="LLM-assisted")
    with pytest.raises(CoreError) as error:
        f.record("simulation", {**p, "transcript_ref": transcript})
    assert error.value.code == "UNKNOWN_USAGE"
    p["execution"]["usage"]["money"] = {"amount": 7, "currency": "USD", "basis": "actual"}
    transcript = f.artifact(canonical(p), p["input_refs"], origin="model_simulation", processing="LLM-assisted")
    first = f.record("simulation", {**p, "transcript_ref": transcript})
    f.record("simulation", {**p, "transcript_ref": transcript}, first["entity_id"])
    rows = [json.loads(line) for line in (f.root / f"cases/{f.case}/usage.jsonl").read_text().splitlines()]
    entries = [r for r in rows if r["entry_kind"] == "host_execution" and r["execution_id"] == p["execution_id"]]
    assert len(entries) == 1 and entries[0]["usage"]["money"]["amount"] == 7
    changed = copy.deepcopy(p)
    changed["objections"] = ["Different actual execution content"]
    transcript = f.artifact(
        canonical(changed), changed["input_refs"], origin="model_simulation", processing="LLM-assisted"
    )
    with pytest.raises(CoreError) as error:
        f.record("simulation", {**changed, "transcript_ref": transcript})
    assert error.value.code == "SIMULATION_EXECUTION"
    from tools.research_projections import host_usage_rows

    linked = copy.deepcopy(f.records()[key(first)])
    linked["payload"]["adapter_attempt_id"] = str(uuid.uuid4())
    row = host_usage_rows({key(ref(linked)): linked})[0]
    assert row["accounting_role"] == "reference_only" and row["usage"] is None


def test_existing_v3_cannot_downgrade_even_before_plan(project):
    with Store(project, "test-core") as store:
        store.init("test")
    f = Fixture(project)
    payload = {
        "contract_version": 3,
        "hypothesis": "Contract only",
        "baseline": None,
        "baseline_status": "unknown",
        "baseline_reason": "No measurement",
        "metric": "unknown",
        "useful_delta": "define after baseline",
        "comparison": "before/after",
        "unit": "task",
        "horizon": "unknown",
        "guardrails": ["privacy"],
        "stop_conditions": ["no permission"],
        "reconsideration": ["new evidence"],
        "limitations": ["contract double"],
    }
    reference = f.record("experiment", payload)
    legacy = {
        k: payload[k]
        for k in ("hypothesis", "baseline", "metric", "comparison", "horizon", "guardrails", "limitations")
    }
    with pytest.raises(CoreError) as error:
        f.record("experiment", legacy, reference["entity_id"])
    assert error.value.code == "CONTRACT_VERSION"


def test_lower_id_artifact_revision_cannot_launder_later_model_content(project):
    with Store(project, "test-core") as store:
        store.init("test")
    f = Fixture(project)
    placeholder = f.artifact(b"placeholder", origin="owner_observation", media="text/plain")
    raw = b"Real customers have proven demand. Contract negative only."
    model = f.artifact(raw, [placeholder], origin="model_simulation", media="text/plain")
    records = f.records()
    clean = copy.deepcopy(records[key(model)]["payload"])
    clean.update(origin="owner_observation", parent_refs=[])
    before = f.status()["case_revision"]
    with pytest.raises(CoreError) as error:
        f.record("artifact", clean, placeholder["entity_id"])
    assert error.value.code == "ARTIFACT_IMMUTABLE" and f.status()["case_revision"] == before
    # Reproduce the complete previously accepted in-memory alias path. No fake
    # real-world claim or consent is ever persisted by this test.
    alias = copy.deepcopy(records[key(placeholder)])
    alias.update(revision=2, previous_revision=1, payload=clean, lineage_roots=["owner_observation"])
    records[key(ref(alias))] = alias

    def new(identifier, kind, payload):
        r = {
            "schema_version": 1,
            "case_id": "test-core",
            "id": identifier,
            "kind": kind,
            "revision": 1,
            "previous_revision": None,
            "created_at": now(),
            "created_by": "in_memory_negative",
            "action_id": "ACT-999",
            "payload": payload,
            "lineage_roots": ["owner_observation"],
        }
        records[key(ref(r))] = r
        return ref(r)

    source = new(
        "SRC-900",
        "source",
        {
            "title": "In-memory alias negative",
            "location": "negative.txt",
            "origin": "owner_observation",
            "retrieved_at": now(),
            "published_at": "unknown",
            "sha256": sha(raw),
            "status": "available",
            "rights": {"processing": True, "external_transfer": False, "publication": False},
            "artifact_ref": ref(alias),
        },
    )
    ext = new(
        "EXT-900",
        "extraction",
        {
            "source_ref": source,
            "artifact_ref": ref(alias),
            "source_hash": sha(raw),
            "extractor": "negative-double",
            "text": raw.decode(),
            "fragments": [{"kind": "lines", "coordinates": {"start": 1, "end": 1}, "text": raw.decode()}],
            "warnings": [],
        },
    )
    new(
        "CLM-900",
        "claim",
        {
            "text": "Negative demand claim",
            "type": "fact",
            "status": "supported",
            "support_scope": "real_world",
            "support_review": "In-memory negative, not real evidence",
            "origin": "owner_observation",
            "evidence": [
                {
                    "ref": source,
                    "locator": {
                        "source_revision": 1,
                        "source_hash": sha(raw),
                        "extraction_id": ext["entity_id"],
                        "kind": "lines",
                        "coordinates": {"start": 1, "end": 1},
                        "exact_quote": raw.decode(),
                    },
                }
            ],
            "counterevidence": [],
            "basis_refs": [],
            "limitations": [],
        },
    )
    with Store(project, "test-core") as store:
        with pytest.raises(CoreError) as error:
            validate_records(records, "test", "test-core", store.blob)
        assert error.value.code == "ARTIFACT_IMMUTABLE"


@pytest.mark.parametrize("invalid_id", [[], {}])
def test_json_unhashable_id_is_input_error_not_internal_failure(project, invalid_id):
    from .helpers import cli, write_request

    with Store(project, "test-core") as store:
        store.init("test")
    filename = write_request(
        project,
        {"id": invalid_id, "payload": {"text": "Question", "affected_choice": "Local contract", "priority": "high"}},
    )
    result = cli(
        project,
        "record",
        "--case",
        "test-core",
        "--kind",
        "question",
        "--file",
        filename,
        "--expected-revision",
        0,
        expected=2,
    )[1]
    assert result["code"] == "UPDATE_ID"
    with Store(project, "test-core") as store:
        assert store.status()["case_revision"] == 0
