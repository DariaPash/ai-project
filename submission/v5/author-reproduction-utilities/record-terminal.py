"""Record a genuine PTY session and preserve timed I/O (asciicast v2).

No fabricated command output, slides, tests or network provider calls.
The companion renderer replays terminal screen state from these exact bytes.
"""

import codecs
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import struct
import sys
import termios
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.development import now, write_json
from tools.store import Store

COLS, ROWS = 116, 34
PROMPT = "ai-project$ "


class Screen:
    def __init__(self):
        self.lines = [[" "] * COLS for _ in range(ROWS)]
        self.x = self.y = 0
        self.escape = ""

    def down(self):
        self.y += 1
        if self.y >= ROWS:
            self.lines.pop(0)
            self.lines.append([" "] * COLS)
            self.y = ROWS - 1

    def feed(self, text):
        for c in text:
            if self.escape:
                self.escape += c
                if self.escape.startswith("\x1b]"):
                    if c == "\x07" or self.escape.endswith("\x1b\\"):
                        self.escape = ""
                    continue
                if self.escape == "\x1b[":
                    continue
                if len(self.escape) == 2 and c not in "[]":
                    self.escape = ""
                    continue
                if self.escape.startswith("\x1b[") and "@" <= c <= "~":
                    values = self.escape[2:-1]
                    nums = [int(n) if n.isdigit() else 0 for n in values.split(";")]
                    n = nums[0] or 1
                    if c == "K":
                        start, end = (
                            (0, COLS) if values == "2" else ((0, self.x + 1) if values == "1" else (self.x, COLS))
                        )
                        for i in range(start, min(end, COLS)):
                            self.lines[self.y][i] = " "
                    elif c == "J" and values in {"2", "3"}:
                        self.lines = [[" "] * COLS for _ in range(ROWS)]
                    elif c in "Hf":
                        self.y = min(ROWS - 1, max(0, n - 1))
                        self.x = min(COLS - 1, max(0, (nums[1] if len(nums) > 1 and nums[1] else 1) - 1))
                    elif c == "G":
                        self.x = min(COLS - 1, n - 1)
                    elif c == "A":
                        self.y = max(0, self.y - n)
                    elif c == "B":
                        self.y = min(ROWS - 1, self.y + n)
                    elif c == "C":
                        self.x = min(COLS - 1, self.x + n)
                    elif c == "D":
                        self.x = max(0, self.x - n)
                    self.escape = ""
                continue
            if c == "\x1b":
                self.escape = c
            elif c == "\r":
                self.x = 0
            elif c == "\n":
                self.down()
            elif c == "\b":
                self.x = max(0, self.x - 1)
            elif c == "\t":
                self.x = min(COLS - 1, (self.x // 8 + 1) * 8)
            elif ord(c) >= 32 and c != "\x7f":
                if self.x >= COLS:
                    self.x = 0
                    self.down()
                self.lines[self.y][self.x] = c
                self.x += 1

    def state(self):
        return {"lines": ["".join(line).rstrip() for line in self.lines], "x": min(self.x, COLS - 1), "y": self.y}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", help="Explicit real-command plan JSON for a new recording revision")
    parser.add_argument("--output", default="submission/cli-recording")
    args = parser.parse_args()
    plan = json.loads((ROOT / args.plan).read_text()) if args.plan else None
    output = ROOT / args.output
    output.mkdir(exist_ok=False)
    progress = json.loads((ROOT / "planning/progress.json").read_text())
    memory = json.loads((ROOT / progress["steps"]["06"]["evidence"][0]).read_text()) if not plan else None
    case = plan["case"] if plan else memory["fixture_case"]
    project = ROOT / case["project"]
    with Store(project, case["case_id"]) as store:
        before = store.status()
    write_json(output / "before.json", before)
    material = project / "cases/test-core/input/cli-recording"
    if not plan:
        material.mkdir(exist_ok=False)
    else:
        material = output / "unused-legacy-input"
        material.mkdir()
    (material / "note.txt").write_text(
        "terminal-recording: owned synthetic CLI demonstration note.\nThis note demonstrates local import and search only.\nIt does not prove customer demand, task completion, or business approval.\n",
        encoding="utf-8",
    )
    write_json(
        material / "ingest.json",
        {
            "schema_version": 1,
            "format": "txt",
            "title": "Owned terminal-recording note",
            "origin": "synthetic_fixture",
            "rights": {"processing": True, "external_transfer": False, "publication": False},
            "options": {"encoding": "utf-8"},
            "limits": {
                "max_bytes": 65536,
                "max_output_bytes": 262144,
                "max_rows": 100,
                "max_columns": 16,
                "max_pages": 2,
                "timeout_ms": 10000,
                "max_zip_entries": 50,
                "max_uncompressed_bytes": 1048576,
                "max_compression_ratio": 50,
            },
        },
    )
    write_json(material / "index.json", {"mode": "hybrid", "language": "eng"})
    commands = [
        "printf 'Синтетический учебный кейс. Настоящие команды CLI, без слайдов.\\n'",
        "alias ai='$PYTHON -m tools.cli'",
        "set -o pipefail",
        "ai status --case test-core | jq '{revision:.case_revision, awaiting_human:.data.state.awaiting_human, next:.data.state.next_action}'",
        "ai retrieve --case test-core --mode hybrid --query 'what evidence is missing before promising completion?' | jq '{mode:.data.mode,vectors:.data.semantic_vectors_used,hits:[.data.hits[:3][]|{ref,text:(.text[:180])}]}'",
        "cat cases/test-core/input/cli-recording/note.txt",
        "r=$(ai status --case test-core | jq -r .case_revision)",
        "ai ingest --case test-core --path cases/test-core/input/cli-recording/note.txt --spec cases/test-core/input/cli-recording/ingest.json --expected-revision \"$r\" | jq '{ok,code,revision:.case_revision,source:.data.source_ref,extraction:.data.extraction_ref,error}'",
        "ai search --case test-core --query 'terminal-recording' | jq '{hits:[.data.hits[:2][]|{source:.source_ref,quote:.locator.exact_quote,origin:.origin_roots}]}'",
        "ai index build --case test-core --spec cases/test-core/input/cli-recording/index.json --expected-revision \"$(ai status --case test-core | jq -r .case_revision)\" | jq '{ok,code,revision:.case_revision,data,error}'",
        "ai retrieve --case test-core --mode hybrid --query 'What is the terminal-recording note allowed to prove?' | jq '{mode:.data.mode,hits:[.data.hits[:3][]|{ref,text:(.text[:180])}]}'",
        "ai impact --case test-core --claim CLM-002 | jq '{start:.data.start_ref,affected_count:(.data.affected|length),sample:[.data.affected[:5][]|{ref,kind}]}'",
        'ai agenda --case test-core --as-of "$(date -u +%Y-%m-%dT%H:%M:%SZ)" | jq \'{awaiting_human:.data.awaiting_human,obligations:[.data.items[]|select(.kind=="obligation")]}\'',
        'ai checkpoint --case test-core --reason "CLI session recorded; H remains pending" --expected-revision "$(ai status --case test-core | jq -r .case_revision)" | jq \'{ok,code,revision:.case_revision}\'',
        "ai status --case test-core | jq '{revision:.case_revision,awaiting_human:.data.state.awaiting_human,next:.data.state.next_action}'",
        "printf 'Импорт, поиск, индекс и checkpoint выполнены. H не подтверждался.\\n'",
    ]
    if plan:
        commands = plan["commands"]
    write_json(
        output / "capture-plan.json",
        {
            "at": now(),
            "actual_commands": commands,
            "case_project": case["project"],
            "rows": ROWS,
            "columns": COLS,
            "speed": 1,
            "no_tests": True,
            "no_provider_calls": plan.get("no_provider_calls", True) if plan else True,
            "capture": "Real PTY, actual echoed input/output. Video is frame-by-frame terminal replay, not desktop OS screen capture.",
        },
    )
    start = time.monotonic()
    screen = Screen()
    frames = []
    events = []
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    tail = ""
    command_receipts = []
    log = (output / "session.cast").open("x", encoding="utf-8")
    log.write(
        json.dumps(
            {
                "version": 2,
                "width": COLS,
                "height": ROWS,
                "timestamp": int(time.time()),
                "title": "ai-project actual CLI session",
                "env": {"TERM": "xterm-256color"},
            },
            ensure_ascii=False,
        )
        + "\n"
    )
    log.flush()
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(project)
        env = {
            "PATH": "/opt/homebrew/bin:/usr/bin:/bin",
            "PYTHONPATH": str(ROOT),
            "PYTHON": str(ROOT / ".venv-dev/bin/python"),
            "DEMO_VIEW": str(ROOT / "submission/story-view.py"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "TERM": "xterm-256color",
            "LANG": "en_US.UTF-8",
            "LC_ALL": "en_US.UTF-8",
            "PS1": PROMPT,
            "PS2": "> ",
            "HISTFILE": "/dev/null",
            "BASH_SILENCE_DEPRECATION_WARNING": "1",
            "PROMPT_COMMAND": 'printf "\\033]133;D;%s\\007" "$?"',
        }
        os.execve("/bin/bash", ["bash", "--noprofile", "--norc", "-i"], env)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))

    def event(kind, text):
        t = round(time.monotonic() - start, 6)
        entry = [t, kind, text]
        events.append(entry)
        log.write(json.dumps(entry, ensure_ascii=False) + "\n")
        log.flush()

    def snapshot(force=False):
        state = screen.state()
        t = round(time.monotonic() - start, 3)
        if force or not frames or (t - frames[-1]["time"] >= 0.09 and state != frames[-1]["screen"]):
            frames.append({"time": t, "screen": state})

    def pump(seconds):
        nonlocal tail
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            readable, _, _ = select.select([fd], [], [], min(0.025, max(0, end - time.monotonic())))
            if readable:
                try:
                    data = os.read(fd, 65536)
                except OSError:
                    return
                if not data:
                    return
                text = decoder.decode(data)
                event("o", text)
                tail = (tail + text)[-18000:]
                screen.feed(text)
            snapshot()

    def wait_prompt(timeout):
        deadline = time.monotonic() + timeout
        while not tail.endswith(PROMPT):
            if time.monotonic() > deadline:
                raise TimeoutError(
                    "Actual command did not return prompt; preserve captured result and reconcile case, no automatic replay"
                )
            pump(0.04)
        snapshot(force=True)

    success = False
    try:
        wait_prompt(8)
        pump(1)
        for command in commands:
            tail = ""
            began = now()
            t0 = round(time.monotonic() - start, 3)
            for c in command:
                os.write(fd, c.encode())
                event("i", c)
                pump(0.012)
            os.write(fd, b"\n")
            event("i", "\n")
            wait_prompt(plan.get("command_timeout_seconds", 90) if plan else 90)
            statuses = re.findall(r"\x1b\]133;D;(\d+)\x07", tail)
            code = int(statuses[-1]) if statuses else None
            command_receipts.append(
                {
                    "command": command,
                    "started_at": began,
                    "start_seconds": t0,
                    "end_seconds": round(time.monotonic() - start, 3),
                    "shell_exit": code,
                }
            )
            write_json(output / "commands.json", command_receipts)
            if code != 0:
                raise RuntimeError(
                    "Actual command returned " + str(code) + "; raw failure preserved, no success replacement"
                )
            pump(plan.get("hold_seconds", 6) if plan else (2.5 if "jq" in command else 1.3))
        pump(3)
        snapshot(force=True)
        success = True
    finally:
        duration = round(time.monotonic() - start, 3)
        # Interactive bash ignores SIGTERM. Save the capture before bounded cleanup.
        write_json(
            output / "terminal-frames.json", {"columns": COLS, "rows": ROWS, "duration": duration, "frames": frames}
        )
        try:
            os.killpg(pid, signal.SIGHUP)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 2
        while True:
            try:
                done, _ = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                break
            if done:
                break
            if time.monotonic() >= deadline:
                try:
                    os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                os.waitpid(pid, 0)
                break
            time.sleep(0.02)
        os.close(fd)
        log.flush()
        os.fsync(log.fileno())
        log.close()
        write_json(
            output / "terminal-frames.json", {"columns": COLS, "rows": ROWS, "duration": duration, "frames": frames}
        )
        with Store(project, case["case_id"]) as store:
            after = store.status()
        write_json(
            output / "capture-receipt.json",
            {
                "at": now(),
                "actual": True,
                "success": success,
                "seconds": duration,
                "commands_completed": len(command_receipts),
                "raw_cast_sha256": hashlib.sha256((output / "session.cast").read_bytes()).hexdigest(),
                "before_revision": before["case_revision"],
                "after_revision": after["case_revision"],
                "after_snapshot_digest": after["data"]["snapshot_digest"],
                "awaiting_human": after["data"]["state"]["awaiting_human"],
                "rendering": "Timed terminal-screen replay of actual captured bytes; no prepared output substitution",
                "test_runs": 0,
                "screen_capture": False,
                "pty_recording": True,
            },
        )
    print(
        json.dumps(
            {
                "capture": str(output.relative_to(ROOT)),
                "seconds": duration,
                "frames": len(frames),
                "commands": len(command_receipts),
                "case_revision": after["case_revision"],
            }
        )
    )


if __name__ == "__main__":
    main()
