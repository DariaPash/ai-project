"""Local development evidence, deliberately separate from product case state."""

from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import signal
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
PROTECTED = (
    "main.py",
    "HACKATHON_PLAN.md",
    ".idea",
    ".venv",
    "planning/design",
    "planning/steps",
    "planning/README.md",
)


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def protected_manifest():
    result = {}
    for name in PROTECTED:
        path = ROOT / name
        files = sorted(p for p in path.rglob("*") if p.is_file() and not p.is_symlink()) if path.is_dir() else [path]
        entries = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        result[name] = {
            "files": len(entries),
            "tree_sha256": hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest(),
        }
    return result


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temp.open("x") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def start():
    path = ROOT / "planning/progress.json"
    if path.exists():
        raise SystemExit("Progress exists; inspect it instead of reinitializing")
    stamp = now()
    run = "run-" + uuid.uuid4().hex
    evidence = ROOT / "planning/evidence/01" / run
    baseline = protected_manifest()
    write_json(evidence / "baseline.json", {"at": stamp, "protected": baseline})
    steps = {}
    for instruction in sorted((ROOT / "planning/steps").glob("*.md")):
        step = instruction.name[:2]
        steps[step] = {
            "step_id": step,
            "status": "not_started",
            "execution": "pending",
            "instruction_sha256": hashlib.sha256(instruction.read_bytes()).hexdigest(),
            "base_manifest": digest(baseline),
            "prerequisites": [],
            "completed_units": [],
            "changed_files": [],
            "checks": [],
            "gates": [],
            "blockers": [],
            "budget_used": {"money": "unknown", "human_minutes": "unknown"},
            "updated_at": stamp,
            "next_action": "Wait for explicit execution of this step",
        }
    features = {
        f"F{i:02}": {
            key: {"status": "not_started", "evidence": []}
            for key in ("implementation", "offline", "live", "semantic", "acceptance")
        }
        for i in range(1, 16)
    }
    progress = {
        "schema_version": 1,
        "revision": 0,
        "updated_at": stamp,
        "active_run": str(evidence.relative_to(ROOT)),
        "steps": steps,
        "features": features,
    }
    write_json(path, progress)
    steps["01"].update(
        status="in_progress",
        execution="active",
        next_action="Implement and test core contracts/store/CLI",
        gates=["B", "R", "D", "N"],
    )
    progress["revision"] = 1
    write_json(path, progress)
    print(str(evidence.relative_to(ROOT)))


def check(command):
    progress = json.loads((ROOT / "planning/progress.json").read_text())
    evidence = ROOT / progress["active_run"]
    started = now()
    check_id = "check-" + uuid.uuid4().hex
    dest = evidence / (check_id + ".json")
    write_json(
        evidence / "check-runs" / (check_id + "-intent.json"),
        {
            "command": command,
            "started_at": started,
            "status": "hashing_inputs",
            "actual": True,
            "deadline_seconds": 1200,
        },
    )
    inputs = {}
    for name in (
        "tools",
        "schemas",
        "config",
        "tests",
        "workflows",
        "knowledge",
        "templates",
        "skills",
        "AGENTS.md",
        "README.md",
        "PROJECT_CHARTER.md",
        "pyproject.toml",
        "requirements.txt",
        "requirements-optional-media.txt",
    ):
        path = ROOT / name
        candidates = path.rglob("*") if path.is_dir() else [path]
        for item in candidates:
            if item.is_file() and not item.is_symlink() and "__pycache__" not in item.parts:
                inputs[str(item.relative_to(ROOT))] = hashlib.sha256(item.read_bytes()).hexdigest()
    stdout_path = evidence / (check_id + ".stdout.log")
    stderr_path = evidence / (check_id + ".stderr.log")
    with stdout_path.open("xb") as out, stderr_path.open("xb") as err:
        process = subprocess.Popen(command, cwd=ROOT, stdout=out, stderr=err, start_new_session=True)
        timed_out = False
        try:
            write_json(
                evidence / "check-runs" / (check_id + "-started.json"),
                {
                    "command": command,
                    "started_at": started,
                    "pid": process.pid,
                    "stdout": str(stdout_path.relative_to(ROOT)),
                    "stderr": str(stderr_path.relative_to(ROOT)),
                    "status": "running",
                    "actual": True,
                },
            )
            process.wait(timeout=1200)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
    result = subprocess.CompletedProcess(
        command,
        124 if timed_out else process.returncode,
        stdout_path.read_text(errors="replace"),
        stderr_path.read_text(errors="replace"),
    )
    if timed_out:
        result.stderr += "\nDevelopment command exceeded 1200s; terminated process group; partial logs retained."
    receipt = {
        "command": command,
        "started_at": started,
        "ended_at": now(),
        "exit": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "actual": True,
        "tier": "offline_real_tool",
        "input_hashes": inputs,
    }
    write_json(dest, receipt)
    update_progress(
        check={
            "command": command,
            "exit": result.returncode,
            "expected": 0,
            "observed": result.returncode,
            "evidence": str(dest.relative_to(ROOT)),
            "at": receipt["ended_at"],
        }
    )
    print(
        json.dumps(
            {"receipt": str(dest.relative_to(ROOT)), **{k: v for k, v in receipt.items() if k != "input_hashes"}},
            ensure_ascii=False,
        )
    )
    return result.returncode


