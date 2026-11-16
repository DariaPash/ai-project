"""Bounded local execution utilities and typed, immutable adapter inputs."""

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import selectors
import signal
import resource
import time

from ..contracts import sha
from ..errors import CoreError


@dataclass(frozen=True)
class AdapterRequest:
    raw: bytes
    source_sha256: str
    spec: dict
    deadline: float


def executable(name):
    if name not in {"tesseract", "pdftoppm", "ffmpeg", "ffprobe", "swift"}:
        raise CoreError("ENGINE_DENIED", "Adapter executable is not allowlisted", 4)
    path = shutil.which(name, path="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin")
    if not path:
        raise CoreError("ENGINE_UNAVAILABLE", "Required local " + name + " executable is unavailable", 3)
    return path


def bounded_read(path, cap):
    """Check before allocation and use a bounded read even if the file changes."""
    if path.stat().st_size > cap:
        raise CoreError("MEDIA_OUTPUT_LIMIT", "Derived file exceeds remaining aggregate budget", 4)
    with path.open("rb") as stream:
        raw = stream.read(cap + 1)
    if len(raw) > cap:
        raise CoreError("MEDIA_OUTPUT_LIMIT", "Derived file exceeds remaining aggregate budget", 4)
    return raw


def run(args, deadline, cap=8388608, *, file_cap=None, output_files=()):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise CoreError("MEDIA_TIMEOUT", "Total local processing deadline expired", 5)
    in_worker = os.environ.get("STRATEGIST_LOCAL_MEDIA_WORKER_PGID") == str(os.getpgrp())
    if file_cap is not None and file_cap < 1:
        raise CoreError("MEDIA_OUTPUT_LIMIT", "No remaining derived-file budget", 4)

    def limit_files():
        resource.setrlimit(resource.RLIMIT_FSIZE, (file_cap, file_cap))

    process = subprocess.Popen(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=not in_worker,
        preexec_fn=limit_files if file_cap is not None else None,
        env={"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", "LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    try:
        with selectors.DefaultSelector() as selector:
            for name, stream in [("stdout", process.stdout), ("stderr", process.stderr)]:
                selector.register(stream, selectors.EVENT_READ, name)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CoreError("MEDIA_TIMEOUT", "Local engine exceeded the total deadline; no retry", 5)
                for item, _ in selector.select(remaining):
                    raw = os.read(item.fileobj.fileno(), 65536)
                    if not raw:
                        selector.unregister(item.fileobj)
                        continue
                    buffers[item.data].extend(raw)
                    if len(buffers[item.data]) > (cap if item.data == "stdout" else 65536):
                        raise CoreError("MEDIA_OUTPUT_LIMIT", "Engine stream exceeded its byte cap", 4)
        try:
            process.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as error:
            raise CoreError("MEDIA_TIMEOUT", "Local engine exceeded the total deadline; no retry", 5) from error
        if file_cap is not None and any(p.exists() and p.stat().st_size >= file_cap for p in output_files):
            raise CoreError(
                "MEDIA_OUTPUT_LIMIT", "Derived file reached its hard size cap; truncation is not success", 4
            )
        if process.returncode:
            if file_cap is not None and (
                process.returncode == -signal.SIGXFSZ or b"File too large" in buffers["stderr"]
            ):
                raise CoreError("MEDIA_OUTPUT_LIMIT", "Engine reached its hard file-size cap", 4)
            raise CoreError("MEDIA_CORRUPT", "Local engine rejected input; raw diagnostics are not exposed", 2)
        return bytes(buffers["stdout"])
    finally:
        if not in_worker:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()
        process.stderr.close()


def profile(name):
    path = executable(name)
    args = (
        [path, "-v"]
        if name == "pdftoppm"
        else [path, "--version"]
        if name == "tesseract"
        else [path, "--version"]
        if name == "swift"
        else [path, "-version"]
    )
    process = subprocess.run(args, capture_output=True, timeout=10, env={"PATH": os.defpath})
    text = (process.stdout + process.stderr).decode("utf-8", errors="replace").splitlines()
    return {
        "engine": name,
        "version": text[0] if text else "unknown",
        "executable": path,
        "executable_sha256": sha(Path(path).read_bytes()),
    }


def probe(config=None, live=False):
    names = (config or {}).get("engines", ["tesseract", "pdftoppm", "ffmpeg", "ffprobe"])
    result = {}
    for name in names:
        try:
            result[name] = {"status": "installed_not_processing_verified", **profile(name)}
        except CoreError as error:
            result[name] = {"status": "unavailable", "reason": error.reason}
    return {"network_used": False, "live_processing_performed": False, "engines": result}
