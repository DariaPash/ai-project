"""Technical, synthetic-only generator checks; no benchmark/model/STT/network."""

import copy
import importlib.util
import json
from pathlib import Path
import socket
import subprocess

import pytest

from tools.contracts import digest, key, sha
from tools.store import Store
from .helpers import PROJECT, cli, make_project
from .step03_helpers import add_options, build_research, complete_fixture


SPEC = importlib.util.spec_from_file_location("readable_v4", PROJECT / "submission/prepare-v4-readable.py")
readable = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(readable)


@pytest.fixture(scope="module")
def full(tmp_path_factory):
    root = make_project(tmp_path_factory.mktemp("readable-input") / "project")
    return complete_fixture(add_options(build_research(root)))


def tree_bytes(root):
    return {
        str(p.relative_to(root)): sha(p.read_bytes())
        for p in root.rglob("*")
        if p.is_file() and ".locks" not in p.parts
    }


def test_one_snapshot_complete_outputs_without_store_write_or_external_calls(full, tmp_path, monkeypatch):
    before = tree_bytes(full.root / "cases")

    def denied(*args, **kwargs):
        raise AssertionError("Generator attempted an external operation")

    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(subprocess, "run", denied)
    monkeypatch.setattr(subprocess, "Popen", denied)
    output = tmp_path / "readable"
    manifest = readable.prepare(full.root, output, full.case)
    assert before == tree_bytes(full.root / "cases")
    assert manifest["store_mutated"] is False
    assert manifest["publication_authorized"] is False
    assert manifest["business_approval_inferred"] is False
    for r in (full.product, full.communication, full.experiment):
        assert (output / f"{r['entity_id']}-r{r['revision']}.md").exists()
    assert list(output.glob("PRM-*.md")), "kind must be promise, not promise_matrix"
    for name, item in manifest["files"].items():
        assert item["sha256"] == sha((output / name).read_bytes())
        assert item["bytes"] == (output / name).stat().st_size
    assert str(PROJECT) not in "\n".join(p.read_text() for p in output.glob("*.md"))


def test_weights_scores_sensitivity_recomputed_not_claimed_as_market_effect(full, tmp_path):
    output = tmp_path / "readable"
    readable.prepare(full.root, output, full.case)
    text = (output / "options-comparison.md").read_text()
    for option in full.options:
        assert key(option) in text
    assert "Чувствительность 1" in text and "Чувствительность 2" in text
    assert "**3.3**" in text and "**2.8**" in text
    assert "не вероятность успеха" in text


def test_exact_citations_include_hash_revision_coordinates_and_quote(full, tmp_path):
    output = tmp_path / "readable"
    readable.prepare(full.root, output, full.case)
    text = (output / "evidence.md").read_text()
    for r in full.records().values():
        if r["kind"] == "claim":
            for item in r["payload"].get("evidence", []):
                assert key(item["ref"]) in text
                assert item["locator"]["source_hash"] in text
                assert item["locator"]["exact_quote"] in text
                assert str(item["locator"]["coordinates"]["start"]) in text


def test_citation_does_not_invent_a_quote(full):
    quote = copy.deepcopy(full.quote("interview-1.txt", 3))
    quote["locator"]["exact_quote"] = "invented real customer endorsement"
    with pytest.raises(ValueError, match="exact located fragment"):
        readable.citation(quote, full.records())
    quote = copy.deepcopy(full.quote("interview-1.txt", 3))
    quote["locator"]["source_hash"] = "0" * 64
    with pytest.raises(ValueError, match="hash mismatch"):
        readable.citation(quote, full.records())


