"""Offline acceptance wrapper. Python audit trace, not an OS-wide egress proof."""

import hashlib
import json
import os
import sys


def main():
    opened = set()
    network = []
    spawned = []

    def audit(event, args):
        if event == "open" and isinstance(args[0], (str, bytes)):
            opened.add(hashlib.sha256(os.fsencode(args[0])).hexdigest())
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "socket.gethostbyname"}:
            network.append(event)
            raise RuntimeError("Offline smoke forbids network")
        if event == "subprocess.Popen":
            command = args[1]
            spawned.append(
                {
                    "executable": os.path.basename(str(args[0])),
                    "module": command[2] if len(command) > 2 and command[1] == "-m" else "unknown",
                }
            )

    sys.addaudithook(audit)
    from tools.cli import main as cli

    try:
        return cli()
    finally:
        trace = {
            "scope": "CLI Python process; parser children carry separate audit receipts; not OS-wide tracing",
            "network_events": network,
            "spawned": spawned,
            "opened_path_hashes": sorted(opened),
        }
        print("AUDIT_TRACE=" + json.dumps(trace, sort_keys=True), file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
