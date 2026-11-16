"""Correct a proven host timestamp-label error with immutable revisions, not rewrite."""

import copy
import json
from tools.contracts import key, sha, target_digest
from tools.development import ROOT, now, write_json
from tools.store import Store
from .step03_helpers import Fixture


def main():
    p = json.loads((ROOT / "planning/progress.json").read_text())
    run = ROOT / p["active_run"]
    target = run / "story-timing-corrected-receipt.json"
    assert not target.exists()
    story = json.loads((run / "story-update-receipt.json").read_text())
    f = Fixture(ROOT / story["project"], story["case_id"])
    status = f.status()
    assert status["data"]["snapshot_digest"] == story["state"]["data"]["snapshot_digest"], (
        "Inspect changed journal before correction"
    )
    print((f.root / f"cases/{f.case}/handoff.md").read_text())
    records = f.records()
    changes = {}

    def replace(value):
        if isinstance(value, dict):
            if set(value) == {"case_id", "entity_id", "revision"}:
                return changes.get(key(value), value)
            return {k: replace(v) for k, v in value.items()}
        if isinstance(value, list):
            return [replace(v) for v in value]
        return value

    def revision(old_ref, kind, payload):
        new = f.record(kind, payload, old_ref["entity_id"])
        changes[key(old_ref)] = new
        return new

    event = copy.deepcopy(records[key(story["event_ref"])]["payload"])
    event["visible_observation"] = (
        "Actual dense pixels show red rectangle on indices02–05 at decoded-frame times5200/5280/5400/5520ms; absent on adjacent frames5120/5600ms. Original host prompt incorrectly labelled requested nominal times as actual."
    )
    event["limitations"] += [
        "Timing correction relabels the same actually viewed image bytes, not a new perception; exact onset/offset/continuity remain unknown."
    ]
    new_event = revision(story["event_ref"], "ux_observation", event)
    new_journey = revision(story["journey_ref"], "ux_journey", replace(records[key(story["journey_ref"])]["payload"]))
    revised = copy.deepcopy(story["revised"])
    revised["claim_ref"] = revision(
        revised["claim_ref"], "claim", replace(records[key(revised["claim_ref"])]["payload"])
    )
    revised["question_ref"] = revision(
        revised["question_ref"], "question", replace(records[key(revised["question_ref"])]["payload"])
    )
    revised["research_plan_ref"] = revision(
        revised["research_plan_ref"], "research_plan", replace(records[key(revised["research_plan_ref"])]["payload"])
    )
    promises = []
    for reference in revised["promise_refs"]:
        payload = replace(records[key(reference)]["payload"])
        payload["qualification"] += (
            " Frame evidence uses actual timestamps with requested/actual offsets; nominal sampling targets are not observed instants."
        )
        promises.append(revision(reference, "promise", payload))
    revised["promise_refs"] = promises
    experiment = copy.deepcopy(records[key(revised["experiment_ref"])]["payload"])
    experiment["limitations"] += [
        "Use actual decoded-frame timestamps, not nominal targets; observe continuous task before timing behavior."
    ]
    revised["experiment_ref"] = revision(revised["experiment_ref"], "experiment", experiment)
    strategies = []
    for reference in revised["strategy_refs"]:
        old = records[key(reference)]["payload"]
        sections = copy.deepcopy(old["sections"])
        field = "dependencies" if old["strategy_type"] == "product" else "forbidden_promises"
        sections[field] += (
            " Timing correction: requested frame times may round to actual decoded instants; no continuous-behavior claim."
        )
        new = f.strategy(
            old["strategy_type"],
            old["selected_option_ref"],
            old["option_choice_ref"],
            replace(old["basis_refs"]),
            sections,
            entity_id=reference["entity_id"],
        )
        changes[key(reference)] = new
        strategies.append(new)
    revised["strategy_refs"] = strategies
    old_decision = revised["decision_ref"]
    payload = replace(records[key(old_decision)]["payload"])
    payload.update(
        status="pending", strategy_refs=strategies, experiment_ref=revised["experiment_ref"], promise_refs=promises
    )
    revised["decision_ref"] = revision(old_decision, "decision", payload)
    request = {
        "scope": "reconsideration",
        "targets": [revised["decision_ref"]],
        "terms": {},
        "question": "Approve/reject/revise this exact timing-corrected proposal; no real H is inferred.",
        "status": "requested",
    }
    request["target_digest"] = target_digest("reconsideration", request["targets"], f.records(), {})
    revised["approval_request_ref"] = f.record("approval", request)
    raw = (run / "timing-correction.md").read_bytes()
    artifact = f.artifact(
        raw,
        parents=[new_event, new_journey],
        origin="model_simulation",
        processing="LLM-assisted",
        media="text/markdown",
    )
    with Store(f.root, f.case) as store:
        checkpoint = store.checkpoint(
            "Actual frame timestamp labels corrected; all affected outputs revised; await exact reconsideration H",
            store.status()["case_revision"],
        )
        checked = store.validate()
        snapshot, _, _ = store._load()
        counts = {
            "case_revision": snapshot["case_revision"],
            "committed_actions": len(snapshot["actions"]),
            "records": len(snapshot["records"]),
            "network_attempts": len(snapshot["attempts"]),
            "journal_errors": sum(r["type"] == "ERROR" for r in store.rows),
        }
    result = {
        **story,
        "at": now(),
        "supersedes_file": "story-update-receipt.json",
        "timing_correction": {
            "artifact_ref": artifact,
            "sha256": sha(raw),
            "file": "timing-correction.md",
            "third_model_call": "mapping correction only, not a new pixel inspection",
        },
        "perception_calls": 3,
        "event_ref": new_event,
        "journey_ref": new_journey,
        "revised": revised,
        "checkpoint": checkpoint,
        "state": checked,
        "counts_from_journal": counts,
    }
    write_json(target, result)
    print(json.dumps({"receipt": str(target.relative_to(ROOT)), "counts": counts, "revised": revised}))


if __name__ == "__main__":
    main()
