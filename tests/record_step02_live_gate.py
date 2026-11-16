"""Record actual CLI policy denial without attempting DNS or an external call."""

import json

from tools.development import ROOT, now, write_json
from .helpers import cli, write_request
from .step02_helpers import source_spec


def main():
    progress = json.loads((ROOT / "planning/progress.json").read_text())
    evidence = ROOT / progress["active_run"]
    destination = evidence / "live-gate-receipt.json"
    if destination.exists():
        raise SystemExit("Gate receipt exists; inspect/reuse it")
    smoke = json.loads((evidence / "latest-smoke.json").read_text())
    project = ROOT / smoke["project"]
    case = smoke["case_id"]
    before = cli(project, "status", "--case", case)[1]
    _, ingest = source_spec("html")
    spec = {
        "schema_version": 1,
        "source_access_approval_ref": {"case_id": case, "entity_id": "APR-001", "revision": 1},
        "permission_ref": {"case_id": case, "entity_id": "PER-001", "revision": 1},
        "ingest": ingest,
        "limits": {
            "max_bytes": 1000,
            "timeout_ms": 1000,
            "connect_timeout_ms": 500,
            "max_hops": 0,
            "allowed_mime": ["text/html"],
        },
    }
    path = write_request(project, spec, case=case, name="blocked-fetch-spec.json")
    args = [
        "fetch",
        "--case",
        case,
        "--url",
        "https://example.org/",
        "--spec",
        path,
        "--expected-revision",
        str(before["case_revision"]),
    ]
    process, result = cli(project, *args, expected=4)
    after = cli(project, "status", "--case", case)[1]
    assert result["code"] == "DOMAIN_DENIED" and after["data"]["attempts"] == {}
    assert before["data"]["snapshot_digest"] == after["data"]["snapshot_digest"]
    write_json(
        destination,
        {
            "actual": True,
            "live_status": "blocked_not_executed",
            "attempt_kind": "CLI preflight only, no network attempt",
            "expected_exit": 4,
            "exit": process.returncode,
            "arguments": args,
            "stdout": result,
            "stderr": process.stderr,
            "before": before,
            "after": after,
            "project": smoke["project"],
            "at": now(),
        },
    )
    print(
        json.dumps(
            {
                "receipt": str(destination.relative_to(ROOT)),
                "expected_denial": result["code"],
                "network_attempts_from_ledger": len(after["data"]["attempts"]),
            }
        )
    )


if __name__ == "__main__":
    main()
