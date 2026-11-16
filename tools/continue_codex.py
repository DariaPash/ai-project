"""One owner-authorized text-only continuation in the installed second agent host."""

import json
import os
from pathlib import Path
import signal
import subprocess
import time
import uuid

from .contracts import sha, digest
from .development import ROOT, now, write_json
from .safeio import SafeRoot, canonical
from .store import Store
from .subscription_budget import snapshot
from .transfer import scoped_transfer


def main():
    progress = json.loads((ROOT / "planning/progress.json").read_text())
    evidence = ROOT / progress["active_run"]
    owner = json.loads((evidence / "owner-transfer-and-theme-receipt.json").read_text())
    destination = Path(owner["terms"]["destination_local_path"])
    receipt = evidence / "actual-codex-continuation.json"
    if receipt.exists():
        raise SystemExit("Continuation receipt exists: reconcile it, never generate again")
    location = json.loads((ROOT / "submission/local-case-location.json").read_text())
    source_project = ROOT / location["project_relative_path"]
    with Store(source_project, "test-core") as source:
        with source.io.lock(source.lock_path):
            source_snapshot, _, _ = source._load()
            records = source.records(source_snapshot)
            grant = scoped_transfer(source, source_snapshot, records, owner["approval_ref"]["entity_id"], destination)
            approved = records[f"{owner['approval_ref']['entity_id']}@{owner['approval_ref']['revision']}"]["payload"]
            if grant["approval_ref"] != owner["approval_ref"]:
                raise SystemExit("Approval revision changed; do not dispatch")
            grant_identity = digest(
                {
                    "source_root_sha256": approved["terms"]["source_root_sha256"],
                    "proposal_sha256": approved["terms"]["proposal_sha256"],
                    "destination_root_sha256": approved["terms"]["destination_root_sha256"],
                }
            )
            selected = [
                r
                for r in records.values()
                if source_snapshot["active"].get(r["id"]) == r["revision"]
                and r["kind"] in {"brief", "research_plan", "option", "strategy", "promise", "experiment", "decision"}
            ]
            packet_bytes = canonical(
                {
                    "case_id": "test-core",
                    "snapshot_digest": digest(source_snapshot),
                    "approval_ref": grant["approval_ref"],
                    "state": {k: v for k, v in source_snapshot["runtime"].items() if k != "completed_actions"},
                    "records": selected,
                    "constraints": [
                        "Only owned synthetic text; no raw media or business-H approval",
                        "No tests, benchmark, publication, repeated integrations or additional agent calls",
                    ],
                }
            )
            pinned_source_revision = source_snapshot["case_revision"]
    packet_relative = "continuation/authorized-packet-" + sha(packet_bytes) + ".json"
    with SafeRoot(destination) as root:
        root.write(packet_relative, packet_bytes, immutable=True)
    packet = destination / packet_relative
    prompt = (
        "Continue the transferred educational case using this second host, Codex. "
        "Read only AGENTS.md and " + packet_relative + " in the working directory; "
        "the packet contains the actual CLI status, handoff, brief and pinned strategy records. "
        "Do not read archives, binary artifacts, credentials, environment files, other directories or personal data. "
        "Do not run tests, benchmarks, fixtures, downloads, network tools, another agent, or model calls. "
        "The sole useful action is to draft a capability-delta note for the saved case, which the host will commit. "
        "Do not import sources again or rewrite existing strategies/decisions. The proposed change must distinguish "
        "local technical STT/MCP/model capabilities from unproven product export, demand, measured effects and real business approval. "
        "Answer in Russian, at most700 words, as JSON with keys case_id, snapshot_digest, read_refs, "
        "proposed_capability_delta, limitations, next_action, business_H_confirmed (false). "
        "Give exactly one next_action consistent with awaiting_human=reconsideration. "
        "No implementation or code changes. This is an actual continuation, not an independent review or acceptance test."
    )
    identity = digest(
        {"host": "codex", "model": "gpt-6.1-sol", "packet_sha256": sha(packet.read_bytes()), "prompt": prompt}
    )
    reservation_id = "codex-continuation-" + uuid.uuid4().hex
    snapshot(
        10,
        reservation={
            "id": reservation_id,
            "USD": 10,
            "status": "reserved",
            "at": now(),
            "external_identity": identity,
            "grant_identity": grant_identity,
            "purpose": "Single approved second-host continuation, text only",
        },
    )
    with Store(destination, "test-core") as store:
        before = store.status()
        intent = store.record(
            "action",
            {
                "payload": {
                    "operation": "note",
                    "note": canonical(
                        {
                            "type": "second_host_continuation_intent_v1",
                            "host": "codex-cli0.163.0",
                            "packet_sha256": sha(packet.read_bytes()),
                            "external_identity": identity,
                            "approval_ref": owner["approval_ref"],
                            "reservation_id": reservation_id,
                        }
                    ).decode(),
                }
            },
            before["case_revision"],
        )
    args = [
        "codex",
        "exec",
        "--ignore-user-config",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--model",
        "gpt-6.1-sol",
        "-c",
        'model_reasoning_effort="low"',
        "--cd",
        str(destination),
        "--json",
        "--color",
        "never",
        "--output-last-message",
        str(evidence / "codex-final-response.txt"),
        "-",
    ]
    report = {
        "at": now(),
        "status": "reserved_before_launch",
        "actual": True,
        "destination": str(destination),
        "external_identity": identity,
        "reservation_id": reservation_id,
        "intent": intent,
        "argv": args,
        "prompt": prompt,
        "packet_sha256": sha(packet.read_bytes()),
        "new_model_call_attempts": 1,
        "publication": False,
        "tests_run": False,
        "raw_media_input": False,
    }
    write_json(receipt, report)
    started = time.monotonic()
    with (evidence / "codex-events.jsonl").open("xb") as stdout, (evidence / "codex-stderr.log").open("xb") as stderr:
        with Store(source_project, "test-core") as source:
            with source.io.lock(source.lock_path):
                current, _, _ = source._load()
                if current["case_revision"] != pinned_source_revision:
                    raise SystemExit("Original case changed before dispatch; reservation kept, no model call")
                scoped_transfer(
                    source, current, source.records(current), owner["approval_ref"]["entity_id"], destination
                )
                if packet.read_bytes() != packet_bytes:
                    raise SystemExit("Pinned authorized packet changed; no model call")
                process = subprocess.Popen(
                    args, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr, cwd=destination, start_new_session=True
                )
                try:
                    process.communicate(prompt.encode(), timeout=150)
                    report.update(exit=process.returncode, status="returned")
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    report.update(
                        exit=process.returncode, status="outcome_unknown", reason="Bounded timeout; no automatic retry"
                    )
    report.update(ended_at=now(), local_duration_ms=(time.monotonic() - started) * 1000)
    events = []
    for line in (evidence / "codex-events.jsonl").read_text().splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    usage = next((event.get("usage") for event in reversed(events) if event.get("type") == "turn.completed"), None)
    report["actual_provider_usage"] = usage
    known = bool(usage and usage.get("output_tokens", 0) > 0)
    # Long-context prices, no cache discount: intentionally conservative.
    charge = (
        (usage["input_tokens"] * 4 + (usage["output_tokens"] + usage.get("reasoning_output_tokens", 0)) * 15) / 1000000
        if known
        else None
    )
    with SafeRoot(ROOT) as root:
        with root.lock(".local/subscription-budget.lock"):
            state = root.json(".local/subscription-budget.json")
            for row in state["reservations"]:
                if row["id"] == reservation_id:
                    row.update(
                        status="settled" if known else "outcome_unknown",
                        actual_API_equivalent_upper_USD=charge,
                        settled_at=now(),
                        reason="Actual Codex token receipt" if known else "Usage missing: keep full reserve, no retry",
                    )
            if known:
                state["other_sessions"].append(
                    {
                        "session_id": reservation_id,
                        "upper_USD": charge,
                        "actual_provider_usage": usage,
                        "purpose": "Single actual Codex continuation",
                    }
                )
            root.write(
                ".local/subscription-budget.json", (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode()
            )
    report["API_equivalent_upper_USD"] = charge
    response = evidence / "codex-final-response.txt"
    if report.get("exit") == 0 and response.exists():
        raw = response.read_bytes()
        with Store(destination, "test-core") as store:
            artifact = store.record(
                "artifact",
                {
                    "payload": {
                        "sha256": sha(raw),
                        "size": len(raw),
                        "media_type": "text/plain",
                        "origin": "model_simulation",
                        "processing_kind": "LLM-assisted",
                        "parent_refs": [intent["data"]["ref"]],
                    }
                },
                store.status()["case_revision"],
                artifacts={sha(raw): raw},
            )
            checkpoint = store.checkpoint(
                "Actual Codex continuation response saved as proposed capability-delta note; existing strategies and real business-H unchanged. Next: obtain exact product-user reconsideration, not inferred approval.",
                store.status()["case_revision"],
            )
        report.update(
            status="response_saved_not_business_approved",
            response_ref=artifact["data"]["ref"],
            response_sha256=sha(raw),
            checkpoint=checkpoint,
        )
    write_json(receipt, report)
    print(
        json.dumps(
            {
                k: report.get(k)
                for k in ("status", "exit", "actual_provider_usage", "API_equivalent_upper_USD", "response_ref")
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
