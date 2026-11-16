"""Record bounded step03 acceptance only from actual current evidence."""

import json
from pathlib import Path
import re
from tools.contracts import sha, validate_schema, key
from tools.development import ROOT, now, write_json, protected_manifest
from tools.safeio import SafeRoot
from tools.store import Store


def main():
    progress = json.loads((ROOT / "planning/progress.json").read_text())
    run = ROOT / progress["active_run"]
    assert "/03/" in progress["active_run"]
    manifest_path = run / "research-strategy-manifest.json"
    assert not manifest_path.exists(), "Preserve existing acceptance; revalidate in a new run"
    checks = sorted(((p, json.loads(p.read_text())) for p in run.glob("check-*.json")), key=lambda x: x[1]["ended_at"])
    suite_path, suite = next((p, r) for p, r in reversed(checks) if r["command"][-3:] == ["pytest", "tests", "-q"])
    assert suite["exit"] == 0 and "skipped" not in suite["stdout"]
    count = int(re.search(r"(\d+) passed", suite["stdout"])[1])
    for filename, expected in suite["input_hashes"].items():
        assert sha((ROOT / filename).read_bytes()) == expected, "Untested change: " + filename
    freeze = json.loads((run / "fixture-freeze.json").read_text())
    for filename, expected in freeze["files"].items():
        assert sha((ROOT / filename).read_bytes()) == expected, "Observer fixture changed: " + filename
    predecessor_path = progress["steps"]["02"]["evidence"][0]
    predecessor = json.loads((ROOT / predecessor_path).read_text())
    previous_freeze = ROOT / Path(predecessor_path).parent / "fixture-freeze.json"
    for filename, expected in json.loads(previous_freeze.read_text())["files"].items():
        assert sha((ROOT / filename).read_bytes()) == expected
    baseline = json.loads((run / "baseline.json").read_text())
    protected = protected_manifest()
    assert protected == baseline["protected"]
    integration = json.loads((run / "latest-integration.json").read_text())
    receipt = json.loads((ROOT / integration["receipts"]).read_text())
    outputs = json.loads((ROOT / integration["outputs"]).read_text())
    assert receipt["status"] == "passed" and receipt["actual"] and all(c["exit"] == 0 for c in receipt["commands"])
    _, smoke_check = next((p, r) for p, r in reversed(checks) if r["command"][-1:] == ["tests.run_step03_smoke"])
    assert smoke_check["exit"] == 0
    for filename, expected in smoke_check["input_hashes"].items():
        if (
            filename.startswith(("tools/", "schemas/", "config/")) and filename != "tools/development.py"
        ) or filename == "tests/step03_helpers.py":
            assert sha((ROOT / filename).read_bytes()) == expected, "Stale product smoke: " + filename
    ordered = json.loads((run / "ordered-host-receipt.json").read_text())
    assert ordered["actual"] and ordered["plan_committed_before_generation"] and ordered["sources_unchanged"]
    assert len(ordered["role_refs"]) == 3 and all(c["exit"] == 0 for c in ordered["commands"])
    for filename, expected in ordered["input_hashes"].items():
        assert sha((ROOT / filename).read_bytes()) == expected
    fixture = outputs["fixture"]
    with Store(ROOT / fixture["project"], fixture["case_id"]) as store:
        validated = store.validate()
        assert validated["data"]["snapshot_digest"] == fixture["state"]["snapshot_digest"]
    with Store(ROOT / ordered["project"], ordered["case_id"]) as store:
        checked = store.validate()
        snapshot, _, _ = store._load()
        records = store.records(snapshot)
        assert checked["data"]["snapshot_digest"] == ordered["after"]["snapshot_digest"]
        assert snapshot["runtime"]["awaiting_human"] == "option_choice" and not snapshot["attempts"]
        assert not any(r["kind"] == "decision" for r in records.values())
        for reference in ordered["role_refs"]:
            role = records[key(reference)]
            assert (
                role["payload"]["execution"]["mode"] == "host_inline"
                and role["payload"]["execution"]["context_independence"] == "not_independent"
                and "model_simulation" in role["lineage_roots"]
            )
        host_counts = {
            "case_revision": snapshot["case_revision"],
            "committed_actions": len(snapshot["actions"]),
            "network_attempts": len(snapshot["attempts"]),
            "journal_errors": sum(r["type"] == "ERROR" for r in store.rows),
        }
    review = json.loads((run / "review-receipt.json").read_text())
    assert (
        review["session_id"] == "ses_e25c390e3ffe9eXs5n6PR2GthE"
        and review["status"] == "completed"
        and review["unresolved_findings_in_reviewed_scope"] == []
    )
    assert sha((run / "review-final.md").read_bytes()) == review["report_sha256"]
    gates = [
        "B",
        "R-real-runtime",
        "D",
        "P-real-data-network",
        "L-live-fetch",
        "H-option-choice",
        "H-final-decision",
        "runtime-reviewer-step05",
    ]
    next_action = "Начать только явно запрошенный шаг 04 на принятом technical bundle/text contracts; наследовать H/B/R/D/P/live-fetch/runtime-reviewer blockers"
    scope = "Step03 local v3 research/interview/model-role/strategy/approval contracts; actual single-host synthetic analysis and 3 ordered roles; full fixture lifecycle only. No real H/fieldwork/pilot or full F01-F15 acceptance."
    manifest = {
        "schema_version": 1,
        "step_id": "03",
        "status": "partial",
        "execution": "technical_ready_live_H_blocked",
        "accepted_at": now(),
        "scope": scope,
        "tests_passed": count,
        "tests_skipped": 0,
        "latest_suite_receipt": str(suite_path.relative_to(ROOT)),
        "source_hashes": suite["input_hashes"],
        "fixture_freeze_sha256": sha((run / "fixture-freeze.json").read_bytes()),
        "prerequisite_manifest": predecessor_path,
        "integration": integration,
        "fixture_case": fixture,
        "ordered_host_receipt": str((run / "ordered-host-receipt.json").relative_to(ROOT)),
        "host_counts_from_journal": host_counts,
        "host_snapshot_digest": checked["data"]["snapshot_digest"],
        "independent_development_review": str((run / "review-receipt.json").relative_to(ROOT)),
        "reviewer_scope": "One separate context, four review iterations; no runtime reviewer05/H/fieldwork/blanket security guarantee",
        "protected_trees": protected,
        "protected_changes_this_step": [],
        "gates": gates,
        "next_action": next_action,
        "usage": {
            "tokens": None,
            "money": None,
            "human_minutes": None,
            "unknown_reason": "Leading-host/reviewer billing and human time not exposed; local helper timing not product outcome cost",
        },
    }
    relative = str(manifest_path.relative_to(ROOT))
    suite_ref = manifest["latest_suite_receipt"]
    with SafeRoot(ROOT) as root:
        with root.lock("planning/.progress.lock"):
            current = root.json("planning/progress.json")
            assert current["active_run"] == progress["active_run"]
            step = current["steps"]["03"]
            step.update(
                status="partial",
                execution="technical_ready_live_H_blocked",
                gates=gates,
                next_action=next_action,
                updated_at=now(),
                budget_used=manifest["usage"],
                blockers=[
                    {
                        "gate": "H-option-choice",
                        "reason": "Actual host request is unanswered; no actual human direction/decision inferred",
                        "unblocks": "Actual product-user approve/reject/revise receipt on exact bundle",
                    },
                    {
                        "gate": "H-final-decision",
                        "reason": "Live strategies/DEC cannot proceed before direction H; fixture lifecycle is not real H",
                        "unblocks": "After direction approval, real final response on exact pending DEC bundle",
                    },
                ],
            )
            step["evidence"] = [
                relative,
                suite_ref,
                integration["receipts"],
                integration["outputs"],
                manifest["ordered_host_receipt"],
                manifest["independent_development_review"],
                str((run / "review-final.md").relative_to(ROOT)),
            ]
            step["accepted_subcontracts"] = [
                "v3-research-questions-criteria-gaps",
                "located-interview-theme-counterexample-consent-contract",
                "actual-ordered-single-host-synthetic-roles-with-usage",
                "four-mechanisms-and-two-strategy-artifact-manifests",
                "distinct-exact-option-and-final-approval-bindings",
                "full-technical-fixture-lifecycle-pinned-projections",
                "independent-development-code-content-review-not-runtime05",
            ]
            step["changed_files"] = sorted(
                p for p, h in suite["input_hashes"].items() if predecessor["source_hashes"].get(p) != h
            ) + ["planning/handoff.md", "planning/progress.json"]
            step["completed_units"].append(
                {
                    "label": f"Technical step03 accepted: {count} tests, full fixture path, actual ordered host roles/analysis, independent bounded review; real H blocked",
                    "at": now(),
                }
            )
            current["steps"]["02"]["revalidated_by_step03"] = {
                "receipt": suite_ref,
                "scope": "All predecessor tests rerun; immutable original manifest preserved",
            }
            for feature, description in {
                "F03": "Located text interview contracts and actual host analysis of artificial corpus; no fieldwork",
                "F04": "Three ordered actual host-inline role dialogues, one context/model_simulation, not empirical respondents",
                "F07": "Four technical mechanisms, two fixture strategies/protocol and separate development review; real H/runtime reviewer outstanding",
                "F08": "Exact two-stage approval/DEC fixture lifecycle; real H and agenda/obligations outstanding",
                "F09": "Pinned strategy/criteria/DEC versions only; full impact/reconsideration remains step06",
                "F14": "Core regression and same-case checkpoint/status without duplicate imports; N/E/full resume remain future",
            }.items():
                for dimension in ("implementation", "offline"):
                    current["features"][feature][dimension] = {
                        "status": "partial",
                        "scope": description,
                        "evidence": [relative, suite_ref],
                    }
            for feature in ("F03", "F04"):
                current["features"][feature]["live"] = {
                    "status": "partial",
                    "scope": "Actual permitted current-host model generation on artificial inputs; not external API, fieldwork or independent roles",
                    "evidence": [manifest["ordered_host_receipt"]],
                }
            for feature in ("F01", "F02", "F03", "F04", "F07"):
                current["features"][feature]["semantic"] = {
                    "status": "partial",
                    "scope": "Separate bounded development review of synthetic proposals/initial host drafts, not real business approval; ordered followup checked separately by tools",
                    "evidence": [manifest["independent_development_review"]],
                }
            current["features"]["F07"]["acceptance"] = {
                "status": "partial",
                "scope": "Technical fixture content reviewed; actual direction/final H and runtime05 review not closed",
                "evidence": [relative],
            }
            current["revision"] += 1
            current["updated_at"] = now()
            validate_schema("development-progress", current)
            write_json(manifest_path, manifest)
            root.write("planning/progress.json", (json.dumps(current, ensure_ascii=False, indent=2) + "\n").encode())
    print(
        json.dumps(
            {"step": "03", "status": "partial", "tests_passed": count, "manifest": relative, "host": host_counts},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
