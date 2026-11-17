"""Regression checks for external review: local contracts, not a benchmark or real H."""

import copy
from decimal import Decimal

import pytest

from hooks.checks import release_blockers, run
from tools.contracts import key, ref
from tools.errors import CoreError
from tools.option_scoring import scenario, weighted_score
from tools.search import CHUNK_CHARS, MAX_CHUNKS, corpus, retrieve, text_chunks
from tools.store import Store
from .helpers import add, init
from .test_contracts import hypothesis


SCORES = [
    {"privacy": 4, "reversibility": 4, "value": 1},
    {"privacy": 4, "reversibility": 3, "value": 3},
    {"privacy": 3, "reversibility": 2, "value": 2},
    {"privacy": 4, "reversibility": 1, "value": 0},
]


@pytest.mark.parametrize(
    "values,expected",
    [
        (("0.3", "0.3", "0.4"), ("2.8", "3.3", "2.3", "1.5")),
        (("0.5", "0.3", "0.2"), ("3.4", "3.5", "2.5", "2.3")),
        (("0.2", "0.3", "0.5"), ("2.5", "3.2", "2.2", "1.1")),
    ],
)
def test_three_scenarios_have_no_claimed_ranking_reversal(values, expected):
    weights = dict(zip(("privacy", "reversibility", "value"), values))
    options = [{"id": f"OPT-{i:03}", "payload": {"scores": scores}} for i, scores in enumerate(SCORES, 1)]
    totals, leaders = scenario(options, weights)
    assert list(totals.values()) == list(map(Decimal, expected))
    assert leaders == ["OPT-002"]


@pytest.mark.parametrize("weights", [{}, {"x": 0.9}, {"x": "NaN"}, {"x": "Infinity"}, {"x": -1}])
def test_invalid_weights_are_not_silently_used(weights):
    with pytest.raises(ValueError):
        weighted_score({"x": 4}, weights)


def test_tie_is_reported_without_arbitrary_winner():
    totals, leaders = scenario([{"id": name, "payload": {"scores": {"x": 3}}} for name in ("a", "b")], {"x": 1})
    assert leaders == ["a", "b"] and totals["a"] == 3


def test_lexical_covers_beginning_middle_end_unicode_and_chunk_boundary(project, monkeypatch):
    init(project)
    from tools.adapters import embeddings

    monkeypatch.setattr(embeddings, "execute", lambda *_: pytest.fail("Lexical must not invoke embeddings"))
    text = "начало " + "а " * 690 + "границаслова " + "б " * 1000 + "середина " + "в " * 1500 + "завершение"
    reference = add(project, "claim", hypothesis(text=text))
    with Store(project, "test-core") as store:
        for query in ("начало", "границаслова", "середина", "завершение"):
            hits = retrieve(store, query)["data"]["hits"]
            assert hits and hits[0]["ref"] == reference
            hit = next(h for h in hits if query in h["text"])
            assert hit["text"] == text[hit["start_char"] : hit["end_char"]]
            assert hit["start_char"] <= text.index(query) < hit["end_char"]


def test_chunk_cap_fails_explicitly_instead_of_returning_partial_corpus():
    with pytest.raises(CoreError) as error:
        text_chunks([{"ref": {}, "text": "x" * (CHUNK_CHARS * MAX_CHUNKS)}])
    assert error.value.code == "INDEX_LIMIT"


def test_corpus_fingerprint_binds_chunker_configuration(project, monkeypatch):
    init(project)
    add(project, "claim", hypothesis(text="данные для индекса"))
    from tools import search

    with Store(project, "test-core") as store:
        snapshot, _, _ = store._load()
        records = store.records(snapshot)
        documents, before = corpus(snapshot, records)
        monkeypatch.setattr(search, "CHUNK_OVERLAP", 0)
        same_documents, after = corpus(snapshot, records)
        assert documents == same_documents and before != after


def test_withdrawn_claim_not_returned_as_current_fact(project):
    init(project)
    first = add(project, "claim", hypothesis(text="редкийпоиск"))
    add(project, "claim", hypothesis(text="редкийпоиск", status="retracted"), entity_id=first["entity_id"])
    with Store(project, "test-core") as store:
        assert retrieve(store, "редкийпоиск")["data"]["hits"] == []
        assert all(h["history_only"] for h in retrieve(store, "редкийпоиск", history=True)["data"]["hits"])


