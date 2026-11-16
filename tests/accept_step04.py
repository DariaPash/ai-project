"""Partial step04 acceptance from real receipts; never hides blocked STT/H."""

import hashlib
import json
from pathlib import Path
import re

from tools.contracts import key, validate_schema
from tools.development import ROOT, now, protected_manifest, write_json
from tools.safeio import SafeRoot
from tools.store import Store
from tools.errors import CoreError


def publish(root_path, target, manifest, expected_revision, update):
    """Recoverable publication: a retained manifest can finish the same progress update."""
    relative = str(target.relative_to(root_path))
    with SafeRoot(root_path) as root:
        with root.lock("planning/.progress.lock"):
            current = root.json("planning/progress.json")
            if current["revision"] != expected_revision:
                raise CoreError("CONFLICT", "Development progress changed before acceptance publication", 7)
            if target.exists():
                if root.json(relative) != manifest:
                    raise CoreError("ACCEPTANCE_CONFLICT", "Existing acceptance differs; preserve it and diagnose", 7)
                if relative in current["steps"]["04"].get("evidence", []):
                    return False
            update(current)  # Includes schema validation before publication.
            if not target.exists():
                write_json(target, manifest)
            root.write("planning/progress.json", (json.dumps(current, ensure_ascii=False, indent=2) + "\n").encode())
    return True


