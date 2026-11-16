"""Fixed parser subprocess, bounded by the parent deadline and output cap."""

import base64
import logging
import hashlib
import os
import sys

from .errors import CoreError
from .safeio import canonical, parse_json


def main():
    logging.disable(logging.CRITICAL)
    audit = {
        "scope": "parser_python_process_only_not_OS_sandbox",
        "network_attempts": 0,
        "spawn_attempts": 0,
        "opened_path_hashes": [],
        "truncated": False,
    }
    opened = set()

    def guard(event, args):
        if event in {
            "socket.connect",
            "socket.getaddrinfo",
            "socket.gethostbyname",
            "socket.gethostbyaddr",
            "socket.sendto",
        }:
            audit["network_attempts"] += 1
            raise CoreError("PARSER_EGRESS", "Local parsing may not perform network operations", 4)
        if event in {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn"}:
            audit["spawn_attempts"] += 1
            raise CoreError("PARSER_SPAWN", "Local parsing may not spawn another process", 4)
        if event == "open" and isinstance(args[0], (str, bytes)):
            hashed = hashlib.sha256(os.fsencode(args[0])).hexdigest()
            if len(opened) < 512:
                opened.add(hashed)
            else:
                audit["truncated"] = True

    sys.addaudithook(guard)
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
        # Some POSIX platforms do not implement a useful RLIMIT_AS; the parent
        # deadline still applies. This is not a hostile-code OS sandbox.
        try:
            resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
        except (ValueError, OSError):
            pass
        request = parse_json(sys.stdin.buffer.read(12 * 1024 * 1024))
        raw = base64.b64decode(request["raw_base64"], validate=True)
        from .sources import parse_bytes

        parsed = parse_bytes(raw, request["spec"])
        audit["opened_path_hashes"] = sorted(opened)
        parsed["coverage"]["security_trace"] = audit
        if len(canonical(parsed)) > request["spec"]["limits"]["max_output_bytes"]:
            raise CoreError("OUTPUT_LIMIT", "Extraction including audit metadata exceeds its cap", 4)
        result = {"ok": True, "data": parsed}
    except CoreError as exc:
        result = {"ok": False, "code": exc.code, "reason": exc.reason, "exit": exc.exit_code}
    except ImportError:
        result = {"ok": False, "code": "PARSER_UNAVAILABLE", "reason": "Required parser is not installed", "exit": 3}
    except Exception:
        result = {
            "ok": False,
            "code": "INPUT_CORRUPT",
            "reason": "Parser rejected malformed input; content not invented",
            "exit": 2,
        }
    sys.stdout.buffer.write(canonical(result))


if __name__ == "__main__":
    main()
