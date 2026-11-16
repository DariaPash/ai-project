"""Persist actual separate-context visual findings in the SAME accepted fixture."""

import json
from tools.contracts import key, sha
from tools.development import ROOT, write_json, now
from tools.store import Store
from .step03_helpers import Fixture
from .step04_update import update


def main():
    p = json.loads((ROOT / "planning/progress.json").read_text())
    run = ROOT / p["active_run"]
    target = run / "story-update-receipt.json"
    assert not target.exists(), "Inspect existing receipt; no blind duplicate story update"
    processed = json.loads((run / "processing-receipt.json").read_text())
    previous = json.loads((ROOT / p["steps"]["03"]["evidence"][0]).read_text())["fixture_case"]
    f = Fixture(ROOT / processed["project"], processed["case_id"])
    recovery_path = run / "story-recovery.json"
    if recovery_path.exists():
        recovery = json.loads(recovery_path.read_text())
        assert f.status()["data"]["snapshot_digest"] == recovery["status"]["data"]["snapshot_digest"], (
            "Recovery snapshot changed; inspect journal again"
        )
        refs = recovery["records"]
        revised = {
            "claim_ref": refs["CLM-002@1"],
            "research_plan_ref": refs["RPL-002@1"],
            "question_ref": refs["QST-004@1"],
            "experiment_ref": refs["EXP-001@2"],
            "strategy_refs": [refs["STR-001@2"], refs["STR-002@2"]],
            "promise_refs": [refs["PRM-001@2"]],
            "decision_ref": refs["DEC-001@3"],
            "approval_request_ref": refs["APR-005@1"],
        }
        finish_recording(f, run, target, processed, refs["UXO-001@1"], refs["UXO-002@1"], refs["UXJ-001@1"], revised)
        return
    assert f.status()["data"]["snapshot_digest"] == processed["after"]["data"]["snapshot_digest"]
    f.confirmed = previous["confirmed_ref"]
    f.product = previous["product_ref"]
    f.communication = previous["communication_ref"]
    confirmed = f.records()[key(f.confirmed)]["payload"]
    f.proposal = confirmed["approved_proposal_ref"]
    f.experiment = confirmed["experiment_ref"]
    image = processed["imports"]["screen"]["result"]["data"]
    source = f.records()[key(image["source_ref"])]
    ux = f.record(
        "ux_observation",
        {
            "contract_version": 4,
            "source_ref": image["source_ref"],
            "artifact_ref": source["payload"]["artifact_ref"],
            "artifact_sha256": source["payload"]["sha256"],
            "width": 960,
            "height": 540,
            "orientation": "top_left_pixels",
            "bbox": [35, 350, 220, 80],
            "journey_step": "First static step only",
            "visible_observation": "Separate visual context actually read the pixels: STEP 1 OF 3 and NEXT rectangle; EXPORT PLANNED and NOT AVAILABLE. No button interaction observed.",
            "hypothesis": "NEXT might be read as a button and planned/unavailable wording might need clarification; no observed participant establishes a barrier.",
            "test": "After consent, ask a participant to explain export availability and perform a full task in a working UI; record actual action/outcome.",
            "limitations": [
                "Owned synthetic screenshot, not real usage",
                "Read sample is not raw OCR correction or evidence of demand",
            ],
            "completion_status": "unknown",
        },
    )
    dense = processed["imports"]["dense"]
    dm = dense["extraction"]["payload"]["coverage"]["media"]
    child = next(c for c in dm["children"] if c["mapping"]["timestamp_ms"] == 5200)
    event = f.record(
        "ux_observation",
        {
            "contract_version": 4,
            "source_ref": dense["result"]["data"]["source_ref"],
            "artifact_ref": child["artifact_ref"],
            "artifact_sha256": child["sha256"],
            "width": 960,
            "height": 540,
            "orientation": "top_left_pixels",
            "bbox": [680, 350, 180, 80],
            "timestamp_ms": 5200,
            "journey_step": "Sampled appearance, no task transition observed",
            "visible_observation": "Actual dense-frame visual review sees a red rectangle at 5200/5300/5400/5500ms; absent on 5100/5600ms and previously presented sparse frames.",
            "hypothesis": "Meaning of the color block is unknown; it is not established as an error, notification, click or completion.",
            "test": "Inspect continuous permitted capture/event log and working UI before attributing behavior.",
            "limitations": [
                "Boundaries only bracketed by adjacent frames",
                "No full visual coverage or causal/behavioral inference",
            ],
            "completion_status": "unknown",
        },
    )
    journey = f.record(
        "ux_journey",
        {
            "contract_version": 4,
            "steps": [
                {"label": "Static first step", "observation_ref": ux},
                {"label": "Sampled appearance only", "observation_ref": event},
            ],
            "unobserved_transitions": [
                "NEXT activation",
                "Steps2/3 and final handoff",
                "Exact onset/offset or continuity between sampled frames",
            ],
            "completion_status": "unknown",
            "limitations": ["These are observations, not a demonstrated task journey or actual user study"],
        },
    )
    sources = list(
        {
            key(item["result"]["data"]["source_ref"]): item["result"]["data"]["source_ref"]
            for item in processed["imports"].values()
        }.values()
    )
    revised = update(f, sources, ux, journey)
    finish_recording(f, run, target, processed, ux, event, journey, revised)


def finish_recording(f, run, target, processed, ux, event, journey, revised):
    receipts = []
    for name in ("sparse-visual-review.md", "dense-visual-review.md"):
        raw = (run / name).read_bytes()
        receipts.append(
            {
                "file": str((run / name).relative_to(ROOT)),
                "sha256": sha(raw),
                "artifact_ref": f.artifact(
                    raw,
                    parents=[ux, event, journey],
                    media="text/markdown",
                    origin="model_simulation",
                    processing="LLM-assisted",
                ),
            }
        )
    with Store(f.root, f.case) as store:
        checkpoint = store.checkpoint(
            "Media/visual limitations revised both strategies and experiment; await exact reconsideration approval; no real H inferred",
            store.status()["case_revision"],
        )
        after = store.validate()
        snapshot, _, _ = store._load()
        counts = {
            "case_revision": snapshot["case_revision"],
            "committed_actions": len(snapshot["actions"]),
            "records": len(snapshot["records"]),
            "network_attempts": len(snapshot["attempts"]),
            "journal_errors": sum(r["type"] == "ERROR" for r in store.rows),
        }
    write_json(
        target,
        {
            "at": now(),
            "actual": True,
            "project": processed["project"],
            "case_id": f.case,
            "perception_session_id": "ses_e256707f5ffe535rdI8c6PqRMe",
            "perception_calls": 2,
            "sparse_before_dense": True,
            "oracle_passed_to_perception": False,
            "visual_receipts": receipts,
            "ux_ref": ux,
            "event_ref": event,
            "journey_ref": journey,
            "revised": revised,
            "checkpoint": checkpoint,
            "state": after,
            "counts_from_journal": counts,
            "real_H": False,
            "tokens": None,
            "money": None,
            "human_minutes": None,
            "unknown_reason": "Host accounting not exposed; not zero cost",
        },
    )
    print(json.dumps({"receipt": str(target.relative_to(ROOT)), "counts": counts, "revised": revised}))


if __name__ == "__main__":
    main()