def policy_fixture():
    """In-memory policy doubles ONLY; no fabricated review or human receipt is stored."""

    def record(identity, kind, payload):
        return {"case_id": "test-policy", "id": identity, "revision": 1, "kind": kind, "payload": payload}

    target = record("STR-001", "strategy", {"text": "Synthetic strategy"})
    target_ref = ref(target)
    review = record(
        "REV-001", "review", {"target_refs": [target_ref], "verdict": "no_blocking_findings", "findings": []}
    )
    grant = record("APR-001", "approval", {"scope": "final_decision", "status": "approve", "approval_kind": "real"})
    decision = record(
        "DEC-001", "decision", {"status": "confirmed", "strategy_refs": [target_ref], "approval_ref": ref(grant)}
    )
    records = {key(ref(r)): r for r in (target, review, grant, decision)}
    snapshot = {"active": {r["id"]: r["revision"] for r in records.values()}}
    return snapshot, records, {"awaiting_human": None}, {"basis_refs": [target_ref]}


def test_strategy_gate_can_pass_when_exact_conditions_hold():
    assert release_blockers(*policy_fixture()) == []


def test_strategy_gate_rejects_revoked_human_receipt():
    snapshot, records, state, request = policy_fixture()
    records["APR-001@1"]["payload"]["status"] = "reject"
    assert release_blockers(snapshot, records, state, request)


@pytest.mark.parametrize(
    "change", ["pending", "fixture", "no_review", "blocked_review", "stale_target", "wrong_target"]
)
def test_strategy_gate_does_not_drop_protection(change):
    snapshot, records, state, request = policy_fixture()
    if change == "pending":
        state["awaiting_human"] = "reconsideration"
    elif change == "fixture":
        records["APR-001@1"]["payload"]["approval_kind"] = "fixture"
    elif change == "no_review":
        del records["REV-001@1"]
    elif change == "blocked_review":
        records["REV-001@1"]["payload"]["verdict"] = "changes_required"
    elif change == "stale_target":
        snapshot["active"]["STR-001"] = 2
        records["STR-001@2"] = {**records["STR-001@1"], "revision": 2}
    else:
        records["DEC-001@1"]["payload"]["strategy_refs"] = []
    assert release_blockers(snapshot, records, state, request)


def publication_fixture():
    snapshot, records, state, request = policy_fixture()
    grant = records["APR-001@1"]
    grant["payload"].update(
        scope="publication", targets=request["basis_refs"], terms={"destination": "https://github.com/example/repo"}
    )
    request.update(
        release_scope="materials", approval_ref=ref(grant), destination=grant["payload"]["terms"]["destination"]
    )
    state["awaiting_human"] = "reconsideration"
    return snapshot, records, state, request


def test_material_publication_is_not_a_business_approval_or_legal_submission():
    assert release_blockers(*publication_fixture()) == []
    snapshot, records, state, request = publication_fixture()
    request["release_scope"] = "contest_submission"
    assert any("captain" in reason for reason in release_blockers(snapshot, records, state, request))


@pytest.mark.parametrize("change", ["wrong_scope", "wrong_target", "wrong_destination", "fixture", "revoked"])
def test_publication_requires_exact_current_real_grant(change):
    snapshot, records, state, request = publication_fixture()
    grant = records["APR-001@1"]["payload"]
    if change == "wrong_scope":
        grant["scope"] = "development_resource"
    elif change == "wrong_target":
        grant["targets"] = []
    elif change == "wrong_destination":
        request["destination"] += "/other"
    elif change == "fixture":
        grant["approval_kind"] = "fixture"
    else:
        grant["status"] = "reject"
    assert release_blockers(snapshot, records, state, request)


def test_empty_release_targets_are_blocked():
    snapshot, records, state, request = policy_fixture()
    request["basis_refs"] = []
    assert release_blockers(snapshot, records, state, request)


def test_actual_hook_persists_blocker_and_explicit_procedure_can_succeed(project):
    init(project)
    request = {"event": "pre-release", "procedure_id": "release", "procedure_version": "5"}
    with Store(project, "test-core") as store:
        before = store.status()["case_revision"]
        with pytest.raises(CoreError) as error:
            run(store, request, before)
        assert error.value.code == "RELEASE_BLOCKED"
        assert store.status()["case_revision"] > before
        result = run(store, {**request, "event": "procedure"}, store.status()["case_revision"])
        assert result["data"]["hook_executed"]