def update_progress(*, check=None, unit=None):
    from .safeio import SafeRoot

    with SafeRoot(ROOT) as root:
        with root.lock("planning/.progress.lock"):
            progress = root.json("planning/progress.json")
            active_step = Path(progress["active_run"]).parts[2]
            step = progress["steps"][active_step]
            if check:
                step["checks"].append(check)
            if unit:
                step["completed_units"].append({"label": unit, "at": now()})
            step["updated_at"] = progress["updated_at"] = now()
            progress["revision"] += 1
            root.write(
                "planning/progress.json",
                (json.dumps(progress, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode(),
            )


def start_step(step_id):
    from .safeio import SafeRoot

    if step_id not in {"02", "03", "04", "05", "06", "07", "08"}:
        raise SystemExit("Unknown sequential development step")
    with SafeRoot(ROOT) as root:
        with root.lock("planning/.progress.lock"):
            progress = root.json("planning/progress.json")
            if progress["steps"][step_id]["status"] != "not_started":
                raise SystemExit("Step already started; inspect its existing handoff/evidence, do not reset")
            predecessor = f"{int(step_id) - 1:02}"
            core_path = progress["steps"][predecessor]["evidence"][0]
            core = root.json(core_path)
            assert progress["steps"][predecessor]["status"] in ({"done"} if step_id == "02" else {"done", "partial"})
            for filename, expected in core["source_hashes"].items():
                # This runner is the intentionally changed development bootstrap.
                if filename != "tools/development.py":
                    assert hashlib.sha256((ROOT / filename).read_bytes()).hexdigest() == expected, (
                        "Changed prerequisite: " + filename
                    )
            instructions = list((ROOT / "planning/steps").glob(step_id + "-*.md"))
            assert len(instructions) == 1
            instruction = instructions[0]
            run = "planning/evidence/" + step_id + "/run-" + uuid.uuid4().hex
            write_json(
                ROOT / run / "baseline.json",
                {
                    "at": now(),
                    "protected": protected_manifest(),
                    "prerequisite_manifest": core_path,
                    "prerequisite_manifest_sha256": hashlib.sha256((ROOT / core_path).read_bytes()).hexdigest(),
                    "predecessor_accepted_source_hashes": core["source_hashes"],
                },
            )
            progress["active_run"] = run
            progress["steps"][step_id].update(
                status="in_progress",
                execution="active",
                instruction_sha256=hashlib.sha256(instruction.read_bytes()).hexdigest(),
                prerequisites=[{"step": predecessor, "manifest": core_path, "schema_version": 1}],
                gates=["B", "R", "D", "P-network", "L-live-fetch"]
                + (["H-option-choice", "H-final-decision"] if step_id == "03" else []),
                next_action="Preflight real local capabilities, freeze observer fixtures, implement and verify only this sequential increment; inherited gates remain blocked",
                updated_at=now(),
            )
            progress["revision"] += 1
            progress["updated_at"] = now()
            root.write("planning/progress.json", (json.dumps(progress, ensure_ascii=False, indent=2) + "\n").encode())
    print(run)


def complete_core():
    """Close step01 only after matching real evidence; not a full-product release."""
    from .contracts import validate_schema
    from .safeio import SafeRoot
    from .store import Store

    progress = json.loads((ROOT / "planning/progress.json").read_text())
    assert Path(progress["active_run"]).parts[2] == "01", "Core acceptance belongs to its original step01 run"
    evidence = ROOT / progress["active_run"]
    receipts = sorted(
        ((p, json.loads(p.read_text())) for p in evidence.glob("check-*.json")), key=lambda pair: pair[1]["started_at"]
    )
    suites = [(p, value) for p, value in receipts if value["command"][-3:] == ["pytest", "tests", "-q"]]
    assert suites, "No actual full suite receipt"
    suite_path, suite = suites[-1]
    assert suite["exit"] == 0 and "skipped" not in suite["stdout"], "Core tests failed/were skipped"
    count = int(re.search(r"(\d+) passed", suite["stdout"])[1])
    for path, expected in suite["input_hashes"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected, "Untested change: " + path
    freeze = json.loads((evidence / "fixture-freeze.json").read_text())
    for path, expected in freeze["files"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected, "Frozen fixture changed: " + path
    native = json.loads((evidence / "new-context/receipt.json").read_text())
    invocation = json.loads((evidence / "new-context/invocation.json").read_text())
    assert invocation["fresh_context"] and invocation["state_from_actual_tool_result"] == "completed"
    assert invocation["session_id_from_actual_tool_result"].startswith("ses_")
    assert all(native["comparison"]["checks"].values())
    assert len(native["commands"]) == 8 and all(c["exit_code"] == 0 for c in native["commands"])
    with Store(evidence / "readme-example/project", "test-quickstart") as case:
        checked = case.validate()
    after = native["after"]["authoritative_snapshot"]["content"]
    assert checked["case_revision"] == after["case_revision"] == 5
    assert checked["data"]["state"] == after["runtime"]
    baseline = json.loads((evidence / "baseline.json").read_text())["protected"]
    protected = protected_manifest()
    changed = [p for p in baseline if baseline[p] != protected[p]]
    assert set(changed) <= {".idea"}, "Protected source/venv/planning changed: inspect without overwrite"
    manifest_path = evidence / "core-manifest.json"
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text())
        assert old["source_hashes"] == suite["input_hashes"], (
            "Preserve the old manifest; changed inputs need a new evidence run"
        )
        print("Existing core acceptance preserved; identical input hashes")
        return
    manifest = {
        "schema_version": 1,
        "accepted_at": now(),
        "step_id": "01",
        "status": "done",
        "scope": "Step01 core + one native N smoke only; not full F01–F15",
        "source_hashes": suite["input_hashes"],
        "latest_suite_receipt": str(suite_path.relative_to(ROOT)),
        "tests_passed": count,
        "tests_skipped": 0,
        "fresh_context_session_id": invocation["session_id_from_actual_tool_result"],
        "fresh_context_receipt_sha256": hashlib.sha256(
            (evidence / "new-context/receipt.json").read_bytes()
        ).hexdigest(),
        "fixture_freeze_sha256": hashlib.sha256((evidence / "fixture-freeze.json").read_bytes()).hexdigest(),
        "case_revision": checked["case_revision"],
        "case_snapshot_digest": checked["data"]["snapshot_digest"],
        "protected_trees": protected,
        "protected_changes_preserved": changed,
        "protected_change_note": "Observed .idea delta retained, not reset; no all-trees-unchanged claim",
        "inherited_open_gates": ["B", "R", "D", "P-external-transfer", "S"],
        "model_cost": None,
        "tokens": None,
        "unknown_reason": "Host billing is not exposed",
    }
    with SafeRoot(ROOT) as root:
        with root.lock("planning/.progress.lock"):
            progress = root.json("planning/progress.json")
            step = progress["steps"]["01"]
            step.update(
                status="done",
                execution="completed",
                updated_at=now(),
                blockers=[],
                gates=manifest["inherited_open_gates"],
                next_action="Начать шаг 02 по его инструкции после проверки core-manifest; шаг 02 ещё не запускался",
            )
            step["changed_files"] = sorted(
                set(suite["input_hashes"])
                | {".gitignore", ".env.example", "planning/progress.json", "planning/handoff.md"}
            )
            step["evidence"] = [
                str((evidence / name).relative_to(ROOT))
                for name in (
                    "core-manifest.json",
                    "result.md",
                    "fixture-freeze.json",
                    "readme-example/receipts.json",
                    "new-context/invocation.json",
                    "new-context/receipt.json",
                    "new-context/report.md",
                )
            ]
            step["accepted_subcontracts"] = [
                "schema-v1-pinned-refs-lineage",
                "local-posix-commit-recovery-lock",
                "json-cli-status-record-validate-checkpoint",
                "safe-input-roots",
                "usage-reservation-unknown-outcome",
                "test-helpers-frozen-oracle",
                "native-fresh-context-core-smoke",
            ]
            known = {check["evidence"] for check in step["checks"]}
            for path, receipt in receipts:
                relative = str(path.relative_to(ROOT))
                if relative not in known:
                    step["checks"].append(
                        {
                            "command": receipt["command"],
                            "exit": receipt["exit"],
                            "expected": 0,
                            "observed": receipt["exit"],
                            "evidence": relative,
                            "at": receipt["ended_at"],
                        }
                    )
            step["checks"].append(
                {
                    "command": ["native-fresh-context", invocation["session_id_from_actual_tool_result"]],
                    "exit": 0,
                    "expected": 0,
                    "observed": 0,
                    "evidence": str((evidence / "new-context/receipt.json").relative_to(ROOT)),
                    "at": native["finished_at"],
                }
            )
            step["completed_units"].append(
                {
                    "label": f"Core accepted: {count} tests, install/pip/doctor, README commands and real native N",
                    "at": now(),
                }
            )
            scopes = {
                "F08": "Decision/APR contracts only; agenda/obligations future",
                "F09": "Pinned refs/evidence DAG only; semantic impact future",
                "F10": "Reservation/budget contracts only; model routes future",
                "F11": "Instructions/workflows only; N is not a reviewer",
                "F12": "Local CLI only; MCP future",
                "F14": "Local recovery/locks/idempotency and native N; export/second host future",
                "F15": "Usage ledger only; benchmark future",
            }
            for feature, scope in scopes.items():
                for dimension in ("implementation", "offline"):
                    progress["features"][feature][dimension] = {
                        "status": "partial",
                        "scope": scope,
                        "evidence": [manifest["latest_suite_receipt"]],
                    }
            progress["features"]["F14"]["live"] = {
                "status": "partial",
                "scope": "N core smoke passed; full product resume/second environment future",
                "evidence": [str((evidence / "new-context/receipt.json").relative_to(ROOT))],
            }
            progress["revision"] += 1
            progress["updated_at"] = now()
            validate_schema("development-progress", progress)
            write_json(manifest_path, manifest)
            root.write(
                "planning/progress.json",
                (json.dumps(progress, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode(),
            )
    print(
        json.dumps(
            {
                "step": "01",
                "status": "done",
                "tests_passed": count,
                "new_context": "passed",
                "manifest": str(manifest_path.relative_to(ROOT)),
                "protected_changes_preserved": changed,
            },
            ensure_ascii=False,
        )
    )


def main():
    if sys.argv[1:] == ["start"]:
        start()
    elif sys.argv[1:2] == ["check"] and len(sys.argv) > 2:
        raise SystemExit(check(sys.argv[2:]))
    elif sys.argv[1:2] == ["unit"] and len(sys.argv) == 3:
        update_progress(unit=sys.argv[2])
    elif sys.argv[1:] == ["complete-core"]:
        complete_core()
    elif sys.argv[1:2] == ["start-step"] and len(sys.argv) == 3:
        start_step(sys.argv[2])
    elif sys.argv[1:] == ["verify-protected"]:
        progress = json.loads((ROOT / "planning/progress.json").read_text())
        baseline = json.loads((ROOT / progress["active_run"] / "baseline.json").read_text())["protected"]
        actual = protected_manifest()
        changed = [name for name in baseline if baseline[name] != actual[name]]
        print(json.dumps({"changed": changed, "protected": actual}, indent=2))
        raise SystemExit(bool(changed))
    else:
        raise SystemExit("development: start | check COMMAND... | verify-protected")


if __name__ == "__main__":
    main()