def main():
    p = json.loads((ROOT / "planning/progress.json").read_text())
    run = ROOT / p["active_run"]
    assert Path(p["active_run"]).parts[2] == "04"
    target = run / "media-ux-manifest.json"
    prior_manifest = json.loads(target.read_text()) if target.exists() else None
    suites = sorted(
        (
            json.loads(f.read_text()) | {"path": str(f.relative_to(ROOT))}
            for f in run.glob("check-*.json")
            if json.loads(f.read_text())["command"][-3:] == ["pytest", "tests", "-q"]
        ),
        key=lambda v: v["started_at"],
    )
    assert suites
    suite = suites[-1]
    assert suite["exit"] == 0
    passed = int(re.search(r"(\d+) passed", suite["stdout"])[1])
    skipped = int(re.search(r"(\d+) skipped", suite["stdout"])[1]) if "skipped" in suite["stdout"] else 0
    assert skipped == 1 and "STT" in suite["stdout"], "Unexpected skip must be diagnosed"
    for name, expected in suite["input_hashes"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, "Untested change: " + name
    freeze = json.loads((run / "fixture-freeze.json").read_text())
    for name, expected in freeze["files"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, "Frozen input changed: " + name
    processed = json.loads((run / "processing-receipt.json").read_text())
    story_path = run / "story-timing-corrected-receipt.json"
    story = json.loads(story_path.read_text())
    review = json.loads((run / "review-receipt.json").read_text())
    assert review["remaining_P1_P2"] == [] and review["separate_context"]
    assert (
        not processed["speech"]["actual_recognition_performed"] and processed["speech"]["code"] == "STT_AUTH_REQUIRED"
    )
    assert story["sparse_before_dense"] and not story["oracle_passed_to_perception"] and not story["real_H"]
    with Store(ROOT / story["project"], story["case_id"]) as store:
        status = store.status()
        assert status["data"]["snapshot_digest"] == story["state"]["data"]["snapshot_digest"]
        assert store.validate()["warnings"] == []
        snapshot, _, _ = store._load()
        records = store.records(snapshot)
        revised = story["revised"]
        decision = records[key(revised["decision_ref"])]["payload"]
        assert decision["status"] == "pending" and decision["strategy_refs"] == revised["strategy_refs"]
        assert status["data"]["state"]["awaiting_human"] == "reconsideration"
        assert all(
            records[key(r)]["payload"]["completion_status"] == "unknown"
            for r in (story["ux_ref"], story["event_ref"], story["journey_ref"])
        )
        counts = {
            "case_revision": snapshot["case_revision"],
            "committed_actions": len(snapshot["actions"]),
            "records": len(snapshot["records"]),
            "network_attempts": len(snapshot["attempts"]),
            "journal_errors": sum(r["type"] == "ERROR" for r in store.rows),
        }
    baseline = json.loads((run / "baseline.json").read_text())["protected"]
    protected = protected_manifest()
    changed = sorted(name for name in baseline if protected[name] != baseline[name])
    preserved = None
    if changed:
        receipt_path = run / "protected-delta-preserved.json"
        receipt = json.loads(receipt_path.read_text())
        assert changed == receipt["changed_protected_trees"] == [".idea"], (
            "Protected implementation changed; diagnose without reset"
        )
        assert receipt["baseline"] == {".idea": baseline[".idea"]}
        assert receipt["observed"] == {".idea": protected[".idea"]}, (
            "Metadata fingerprint changed again; reconcile explicitly"
        )
        preserved = {
            "path": str(receipt_path.relative_to(ROOT)),
            "sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        }
    gates = [
        "B",
        "R-real-runtime",
        "D",
        "P-real-data-network",
        "H-option-choice",
        "H-final-decision",
        "L-live-fetch",
        "L-STT-OS-authorization",
        "L-listening-verification",
        "runtime-reviewer-step05",
        "S",
    ]
    manifest = {
        "schema_version": 1,
        "step_id": "04",
        "accepted_at": prior_manifest["accepted_at"] if prior_manifest else now(),
        "status": "partial",
        "execution": "technical_media_ready_STT_listening_blocked",
        "source_hashes": suite["input_hashes"],
        "tests_passed": passed,
        "tests_skipped": skipped,
        "latest_suite_receipt": suite["path"],
        "scope": "Real local OCR/scan/video audio+frames and separate-context visual inspection in existing synthetic strategy case. Not live STT, field UX, runtime05 or business H.",
        "fixture_freeze_sha256": hashlib.sha256((run / "fixture-freeze.json").read_bytes()).hexdigest(),
        "processing_receipt": str((run / "processing-receipt.json").relative_to(ROOT)),
        "story_receipt": str(story_path.relative_to(ROOT)),
        "review_receipt": str((run / "review-receipt.json").relative_to(ROOT)),
        "fixture_case": {
            "project": story["project"],
            "case_id": story["case_id"],
            "state": counts,
            "snapshot_digest": status["data"]["snapshot_digest"],
            "pending_ref": revised["decision_ref"],
        },
        "gates": gates,
        "protected_trees": protected,
        "protected_changes_preserved": changed,
        "protected_delta_receipt": preserved,
        "limitations": [
            "All raw OCR/STT uncertain; no separate verification approval path",
            "Swift compiler cache/whole scratch quota and native decoder sandbox not proven",
            "Supplementary media prompt-injection agent trace not yet executed; S10 media remains open",
            "Original saved video extraction predates PTS guard; actual unchanged-fixture positive regression validates PTS guard, historical EXT not rewritten",
            "Metadata delta preserved with unknown origin; not all protected trees are claimed unchanged"
            if changed
            else "Protected trees unchanged against baseline",
        ],
        "next_action": "Start05 on stable media/ref/base contracts; preserve blocked adapters, H and inherited gates.",
        "usage": {
            "tokens": None,
            "money": None,
            "human_minutes": None,
            "unknown_reason": "Host accounting not exposed; local process durations are not product outcome cost",
        },
    }

    def update(current):
        step = current["steps"]["04"]
        step.update(
            status="partial",
            execution=manifest["execution"],
            updated_at=now(),
            gates=gates,
            next_action=manifest["next_action"],
            budget_used=manifest["usage"],
            evidence=[
                str(target.relative_to(ROOT)),
                suite["path"],
                manifest["processing_receipt"],
                manifest["story_receipt"],
                manifest["review_receipt"],
            ],
            accepted_subcontracts=[
                "bounded-local-image-scan-ocr-with-unverified-spans",
                "mp4-zero-start-cfr-frame-audio-derived-artifacts",
                "pinned-media-locators-and-UX-completion-unknown",
                "actual-sparse-before-dense-visual-inspection",
                "same-case-both-strategy-experiment-promise-update-pending-H",
            ],
            changed_files=sorted(
                set(suite["input_hashes"])
                - set(json.loads((ROOT / current["steps"]["03"]["evidence"][0]).read_text())["source_hashes"])
                | {
                    n
                    for n, h in suite["input_hashes"].items()
                    if json.loads((ROOT / current["steps"]["03"]["evidence"][0]).read_text())["source_hashes"].get(n)
                    != h
                }
            ),
            blockers=[
                {
                    "gate": "L-STT-OS-authorization",
                    "reason": "Apple Speech authorization=0; no prompts/cloud/model downloads allowed",
                    "unblocks": "Scoped OS authorization plus actual local STT receipt",
                },
                {
                    "gate": "L-listening-verification",
                    "reason": "No established actual listening tool; not inferred from transcript oracle",
                    "unblocks": "Permitted sample listening capability and actual verification",
                },
            ],
        )
        step["completed_units"].append(
            {
                "at": now(),
                "label": f"Partial media acceptance: {passed} passed/{skipped} blocked STT skip, actual same-case processing/visual/story and separate development review",
            }
        )
        for feature in ("F05", "F06"):
            for dimension in ("implementation", "offline", "live", "semantic", "acceptance"):
                current["features"][feature][dimension] = {
                    "status": "partial",
                    "scope": manifest["scope"],
                    "evidence": [str(target.relative_to(ROOT))],
                }
        current["steps"]["03"]["revalidated_by_step04"] = {
            "receipt": suite["path"],
            "scope": "All predecessor tests rerun; original manifests/history preserved",
        }
        current["revision"] += 1
        current["updated_at"] = now()
        validate_schema("development-progress", current)

    publish(ROOT, target, manifest, p["revision"], update)
    print(
        json.dumps(
            {
                "manifest": str(target.relative_to(ROOT)),
                "passed": passed,
                "skipped": skipped,
                "status": "partial",
                "counts": counts,
            }
        )
    )


if __name__ == "__main__":
    main()
