"""Execute the fixed README example, preserving actual CLI receipts.

This is a local test script, NOT an LLM session, independent reviewer or agent loop.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from tools.development import ROOT, now, write_json
from tools.safeio import parts


def main():
    progress = json.loads((ROOT / "planning/progress.json").read_text())
    destination = ROOT / progress["active_run"] / "readme-example"
    parts(str(destination.relative_to(ROOT)))
    if destination.exists():
        raise SystemExit("Example already exists; preserve its original receipts, use a new explicit run for a repeat")
    project = destination / "project"
    project.mkdir(parents=True)
    shutil.copytree(ROOT / "config", project / "config")
    shutil.copytree(ROOT / "tests/fixtures/core", project / "tests/fixtures/core")
    case = "test-quickstart"
    commands = [
        ["doctor"],
        ["init", "--case", case, "--namespace", "test"],
        ["status", "--case", case],
        [
            "record",
            "--case",
            case,
            "--kind",
            "brief",
            "--file",
            "tests/fixtures/core/brief.json",
            "--expected-revision",
            "0",
        ],
        [
            "record",
            "--case",
            case,
            "--kind",
            "action",
            "--file",
            "tests/fixtures/core/action.json",
            "--expected-revision",
            "1",
        ],
        ["checkpoint", "--case", case, "--reason", "pause", "--expected-revision", "2"],
        ["validate", "--case", case],
        ["status", "--case", case],
    ]
    transcript = {
        "actual": True,
        "tier": "offline_real_tool",
        "is_new_llm_context": False,
        "origin": "synthetic_fixture",
        "started_at": now(),
        "calls": [],
    }
    # No PYTHONPATH: exercise the actually installed editable package from another cwd.
    environment = {"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"}
    for arguments in commands:
        command = [sys.executable, "-m", "tools.cli", *arguments]
        started = now()
        result = subprocess.run(command, cwd=project, env=environment, capture_output=True, text=True, timeout=25)
        transcript["calls"].append(
            {
                "command": command,
                "cwd": str(project.relative_to(ROOT)),
                "started_at": started,
                "ended_at": now(),
                "exit": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        write_json(destination / "receipts.json", transcript)
        if result.returncode != 0:
            raise SystemExit("README example failed; inspect the preserved receipt")
    status = json.loads(transcript["calls"][-1]["stdout"])
    assert status["data"]["record_count"] == 2
    assert status["data"]["state"]["stage"] == "brief_clarification"
    assert status["data"]["state"]["awaiting_human"] == "Уточнить метрику"
    transcript.update(ended_at=now(), assertions="passed", next_action=status["data"]["state"]["next_action"])
    write_json(destination / "receipts.json", transcript)
    print(
        json.dumps(
            {
                "receipt": str((destination / "receipts.json").relative_to(ROOT)),
                "commands": len(commands),
                "assertions": "passed",
                "new_llm_context": False,
                "state": status["data"]["state"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