def test_editorial_translation_is_bound_to_exact_payload_hash(full, tmp_path):
    identity = key(full.product)
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                identity: {
                    "payload_sha256": digest(full.records()[identity]["payload"]),
                    "russian_markdown": "## Проверенный перевод именно этой ревизии\nУчебное предложение.",
                }
            }
        )
    )
    output = tmp_path / "exact"
    result = readable.prepare(full.root, output, full.case, catalog)
    assert identity in result["translated_exact_records"]
    assert "Проверенный перевод" in (output / f"{full.product['entity_id']}-r{full.product['revision']}.md").read_text()
    catalog.write_text(json.dumps({identity: {"payload_sha256": "0" * 64, "russian_markdown": "FALSE TRANSLATION"}}))
    result = readable.prepare(full.root, tmp_path / "mismatch", full.case, catalog)
    assert identity in result["translation_gaps"]
    assert (
        "FALSE TRANSLATION"
        not in (tmp_path / "mismatch" / f"{full.product['entity_id']}-r{full.product['revision']}.md").read_text()
    )


def test_no_overwrite_even_for_dangling_symlink(full, tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    (output / "keep.txt").write_text("user work")
    with pytest.raises(ValueError, match="already exists"):
        readable.prepare(full.root, output, full.case)
    assert (output / "keep.txt").read_text() == "user work"
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "nonexistent")
    with pytest.raises(ValueError, match="already exists"):
        readable.prepare(full.root, link, full.case)


def test_never_write_case_or_immutable_release_tree(full):
    for out in [full.root / "cases/test-core/new", full.root / "submission/v3/new", full.root / "planning/new"]:
        with pytest.raises(ValueError):
            readable.prepare(full.root, out, full.case)
        assert not out.exists()


def test_empty_case_fails_without_partial_output(tmp_path):
    root = make_project(tmp_path / "project")
    with Store(root, "test-empty") as store:
        store.init("test")
    out = tmp_path / "denied"
    with pytest.raises(ValueError, match="synthetic cases with sources"):
        readable.prepare(root, out, "test-empty")
    assert not out.exists()


def test_shipped_onboarding_brief_needs_no_development_fixtures(tmp_path):
    root = make_project(tmp_path / "project")
    case = "test-readable-start"
    cli(root, "init", "--case", case, "--namespace", "test")
    payload = (PROJECT / "submission/v4-content/inputs/brief.json").read_bytes()
    relative = f"cases/{case}/input/brief.json"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    status = cli(root, "status", "--case", case)[1]
    result = cli(
        root,
        "record",
        "--case",
        case,
        "--kind",
        "brief",
        "--file",
        relative,
        "--expected-revision",
        status["case_revision"],
    )[1]
    assert result["ok"]
    assert cli(root, "validate", "--case", case)[1]["ok"]
    assert not (root / "tests").exists()
    assert not (root / "planning").exists()


def test_translation_catalog_covers_both_strategies_and_four_mechanisms():
    catalog = json.loads((PROJECT / "submission/v4-content/russian-catalog.json").read_text())
    for identity in [
        "STR-001@3",
        "STR-002@3",
        "OPT-001@1",
        "OPT-002@1",
        "OPT-003@1",
        "OPT-004@1",
        "EXP-001@3",
        "PRM-001@3",
    ]:
        assert len(catalog[identity]["payload_sha256"]) == 64
        assert len(catalog[identity]["russian_markdown"]) > 300


def test_new_unapproved_strategy_does_not_replace_dec_pins(full, tmp_path):
    old = full.records()[key(full.product)]["payload"]
    newer = full.strategy(
        "product",
        full.options[1],
        full.choice,
        old["basis_refs"],
        old["sections"],
        text=old["text"] + "\nUnapproved later proposal\n",
        entity_id=full.product["entity_id"],
    )
    output = tmp_path / "pinned"
    result = readable.prepare(full.root, output, full.case)
    assert key(full.product) in result["records"]
    assert key(newer) in result["records"]
    assert key(newer) in result["translation_gaps"]
    decision = full.records()[key(full.confirmed)]["payload"]
    assert full.product in decision["strategy_refs"]
    assert newer not in decision["strategy_refs"]
