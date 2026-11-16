"""Whole-deadline local media worker. No original mutable path is reopened."""

import base64
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from .contracts import sha, validate_schema
from .errors import CoreError
from .safeio import canonical, parse_json


def main():
    if os.getpgrp() == os.getpid():
        os.environ["STRATEGIST_LOCAL_MEDIA_WORKER_PGID"] = str(os.getpid())
    try:
        request = parse_json(sys.stdin.buffer.read(12 * 1024 * 1024))
        spec = request["spec"]
        validate_schema("media-spec", spec)
        raw = base64.b64decode(request["raw_base64"], validate=True)
        if len(raw) > spec["limits"]["max_bytes"]:
            raise CoreError("MEDIA_BYTES", "Media exceeds input cap", 4)
        from .adapters.base import AdapterRequest
        from .adapters import ocr, stt, video

        adapter = ocr if spec["format"] in {"image", "scan_pdf"} else stt if spec["format"] == "audio" else video
        deadline = time.monotonic() + spec["limits"]["timeout_ms"] / 1000
        with tempfile.TemporaryDirectory(prefix="evidence-media-") as folder:
            result = adapter.execute(AdapterRequest(raw, sha(raw), spec, deadline), Path(folder))
        for child in result["children"]:
            child["sha256"] = sha(child["raw"])
            child["raw_base64"] = base64.b64encode(child.pop("raw")).decode()
        result["format"] = spec["format"]
        if len(canonical(result)) > spec["limits"]["max_output_bytes"]:
            raise CoreError("MEDIA_OUTPUT_LIMIT", "Serialized media result exceeds cap", 4)
        response = {"ok": True, "data": result}
    except CoreError as error:
        response = {"ok": False, "code": error.code, "reason": error.reason, "exit": error.exit_code}
    except Exception as error:
        response = {
            "ok": False,
            "code": "MEDIA_INVALID",
            "reason": "Media engine/parser rejected malformed or unsupported data; no invented result",
            "exit": 2,
        }
    sys.stdout.buffer.write(canonical(response))


if __name__ == "__main__":
    main()
