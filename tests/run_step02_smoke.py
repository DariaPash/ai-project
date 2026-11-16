"""Persistent actual CLI smoke in an isolated synthetic project, with receipts."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from tools.contracts import key, sha
from tools.development import ROOT, now, write_json
from tools.store import Store
from .helpers import make_project, write_request
from .step02_helpers import SOURCES, metric_spec, prepare, source_spec


def main():
    progress = json.loads((ROOT / "planning/progress.json").read_text())
    assert Path(progress["active_run"]).parts[2] == "02"
    evidence = ROOT / progress["active_run"]
    folder = evidence / "smoke" / uuid.uuid4().hex
    project = make_project(folder / "project")
    prepare(project)
    case = "test-step02"
    commands = []
    success = False
    started = now()
    canary = project / "private-canary.txt"
    canary.write_bytes(b"SAFE TECHNICAL CANARY: no real secret.\n")
    canary_hashes = {sha(os.fsencode(str(canary))), sha(b"private-canary.txt")}

    def invoke(*args, expected=0):
        result = subprocess.run(
            [sys.executable, "-m", "tests.traced_cli", *map(str, args)],
            cwd=project,
            env={"PATH": os.defpath, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            text=True,
            timeout=25,
        )
        value = json.loads(result.stdout)
        trace = json.loads(
            next(
                line.removeprefix("AUDIT_TRACE=")
                for line in result.stderr.splitlines()
                if line.startswith("AUDIT_TRACE=")
            )
        )
        commands.append(
            {
                "arguments": list(map(str, args)),
                "exit": result.returncode,
                "expected_exit": expected,
                "stdout": value,
                "stderr": result.stderr,
                "audit": trace,
                "at": now(),
            }
        )
        assert result.returncode == expected, (args, result.stdout, result.stderr)
        assert not trace["network_events"] and not canary_hashes.intersection(trace["opened_path_hashes"])
        return value

    def fresh():
        return invoke("status", "--case", case)["case_revision"]

    def record(kind, payload, name):
        filename = write_request(project, {"payload": payload}, case=case, name=name)
        return invoke("record", "--case", case, "--kind", kind, "--file", filename, "--expected-revision", fresh())

    try:
        invoke("doctor")
        invoke("init", "--case", case, "--namespace", "test")
        record(
            "brief",
            {
                "goal": "Verify synthetic source locators and Q/E calculations; preserve incompatible definitions, not infer market demand",
                "constraints": [
                    "Local technical fixtures only",
                    "No real HTTPS approval, no publication or paid model calls",
                ],
                "open_questions": [
                    "Which activation definition would apply to a real product?",
                    "Real baseline and live-source permission remain unknown",
                ],
            },
            "brief.json",
        )
        imported = {}
        for item in SOURCES["sources"]:
            name = item["name"]
            path, spec = source_spec(name)
            filename = write_request(project, spec, case=case, name="ingest-" + name + ".json")
            imported[name] = invoke(
                "ingest", "--case", case, "--path", path, "--spec", filename, "--expected-revision", fresh()
            )["data"]
        path, spec = source_spec("policy-v1")
        repeated = invoke(
            "ingest",
            "--case",
            case,
            "--path",
            path,
            "--spec",
            f"cases/{case}/requests/ingest-policy-v1.json",
            "--expected-revision",
            fresh(),
        )
        assert repeated["data"]["reused"]
        inputs = {
            name: {**{k: imported[name][k] for k in ("source_ref", "extraction_ref", "source_sha256")}, "sheet": "csv"}
            for name in ("registrations", "d7", "activations", "economics")
        }
        calculations = {}
        for operation in ("cohorts", "segments", "funnel", "economics", "scenarios", "sensitivity"):
            filename = write_request(
                project, metric_spec(operation, inputs), case=case, name="metrics-" + operation + ".json"
            )
            calculations[operation] = invoke(
                "metrics", "--case", case, "--spec", filename, "--expected-revision", fresh()
            )["data"]
        repeat = invoke(
            "metrics",
            "--case",
            case,
            "--spec",
            f"cases/{case}/requests/metrics-cohorts.json",
            "--expected-revision",
            fresh(),
        )
        assert repeat["data"]["reused"]
        conflict = invoke("search", "--case", case, "--query", "Activation means")
        injection = invoke("search", "--case", case, "--query", "UNTRUSTED FIXTURE")
        first = next(h for h in conflict["data"]["hits"] if "24 hours" in h["locator"]["exact_quote"])
        second = next(h for h in conflict["data"]["hits"] if "7 calendar days" in h["locator"]["exact_quote"])
        assert first["primary_publication"] == second["primary_publication"] == "fixture-activation-policy"
        assert injection["data"]["hits"] and all(
            h["origin_roots"] == ["synthetic_fixture"] for h in injection["data"]["hits"]
        )
        record(
            "claim",
            {
                "text": "Synthetic policy versions define incompatible activation events/windows; do not pool rates. Machine-smoke candidate, not independent semantic review.",
                "type": "interpretation",
                "status": "unverified",
                "origin": "synthetic_fixture",
                "evidence": [{"ref": h["source_ref"], "locator": h["locator"]} for h in (first, second)],
                "counterevidence": [],
                "basis_refs": [],
                "limitations": [
                    "Synthetic fixture; not real-demand evidence",
                    "Common publication group is not independent corroboration",
                ],
            },
            "conflict-candidate.json",
        )
        record(
            "action",
            {
                "operation": "note",
                "note": "Local Q/E/source checks completed; semantic review by current agent is next, live fetch permission absent",
                "runtime": {
                    "stage": "sources_and_analytics",
                    "next_action": "Current agent reviews pinned synthetic conflict; live fetch stays blocked",
                    "open_questions": ["Official brief, real baseline and live URL permission absent"],
                },
            },
            "next-action.json",
        )
        invoke("search", "--case", case, "--query", "activation", "--discovery", expected=3)
        invoke(
            "checkpoint",
            "--case",
            case,
            "--reason",
            "Local step02 smoke; synthetic data and live-fetch blocker preserved",
            "--expected-revision",
            fresh(),
        )
        before = invoke("status", "--case", case)
        after = invoke("status", "--case", case)
        assert before["data"]["snapshot_digest"] == after["data"]["snapshot_digest"]
        invoke("validate", "--case", case)
        with Store(project, case) as store:
            snapshot, _, _ = store._load()
            records = store.records(snapshot)
            parser_traces = []
            for record_value in records.values():
                if record_value["kind"] == "extraction":
                    trace = record_value["payload"]["coverage"]["security_trace"]
                    assert trace["network_attempts"] == trace["spawn_attempts"] == 0 and not trace["truncated"]
                    assert not canary_hashes.intersection(trace["opened_path_hashes"])
                    parser_traces.append(
                        {
                            "extraction_ref": {"case_id": case, "entity_id": record_value["id"], "revision": 1},
                            "trace": trace,
                        }
                    )
            ledger_counts = {
                "case_revision": snapshot["case_revision"],
                "committed_actions": len(snapshot["actions"]),
                "network_attempts": len(snapshot["attempts"]),
                "journal_errors": sum(row["type"] == "ERROR" for row in store.rows),
            }
        write_json(
            folder / "outputs.json",
            {
                "imports": imported,
                "calculations": calculations,
                "conflict_search": conflict,
                "injection_search": injection,
                "ledger_counts": ledger_counts,
                "parser_traces": parser_traces,
            },
        )
        success = True
    finally:
        receipt = {
            "started_at": started,
            "finished_at": now(),
            "actual": True,
            "tier": "offline_real_tool",
            "status": "passed" if success else "failed",
            "project": str(project.relative_to(ROOT)),
            "case_id": case,
            "commands": commands,
            "canary_is_synthetic": True,
            "canary_path_hashes": sorted(canary_hashes),
            "limitations": [
                "Python-process audit only, not an OS-wide/native-extension sandbox proof",
                "Local synthetic processing; no live HTTPS, no new agent context or independent review",
            ],
        }
        write_json(folder / "receipts.json", receipt)
        if success:
            write_json(
                evidence / "latest-smoke.json",
                {
                    "receipt": str((folder / "receipts.json").relative_to(ROOT)),
                    "outputs": str((folder / "outputs.json").relative_to(ROOT)),
                    "project": str(project.relative_to(ROOT)),
                    "case_id": case,
                },
            )
    print(
        json.dumps(
            {
                "status": "passed",
                "receipt": str((folder / "receipts.json").relative_to(ROOT)),
                "ledger_counts": ledger_counts,
            }
        )
    )


if __name__ == "__main__":
    main()
