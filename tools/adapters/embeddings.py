"""Installed local Apple sentence vectors, with child network denied and no downloads."""

from importlib.resources import files
import json
import math
from pathlib import Path
import subprocess
import tempfile
import time
from .base import run

from ..errors import CoreError
from ..safeio import canonical, parse_json


def execute(texts):
    if (
        not isinstance(texts, list)
        or not 1 <= len(texts) <= 128
        or any(not isinstance(t, str) or len(t) > 1600 for t in texts)
    ):
        raise CoreError("EMBEDDING_LIMIT", "At most128 local text chunks of1600 characters")
    base = Path(tempfile.gettempdir()).resolve()
    approved = base / "opencode"
    if approved.is_dir() and not approved.is_symlink():
        base = approved
    with tempfile.TemporaryDirectory(prefix="local-embeddings-", dir=base) as folder:
        stage = Path(folder)
        script = stage / "embeddings.swift"
        script.write_bytes(files("tools.adapters").joinpath("apple_embeddings.swift").read_bytes())
        input_path = stage / "texts.json"
        input_path.write_bytes(canonical(texts))
        args = [
            "/usr/bin/sandbox-exec",
            "-p",
            "(version 1)(allow default)(deny network*)",
            "/usr/bin/swift",
            "-module-cache-path",
            str(base / "swift-module-cache"),
            str(script),
            str(input_path),
        ]
        try:
            raw_output = run(args, time.monotonic() + 60)
        except CoreError as error:
            raise CoreError(
                "EMBEDDING_TIMEOUT" if error.exit_code == 5 else "EMBEDDING_UNAVAILABLE",
                "Local embedding failed under bounded execution; no retry/cloud/download fallback",
                5 if error.exit_code == 5 else 3,
            ) from error
    output = parse_json(raw_output)
    if output.get("unavailable"):
        raise CoreError(
            "EMBEDDING_UNAVAILABLE", "Installed English sentence embedding unavailable; nothing downloaded", 3
        )
    vectors = output.get("vectors", [])
    dimension = output.get("dimension")
    if len(vectors) != len(texts) or not isinstance(dimension, int) or not 1 <= dimension <= 4096:
        raise CoreError("EMBEDDING_OUTPUT", "Invalid local vector metadata")
    for vector in vectors:
        if len(vector) != dimension or any(not isinstance(n, (int, float)) or not math.isfinite(n) for n in vector):
            raise CoreError("EMBEDDING_OUTPUT", "Invalid/nonfinite vector")
        norm = math.sqrt(sum(n * n for n in vector))
        if not norm:
            raise CoreError("EMBEDDING_OUTPUT", "Empty sentence vector")
        for i in range(len(vector)):
            vector[i] /= norm
    return output
