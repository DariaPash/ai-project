"""Accept only the evidenced local step02 subcontract, never an unrun live gate."""

import json
from pathlib import Path
import re

from tools.contracts import sha, validate_schema
from tools.development import ROOT, now, protected_manifest, write_json
from tools.safeio import SafeRoot
from tools.store import Store


def main():
    progress = json.loads((ROOT / "planning/progress.json").read_text())
    evidence = ROOT / progress["active_run"]
    assert Path(progress["active_run"]).parts[2] == "02"
    destination = evidence / "sources-analytics-manifest.json"
    assert not destination.exists(), "Preserve existing acceptance; new inputs need a new run/revalidation"
    receipts = sorted(
        ((p, json.loads(p.read_text())) for p in evidence.glob("check-*.json")), key=lambda pair: pair[1]["ended_at"]
    )
    suite_path, suite = next((p, r) for p, r in reversed(receipts) if r["command"][-3:] == ["pytest", "tests", "-q"])
    assert suite["exit"] == 0 and "skipped" not in suite["stdout"]
    count = int(re.search(r"(\d+) passed", suite["stdout"])[1])
    for filename, expected in suite["input_hashes"].items():
        assert sha((ROOT / filename).read_bytes()) == expected, "Untested change: " + filename
    freeze = json.loads((evidence / "fixture-freeze.json").read_text())
    for filename, expected in freeze["files"].items():
        assert sha((ROOT / filename).read_bytes()) == expected
    core = json.loads((ROOT / progress["steps"]["01"]["evidence"][0]).read_text())
    core_freeze = ROOT / Path(progress["steps"]["01"]["evidence"][0]).parent / "fixture-freeze.json"
    for filename, expected in json.loads(core_freeze.read_text())["files"].items():
        assert sha((ROOT / filename).read_bytes()) == expected
    baseline = json.loads((evidence / "baseline.json").read_text())
    protected = protected_manifest()
    assert protected == baseline["protected"]
    smoke = json.loads((evidence / "latest-smoke.json").read_text())
    smoke_receipt = json.loads((ROOT / smoke["receipt"]).read_text())
    assert smoke_receipt["status"] == "passed" and smoke_receipt["actual"]
    assert all(c["exit"] == c["expected_exit"] for c in smoke_receipt["commands"])
    assert all(not c["audit"]["network_events"] for c in smoke_receipt["commands"])
    # The final smoke must use the current implementation, not just old green output.
    _, smoke_check = next((p, r) for p, r in reversed(receipts) if r["command"][-1:] == ["tests.run_step02_smoke"])
    assert smoke_check["exit"] == 0
    for filename, expected in smoke_check["input_hashes"].items():
        if filename.startswith(("tools/", "schemas/", "config/")):
            assert sha((ROOT / filename).read_bytes()) == expected, "Stale runtime smoke: " + filename
    semantic = json.loads((evidence / "semantic-receipts.json").read_text())
    assert semantic["actual"] and all(c["exit"] == 0 for c in semantic["commands"])
    gate = json.loads((evidence / "live-gate-receipt.json").read_text())
    assert gate["exit"] == gate["expected_exit"] == 4 and gate["stdout"]["code"] == "DOMAIN_DENIED"
    assert json.loads((ROOT / "config/source_policy.json").read_text())["allowed_domains"] == []
    with Store(ROOT / smoke["project"], smoke["case_id"]) as store:
        checked = store.validate()
        snapshot, _, _ = store._load()
        counts = {
            "case_revision": snapshot["case_revision"],
            "committed_actions": len(snapshot["actions"]),
            "network_attempts": len(snapshot["attempts"]),
            "journal_errors": sum(r["type"] == "ERROR" for r in store.rows),
        }
    assert counts["network_attempts"] == 0
    inherited = ["B", "R", "D", "P-network", "L-live-fetch"]
    next_action = "Начать только явно запрошенный шаг 03 по подтверждённым local import/locator/calculation contracts, сохраняя live-fetch и B/R/D/P blockers"
    manifest = {
        "schema_version": 1,
        "step_id": "02",
        "status": "partial",
        "execution": "local_ready_live_blocked",
        "accepted_at": now(),
        "scope": "Local imports/calculations/lexical plus offline HTTPS security contracts; NOT full F01-F15 or live TLS",
        "tests_passed": count,
        "tests_skipped": 0,
        "latest_suite_receipt": str(suite_path.relative_to(ROOT)),
        "source_hashes": suite["input_hashes"],
        "fixture_freeze_sha256": sha((evidence / "fixture-freeze.json").read_bytes()),
        "smoke": smoke,
        "smoke_counts_from_journal": counts,
        "smoke_snapshot_digest": checked["data"]["snapshot_digest"],
        "semantic_receipt": str((evidence / "semantic-receipts.json").relative_to(ROOT)),
        "semantic_report_sha256": sha((evidence / "semantic-analysis.md").read_bytes()),
        "semantic_scope": "Actual current-agent self-review; not independent or human approval; same frozen sources",
        "live_gate_receipt": str((evidence / "live-gate-receipt.json").relative_to(ROOT)),
        "live_fetch": "blocked_no_approved_URL_or_real_receipt",
        "protected_trees": protected,
        "protected_changes_this_step": [],
        "inherited_gates": inherited,
        "next_action": next_action,
        "cost": {
            "model_tokens": None,
            "money": None,
            "human_minutes": None,
            "reason": "Host usage/billing not exposed; local command duration is not the price of a product outcome",
        },
    }
    relative = str(destination.relative_to(ROOT))
    suite_ref = manifest["latest_suite_receipt"]
    with SafeRoot(ROOT) as root:
        with root.lock("planning/.progress.lock"):
            current = root.json("planning/progress.json")
            step = current["steps"]["02"]
            assert current["active_run"] == progress["active_run"]
            step.update(
                status="partial",
                execution="local_ready_live_blocked",
                gates=inherited,
                blockers=[
                    {
                        "gate": "L-live-fetch",
                        "reason": "Empty domain/path allowlist and no real scoped source-access approval; no live request performed",
                        "unblocks": "Human approves exact public URL, processing rights and resource caps, then real integration evidence",
                    }
                ],
                next_action=next_action,
                updated_at=now(),
            )
            step["evidence"] = [
                relative,
                suite_ref,
                smoke["receipt"],
                smoke["outputs"],
                manifest["semantic_receipt"],
                manifest["live_gate_receipt"],
                str((evidence / "semantic-analysis.md").relative_to(ROOT)),
            ]
            step["accepted_subcontracts"] = [
                "md-txt-textpdf-csv-xlsx-html-local-import-v1",
                "immutable-source-extraction-locators-lineage",
                "frozen-quantitative-decimal-oracles",
                "local-lexical-with-current-status-rights",
                "offline-pinned-https-security-matrix-not-live-TLS",
                "incremental-cli-smoke-and-current-agent-semantic-self-review",
            ]
            step["changed_files"] = sorted(
                p for p, h in suite["input_hashes"].items() if core["source_hashes"].get(p) != h
            ) + ["planning/handoff.md", "planning/progress.json"]
            step["completed_units"].append(
                {
                    "label": f"Local step02 accepted: {count} tests; all formats; six Q/E operations; actual CLI/audit/self-review; live blocked",
                    "at": now(),
                }
            )
            current["steps"]["01"]["revalidated_by_step02"] = {
                "receipt": suite_ref,
                "scope": "Predecessor tests rerun after additive core changes; original acceptance history preserved",
            }
            scopes = {
                "F01": "Local six-format ingestion, located conflict, offline fetch security; live fetch/discovery outstanding",
                "F02": "Six deterministic quantitative operations and frozen oracle; broader research interpretation in step03",
                "F13": "Local lexical only; no embeddings/hybrid implemented",
                "F14": "Core regression plus incremental source/metrics pause-resume; no new-context/full-product/second-host claim",
            }
            for feature, scope in scopes.items():
                for dimension in ("implementation", "offline"):
                    current["features"][feature][dimension] = {
                        "status": "partial",
                        "scope": scope,
                        "evidence": [relative, suite_ref],
                    }
            current["features"]["F01"]["live"] = {
                "status": "blocked",
                "scope": "No authorized real HTTPS URL; doubles not live integration",
                "evidence": [manifest["live_gate_receipt"]],
            }
            for feature in ("F01", "F02"):
                current["features"][feature]["semantic"] = {
                    "status": "partial",
                    "scope": "Current-agent synthetic conflict/data-quality self-review; not independent or real-demand support",
                    "evidence": [manifest["semantic_receipt"]],
                }
                current["features"][feature]["acceptance"] = {
                    "status": "partial",
                    "scope": scopes[feature],
                    "evidence": [relative],
                }
            current["revision"] += 1
            current["updated_at"] = now()
            validate_schema("development-progress", current)
            write_json(destination, manifest)
            root.write("planning/progress.json", (json.dumps(current, ensure_ascii=False, indent=2) + "\n").encode())
    print(
        json.dumps(
            {
                "step": "02",
                "status": "partial",
                "tests_passed": count,
                "manifest": relative,
                "next_action": next_action,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
