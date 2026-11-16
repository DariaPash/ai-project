"""Persist an already-written current-agent analysis; never generate its verdict."""

import json
from pathlib import Path

from tools.development import ROOT, now, write_json
from tools.store import Store
from .helpers import cli, write_request
from .step02_helpers import source_spec


def main():
    progress = json.loads((ROOT / "planning/progress.json").read_text())
    evidence = ROOT / progress["active_run"]
    smoke = json.loads((evidence / "latest-smoke.json").read_text())
    project = ROOT / smoke["project"]
    case = smoke["case_id"]
    destination = evidence / "semantic-receipts.json"
    if destination.exists():
        raise SystemExit("Semantic receipt already exists; inspect/reuse it, never overwrite")
    report = evidence / "semantic-analysis.md"
    assert report.is_file()
    commands = []

    def invoke(*args):
        process, value = cli(project, *args)
        commands.append(
            {
                "args": list(map(str, args)),
                "exit": process.returncode,
                "stdout": value,
                "stderr": process.stderr,
                "at": now(),
            }
        )
        return value

    def fresh():
        return invoke("status", "--case", case)["case_revision"]

    def record(kind, payload, name):
        request = write_request(project, {"payload": payload}, case=case, name=name)
        return invoke("record", "--case", case, "--kind", kind, "--file", request, "--expected-revision", fresh())

    input_path = project / f"cases/{case}/input/agent-semantic-analysis.md"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    assert not input_path.exists()
    input_path.write_bytes(report.read_bytes())
    _, spec = source_spec("policy-v1")
    spec["title"] = "Current-agent self-review of synthetic source conflict"
    spec["origin"] = "model_simulation"
    spec["primary_publication"] = "current-agent-self-review-not-primary-evidence"
    filename = write_request(project, spec, case=case, name="agent-analysis-spec.json")
    imported = invoke(
        "ingest",
        "--case",
        case,
        "--path",
        str(input_path.relative_to(project)),
        "--spec",
        filename,
        "--expected-revision",
        fresh(),
    )
    results = invoke("search", "--case", case, "--query", "Activation means")["data"]["hits"]
    first = next(
        h for h in results if h["source_ref"]["entity_id"] == "SRC-001" and "24 hours" in h["locator"]["exact_quote"]
    )
    second = next(
        h
        for h in results
        if h["source_ref"]["entity_id"] == "SRC-002" and "7 calendar days" in h["locator"]["exact_quote"]
    )
    claim = record(
        "claim",
        {
            "text": "In the technical fixtures, activation changed from meeting creation within 24 hours (declared 2026-10-20) to report export within 7 days (declared 2026-11-01); these rates cannot be pooled and the publication group is not independent corroboration.",
            "type": "interpretation",
            "status": "supported",
            "support_scope": "technical_fixture",
            "support_review": "Actual current-agent self-review in semantic-analysis.md; not independent or human approval",
            "origin": "model_simulation",
            "evidence": [{"ref": h["source_ref"], "locator": h["locator"]} for h in (first, second)],
            "counterevidence": [],
            "basis_refs": [
                imported["data"]["source_ref"],
                {"case_id": case, "entity_id": "CAL-001", "revision": 1},
                {"case_id": case, "entity_id": "CAL-003", "revision": 1},
            ],
            "limitations": [
                "Synthetic fixture only; no real-demand or causal support",
                "Publication dates are asserted in text, metadata remains unknown",
                "Machine evidence is not an independent primary publication",
            ],
        },
        "agent-semantic-claim.json",
    )
    record(
        "action",
        {
            "operation": "note",
            "note": "Current agent read the original fixtures and checked definitions, dates, root independence, missing data and causality; report saved, no independent reviewer",
            "runtime": {
                "stage": "sources_and_analytics",
                "next_action": "Await explicit step03 execution using local contracts; preserve live-fetch/B/R/D blockers",
                "open_questions": [
                    "Official brief, demo, runtime budget, real baseline and real URL permission remain unknown"
                ],
                "awaiting_human": None,
            },
        },
        "agent-semantic-action.json",
    )
    invoke(
        "checkpoint",
        "--case",
        case,
        "--reason",
        "Current-agent semantic self-review saved; local-ready/live-blocked step02",
        "--expected-revision",
        fresh(),
    )
    validated = invoke("validate", "--case", case)
    with Store(project, case) as store:
        snapshot, _, _ = store._load()
        counts = {
            "case_revision": snapshot["case_revision"],
            "committed_actions": len(snapshot["actions"]),
            "network_attempts": len(snapshot["attempts"]),
            "journal_errors": sum(row["type"] == "ERROR" for row in store.rows),
        }
    write_json(
        destination,
        {
            "actual": True,
            "analyst": "current GPT-6.1 Sol context; self-review, not independent/human approval",
            "report": str(report.relative_to(ROOT)),
            "claim_ref": claim["data"]["ref"],
            "report_source_ref": imported["data"]["source_ref"],
            "commands": commands,
            "ledger_counts": counts,
            "validated_snapshot_digest": validated["data"]["snapshot_digest"],
            "finished_at": now(),
        },
    )
    print(json.dumps({"receipt": str(destination.relative_to(ROOT)), "ledger_counts": counts}))


if __name__ == "__main__":
    main()
