"""Persist fresh leading-host outputs after the already committed research plan.

No generation happens here; model-authored source logs precede this script.
"""

import copy
import json
import uuid
from tools.contracts import key, ref, sha, target_digest
from tools.development import ROOT, now, write_json
from tools.safeio import canonical
from tools.store import Store, unknown_usage
from . import helpers
from . import step03_helpers as workflow
from .run_step03_smoke import snapshot


def main():
    progress = json.loads((ROOT / "planning/progress.json").read_text())
    evidence = ROOT / progress["active_run"]
    marker = json.loads((evidence / "ordered-host-start.json").read_text())
    dest = evidence / "ordered-host-receipt.json"
    assert not dest.exists(), "Existing host execution must not be replayed as a new one"
    project = ROOT / marker["project"]
    f = workflow.Fixture(project, marker["case_id"], via_cli=True)
    records = f.records()
    assert records[key(marker["research_plan_ref"])]["created_at"] < marker["at"]
    before = f.status()
    assert before["case_revision"] == marker["intent_result"]["case_revision"]
    source_before = {r["id"]: r["revision"] for r in records.values() if r["kind"] == "source"}
    f.plan = marker["research_plan_ref"]
    f.analysis = next(ref(r) for r in records.values() if r["kind"] == "interview_analysis")
    f.guide = records[key(f.analysis)]["payload"]["guide_ref"]
    f.conflict = next(
        ref(r) for r in records.values() if r["kind"] == "claim" and r["payload"]["origin"] == "synthetic_fixture"
    )
    f.calculations = [ref(r) for r in records.values() if r["kind"] == "calculation"]
    f.imports = {}
    for source in records.values():
        if source["kind"] == "source" and source["payload"]["location"].startswith("tests/fixtures/research/"):
            extraction = next(
                r for r in records.values() if r["kind"] == "extraction" and r["payload"]["source_ref"] == ref(source)
            )
            f.imports[source["payload"]["location"].split("/")[-1]] = {
                "source_ref": ref(source),
                "extraction_ref": ref(extraction),
                "source_sha256": source["payload"]["sha256"],
            }
    commands = []
    original = helpers.cli

    def traced(root, *args, **kwargs):
        process, result = original(root, *args, **kwargs)
        commands.append(
            {
                "arguments": list(map(str, args)),
                "exit": process.returncode,
                "stdout": result,
                "stderr": process.stderr,
                "at": now(),
            }
        )
        return process, result

    helpers.cli = workflow.cli = traced
    try:
        analysis = copy.deepcopy(records[key(f.analysis)]["payload"])
        analysis["themes"][0]["interpretation"] = (
            "Actual ordered leading-host analysis: the two located passages justify checking manual verification cost within this artificial corpus, not a real market rate or measured baseline"
        )
        analysis["themes"][0]["alternative"] = (
            "Waiting for colleagues and privacy/admissible input may dominate editing effort; the quick completion in I3 is a counterexample"
        )
        analysis["limitations"] = [
            "Actual current-host followup after committed RPL, not a Python-generated analysis or independent context",
            "Artificial text only; no fieldwork, real consent, market prevalence or actual sales baseline",
        ]
        f.analysis = f.record("interview_analysis", analysis, f.analysis["entity_id"])
        raw_report = (evidence / "ordered-host/analysis.md").read_bytes()
        report = f.artifact(
            raw_report,
            [f.analysis, f.conflict],
            origin="model_simulation",
            media="text/markdown",
            processing="LLM-assisted",
        )
        ended = now()
        roles = []
        for filename in ("manager.json", "operator.json", "buyer.json"):
            raw = (evidence / "ordered-host" / filename).read_bytes()
            authored = json.loads(raw)
            usage = unknown_usage()
            usage["model"] = marker["model"]
            payload = {
                "contract_version": 3,
                "execution_id": str(uuid.uuid5(uuid.NAMESPACE_URL, marker["at"] + ":" + sha(raw))),
                **authored,
                "input_refs": [f.analysis, report, f.conflict, f.imports["capabilities.txt"]["source_ref"]],
                "execution": {
                    "mode": "host_inline",
                    "model": marker["model"],
                    "started_at": marker["at"],
                    "ended_at": ended,
                    "usage": usage,
                    "context_independence": "not_independent",
                },
            }
            artifact = f.artifact(
                canonical(payload), payload["input_refs"], origin="model_simulation", processing="LLM-assisted"
            )
            roles.append(f.record("simulation", {**payload, "transcript_ref": artifact}))
        f.record(
            "claim",
            {
                "text": "Ordered host followup preserves manual-review theme, fast-completion counterexample and coordination/privacy alternatives; model roles are hypotheses and not human direction choice",
                "type": "interpretation",
                "status": "unverified",
                "origin": "model_simulation",
                "evidence": [f.quote("interview-1.txt", 3), f.quote("interview-2.txt", 3)],
                "counterevidence": [f.quote("interview-3.txt", 3)],
                "basis_refs": [f.analysis, report, *roles],
                "limitations": [
                    "Same current host context, not blinded or fieldwork; real baseline and both H remain unknown"
                ],
            },
        )
        workflow.add_options(f, roles)
        request = f.record(
            "approval",
            {
                "scope": "option_choice",
                "targets": f.choice_targets,
                "terms": f.choice_terms,
                "target_digest": target_digest("option_choice", f.choice_targets, f.records(), f.choice_terms),
                "question": "Revised technical four-option bundle after ordered host analysis. Approve/reject/revise? No product-user response has been received; earlier draft request is retained as unanswered history.",
                "status": "requested",
            },
        )
        f.record(
            "action",
            {
                "operation": "note",
                "note": "Ordered model output saved after committed RPL; prior draft requests/turns retained, not replayed or represented as human receipts",
                "runtime": {
                    "stage": "awaiting_option_choice",
                    "awaiting_human": "option_choice",
                    "next_action": "Obtain the real product-user response to "
                    + request["entity_id"]
                    + " exact bundle; do not produce live strategies/DEC without H",
                },
            },
        )
        traced(
            project,
            "checkpoint",
            "--case",
            f.case,
            "--reason",
            "Ordered host followup saved; first real H unanswered",
            "--expected-revision",
            f.status()["case_revision"],
        )
        final = snapshot(project, f.case)
        after = f.records()
        assert source_before == {r["id"]: r["revision"] for r in after.values() if r["kind"] == "source"}
        assert not any(r["kind"] == "decision" for r in after.values())
        assert f.status()["data"]["state"]["awaiting_human"] == "option_choice"
        write_json(
            dest,
            {
                "actual": True,
                "project": marker["project"],
                "case_id": f.case,
                "plan_ref": f.plan,
                "plan_committed_before_generation": True,
                "intent_ref": marker["intent_result"]["data"]["ref"],
                "marker_at": marker["at"],
                "saved_at": now(),
                "role_refs": roles,
                "analysis_ref": f.analysis,
                "analysis_artifact_ref": report,
                "option_refs": f.options,
                "sensitivity_artifact_ref": f.sensitivity_ref,
                "approval_request_ref": request,
                "before_revision": before["case_revision"],
                "after": final,
                "sources_unchanged": True,
                "commands": commands,
                "input_hashes": {
                    str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in sorted((evidence / "ordered-host").glob("*"))
                },
                "limitations": [
                    "Same leading context, actual generated turns not separate paid API calls",
                    "No evaluator key in generation package; author prepared corpus, no blind claim",
                    "Original draft logs and unanswered request retained; zero actual human approvals or fieldwork",
                ],
            },
        )
    finally:
        helpers.cli = workflow.cli = original
    print(
        json.dumps(
            {
                "receipt": str(dest.relative_to(ROOT)),
                "after": final,
                "awaiting_human": "option_choice",
                "roles": len(roles),
            }
        )
    )


if __name__ == "__main__":
    main()
