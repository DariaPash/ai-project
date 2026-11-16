import json
import os
import subprocess
import sys

from .helpers import PROJECT, cli, init, write_request


def test_two_real_writers_conflict_without_lost_updates(project):
    oracle = json.loads((PROJECT / "tests/fixtures/core/oracle.json").read_text())
    init(project)
    payload = {"payload": {"goal": "Competing write", "constraints": [], "open_questions": []}}
    request = write_request(project, payload)
    env = {"PATH": os.defpath, "PYTHONPATH": str(PROJECT), "PYTHONDONTWRITEBYTECODE": "1"}
    command = [
        sys.executable,
        "-m",
        "tools.cli",
        "record",
        "--case",
        "test-core",
        "--kind",
        "brief",
        "--file",
        request,
        "--expected-revision",
        "0",
    ]
    processes = [
        subprocess.Popen(command, cwd=project, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for _ in range(2)
    ]
    outputs = [p.communicate(timeout=25) for p in processes]
    assert sorted(p.returncode for p in processes) == oracle["concurrent_writer_exits"]
    assert all(json.loads(stdout)["code"] in {"OK", "CONFLICT"} for stdout, _ in outputs)
    _, status = cli(project, "status", "--case", "test-core")
    assert status["data"]["record_count"] == 1
    assert status["data"]["action_count"] == 2
    cli(project, "validate", "--case", "test-core")
