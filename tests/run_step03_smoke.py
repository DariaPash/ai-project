"""Persistent actual tools: full fixture lifecycle and actual host-artifact path.

The CLI does NOT generate model turns. It imports the preceding real host output;
fixture simulations/approvals and host execution are kept in separate projects.
"""

import json
from pathlib import Path
import uuid

from tools.contracts import key, sha, target_digest
from tools.development import ROOT, now, write_json
from tools.safeio import canonical
from tools.store import Store, unknown_usage
from .helpers import make_project
from . import helpers
from . import step03_helpers as workflow


def snapshot(root, case):
    with Store(root, case) as store:
        checked = store.validate()
        snap, _, _ = store._load()
        return {
            "case_revision": snap["case_revision"],
            "snapshot_digest": checked["data"]["snapshot_digest"],
            "record_count": len(snap["records"]),
            "action_count": len(snap["actions"]),
            "network_attempt_count": len(snap["attempts"]),
            "journal_error_count": sum(r["type"] == "ERROR" for r in store.rows),
        }


def main():
    progress = json.loads((ROOT / "planning/progress.json").read_text())
    evidence = ROOT / progress["active_run"]
    assert "/03/" in progress["active_run"]
    folder = evidence / "integration" / uuid.uuid4().hex
    commands = []
    original = helpers.cli

    def traced(root, *args, **kwargs):
        process, result = original(root, *args, **kwargs)
        commands.append(
            {
                "project": str(Path(root).relative_to(ROOT)),
                "arguments": list(map(str, args)),
                "exit": process.returncode,
                "stdout": result,
                "stderr": process.stderr,
                "at": now(),
            }
        )
        return process, result

    helpers.cli = workflow.cli = traced
    started = now()
    success = False
    try:
        fixture = workflow.complete_fixture(
            workflow.add_options(workflow.build_research(make_project(folder / "fixture"), via_cli=True))
        )
        traced(
            fixture.root,
            "checkpoint",
            "--case",
            fixture.case,
            "--reason",
            "Full fixture lifecycle, not real H or real role execution",
            "--expected-revision",
            fixture.status()["case_revision"],
        )
        fixture_state = snapshot(fixture.root, fixture.case)
        host = workflow.build_research(make_project(folder / "host"), via_cli=True)
        start = json.loads((evidence / "host-execution-start.json").read_text())
        ended = now()
        roles = []
        for filename in ("manager.json", "operator.json", "buyer.json"):
            raw = (evidence / "host-roles" / filename).read_bytes()
            generated = json.loads(raw)
            usage = unknown_usage()
            usage["model"] = start["model"]
            payload = {
                "contract_version": 3,
                "execution_id": str(uuid.uuid5(uuid.NAMESPACE_URL, start["started_at"] + ":" + sha(raw))),
                **generated,
                "input_refs": [host.analysis, host.conflict, host.imports["capabilities.txt"]["source_ref"]],
                "execution": {
                    "mode": "host_inline",
                    "model": start["model"],
                    "started_at": start["started_at"],
                    "ended_at": ended,
                    "usage": usage,
                    "context_independence": "not_independent",
                },
            }
            transcript = host.artifact(
                canonical(payload), payload["input_refs"], origin="model_simulation", processing="LLM-assisted"
            )
            reference = host.record("simulation", {**payload, "transcript_ref": transcript})
            roles.append(reference)
        # Model analysis was written by the current host before this script. It
        # is not a source of real-world evidence and never a human approval.
        analysis_bytes = (evidence / "host-analysis.md").read_bytes()
        report = host.artifact(
            analysis_bytes,
            [host.analysis, host.conflict, *roles],
            origin="model_simulation",
            media="text/markdown",
            processing="LLM-assisted",
        )
        host.record(
            "claim",
            {
                "text": "The actual current-host analysis treats manual review as a testable corpus theme, retains the fast-completion counterexample and privacy/coordination alternatives; no real demand or baseline is established.",
                "type": "interpretation",
                "status": "unverified",
                "origin": "model_simulation",
                "evidence": [host.quote("interview-1.txt", 3), host.quote("interview-2.txt", 3)],
                "counterevidence": [host.quote("interview-3.txt", 3)],
                "basis_refs": [host.analysis, report, *roles],
                "limitations": [
                    "Actual host analysis on artificial text; author not blinded; not fieldwork, independent respondent contexts or real H"
                ],
            },
        )
        workflow.add_options(host, roles)
        request = {
            "scope": "option_choice",
            "targets": host.choice_targets,
            "terms": host.choice_terms,
            "question": "Hypothetical improve direction is only a recommendation. Product user: approve/reject/revise this exact four-option/criteria bundle? No response has been received.",
            "status": "requested",
            "target_digest": target_digest("option_choice", host.choice_targets, host.records(), host.choice_terms),
        }
        approval_request = host.record("approval", request)
        host.record(
            "action",
            {
                "operation": "note",
                "note": "Real host-inline technical model outputs imported; no actual H or external API execution",
                "runtime": {
                    "stage": "awaiting_option_choice",
                    "awaiting_human": "option_choice",
                    "next_action": "Obtain a real product-user response to the exact option_choice bundle; do not create strategies/confirmed DEC before that live gate",
                },
            },
        )
        traced(
            host.root,
            "checkpoint",
            "--case",
            host.case,
            "--reason",
            "Actual host path stops on real H; fixture full path is separate",
            "--expected-revision",
            host.status()["case_revision"],
        )
        before = host.status()
        after = traced(host.root, "status", "--case", host.case)[1]
        assert before["data"]["snapshot_digest"] == after["data"]["snapshot_digest"]
        records = host.records()
        assert not any(r["kind"] == "decision" for r in records.values())
        assert all(records[key(r)]["payload"]["execution"]["mode"] == "host_inline" for r in roles)
        assert after["data"]["state"]["awaiting_human"] == "option_choice"
        host_state = snapshot(host.root, host.case)
        write_json(
            folder / "outputs.json",
            {
                "fixture": {
                    "project": str(fixture.root.relative_to(ROOT)),
                    "case_id": fixture.case,
                    "confirmed_ref": fixture.confirmed,
                    "product_ref": fixture.product,
                    "communication_ref": fixture.communication,
                    "state": fixture_state,
                },
                "host": {
                    "project": str(host.root.relative_to(ROOT)),
                    "case_id": host.case,
                    "role_refs": roles,
                    "analysis_artifact_ref": report,
                    "approval_request_ref": approval_request,
                    "state": host_state,
                    "actual_model": "openai/gpt-6.1-sol",
                    "context_independence": "not_independent",
                    "no_separate_paid_API": True,
                    "observer_key_in_generator_inputs": False,
                },
                "input_hashes": {
                    str(p.relative_to(ROOT)): sha(p.read_bytes())
                    for p in [evidence / "host-analysis.md", *sorted((evidence / "host-roles").glob("*.json"))]
                },
            },
        )
        success = True
    finally:
        helpers.cli = workflow.cli = original
        write_json(
            folder / "receipts.json",
            {
                "actual": True,
                "status": "passed" if success else "failed",
                "started_at": started,
                "finished_at": now(),
                "commands": commands,
                "limits": [
                    "Fixture approvals never real H; host path awaiting direction choice",
                    "Host log consistency checked structurally, no cryptographic provider attestation; three roles one actual leading context",
                    "No blind generation, market inference, separate API model calls or independent-respondent claim",
                ],
            },
        )
        if success:
            write_json(
                evidence / "latest-integration.json",
                {
                    "receipts": str((folder / "receipts.json").relative_to(ROOT)),
                    "outputs": str((folder / "outputs.json").relative_to(ROOT)),
                },
            )
    print(
        json.dumps(
            {
                "status": "passed",
                "receipts": str((folder / "receipts.json").relative_to(ROOT)),
                "fixture": fixture_state,
                "host": host_state,
            }
        )
    )


if __name__ == "__main__":
    main()
