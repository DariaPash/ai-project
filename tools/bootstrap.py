"""Explicit optional-runtime setup, without planning files, credentials or model calls.

Writes are project-local, locked and no-overwrite. Failed/unfinished installs
retain receipts/files for reconciliation, never automatic retry.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import time
import urllib.parse
import urllib.request

from .errors import CoreError
from .safeio import SafeRoot, canonical, parts

MCP_ENTRY = ".local/integrations/filesystem-mcp/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js"
DOWNLOAD_HOSTS = {
    "codeload.github.com",
    "huggingface.co",
    "cdn-lfs.huggingface.co",
    "cdn-lfs-us-1.hf.co",
    "cas-bridge.xethub.hf.co",
}


def now():
    return datetime.now(timezone.utc).isoformat()


def file_hash(path, cap=256 * 1024 * 1024):
    """Read only a named regular file, never a credential directory."""
    path = Path(path)
    if not path.is_absolute():
        raise CoreError("BOOTSTRAP_PATH", "Runtime executable must be absolute", 4)
    with SafeRoot(path.parent) as root:
        return hashlib.sha256(root.read(path.name, cap)).hexdigest()


def executable(name):
    found = shutil.which(name)
    if not found:
        raise CoreError("BOOTSTRAP_UNAVAILABLE", "Required executable is not installed: " + name, 3)
    path = Path(found).resolve(strict=True)
    return str(path), file_hash(path)


def pinned_local(root, path, cap):
    parts(path)
    if not path.startswith(".local/"):
        raise CoreError("BOOTSTRAP_PATH", "Runtime must stay in project-local storage", 4)
    return hashlib.sha256(root.read(path, cap)).hexdigest()


def _run(args, cwd, timeout):
    # No inherited API keys, npm tokens, global HOME config or provider auth.
    env = {"PATH": os.defpath, "HOME": str(cwd), "TMPDIR": str(cwd), "LANG": "C.UTF-8"}
    if Path(args[0]).name.startswith("node"):
        env["PATH"] = str(Path(args[0]).parent) + os.pathsep + os.defpath
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise CoreError("BOOTSTRAP_TIMEOUT", "Setup timed out; inspect retained receipt before retry", 5) from exc
    if result.returncode:
        raise CoreError("BOOTSTRAP_INSTALL_FAILED", "Setup command failed; retained files must be reconciled", 5)


def _download_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in DOWNLOAD_HOSTS
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise CoreError("BOOTSTRAP_DOWNLOAD_HOST", "Download/redirect host is outside the bounded setup allowlist", 4)
    return url


class _Redirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 4

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, _download_url(newurl))


def _download(root, url, destination, expected_hash, cap):
    if not re.fullmatch(r"[a-f0-9]{64}", expected_hash or ""):
        raise CoreError("BOOTSTRAP_HASH", "Explicit SHA-256 pin is required")
    if root.exists(destination):
        raise CoreError("BOOTSTRAP_EXISTS", "Existing download must be reconciled, not overwritten", 7)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _Redirect())
    chunks, size = [], 0
    deadline = time.monotonic() + 180
    with opener.open(_download_url(url), timeout=60) as response:
        while True:
            if time.monotonic() > deadline:
                raise CoreError("BOOTSTRAP_TIMEOUT", "Download exceeded bounded setup deadline", 5)
            block = response.read1(min(65536, cap + 1 - size))
            if not block:
                break
            chunks.append(block)
            size += len(block)
            if size > cap:
                raise CoreError("BOOTSTRAP_DOWNLOAD_LIMIT", "Download exceeds setup byte cap", 4)
    raw = b"".join(chunks)
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise CoreError("BOOTSTRAP_HASH", "Downloaded artifact differs from explicit pin", 6)
    root.write(destination, raw, immutable=True)


def _speech(root, args):
    version = args.version
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", version or ""):
        raise CoreError("BOOTSTRAP_VERSION", "Speech requires an exact vN.N.N version")
    if not re.fullmatch(r"[a-f0-9]{40}", args.model_revision or ""):
        raise CoreError("BOOTSTRAP_VERSION", "Model requires an immutable 40-hex revision")
    for value in (args.source_sha256, args.model_sha256):
        if not re.fullmatch(r"[a-f0-9]{64}", value or ""):
            raise CoreError("BOOTSTRAP_HASH", "Explicit source and model SHA-256 pins are required")
    cmake, _ = executable("cmake")
    stage = ".local/integrations/whisper.cpp-" + version
    root.mkdir_exclusive(stage)
    archive_path = stage + "/source.tar.gz"
    _download(
        root,
        "https://codeload.github.com/ggml-org/whisper.cpp/tar.gz/refs/tags/" + version,
        archive_path,
        args.source_sha256,
        64 * 1024 * 1024,
    )
    # Ordinary source files/directories only; no links, devices or traversal.
    import io

    with tarfile.open(fileobj=io.BytesIO(root.read(archive_path, 64 * 1024 * 1024))) as archive:
        members = archive.getmembers()
        prefix = "whisper.cpp-" + version[1:]
        if len(members) > 20000 or sum(m.size for m in members) > 256 * 1024 * 1024:
            raise CoreError("BOOTSTRAP_ARCHIVE_LIMIT", "Source archive exceeds cap", 4)
        for member in members:
            components = parts(member.name)
            if components[0] != prefix or not (member.isfile() or member.isdir()):
                raise CoreError("BOOTSTRAP_ARCHIVE_PATH", "Unexpected archive path/type", 4)
            destination = stage + "/source/" + "/".join(components)
            if member.isdir():
                with root.directory(parts(destination), create=True):
                    pass
            else:
                with archive.extractfile(member) as stream:
                    root.write(destination, stream.read(member.size + 1), immutable=True)
    source = str(root.path / stage / "source" / prefix)
    build = str(root.path / stage / "build")
    _run(
        [
            cmake,
            "-S",
            source,
            "-B",
            build,
            "-DCMAKE_BUILD_TYPE=Release",
            "-DWHISPER_BUILD_TESTS=OFF",
            "-DWHISPER_BUILD_EXAMPLES=ON",
            "-DGGML_METAL=OFF",
            "-DGGML_OPENMP=OFF",
        ],
        root.path / stage,
        120,
    )
    _run([cmake, "--build", build, "--target", "whisper-cli", "-j", "4"], root.path / stage, 600)
    model = ".local/models/ggml-base.bin"
    _download(
        root,
        "https://huggingface.co/ggerganov/whisper.cpp/resolve/" + args.model_revision + "/ggml-base.bin",
        model,
        args.model_sha256,
        200 * 1024 * 1024,
    )
    binary = stage + "/build/bin/whisper-cli"
    return ".local/speech-runtime.json", {
        "schema_version": 1,
        "engine": "whisper.cpp",
        "version": version,
        "executable": binary,
        "executable_sha256": pinned_local(root, binary, 64 * 1024 * 1024),
        "model": model,
        "model_sha256": args.model_sha256,
        "model_revision": args.model_revision,
        "model_id": "ggerganov/whisper.cpp/ggml-base.bin",
        "network_during_recognition": False,
        "languages": ["eng", "rus"],
    }


def _mcp(root, args):
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", args.version or ""):
        raise CoreError("BOOTSTRAP_VERSION", "MCP requires an exact N.N.N package version")
    node, node_hash = executable("node")
    npm, _ = executable("npm")
    stage = ".local/integrations/filesystem-mcp"
    root.mkdir_exclusive(stage)
    root.write(stage + "/empty.npmrc", b"")
    root.write(stage + "/empty-global.npmrc", b"")
    # npm's JS entrypoint is invoked with the pinned Node and isolated HOME.
    _run(
        [
            node,
            npm,
            "install",
            "--prefix",
            str(root.path / stage),
            "--ignore-scripts",
            "--no-audit",
            "--no-fund",
            "--fetch-retries=0",
            "--fetch-timeout=30000",
            "--registry=https://registry.npmjs.org",
            "--userconfig=" + str(root.path / stage / "empty.npmrc"),
            "--globalconfig=" + str(root.path / stage / "empty-global.npmrc"),
            "@modelcontextprotocol/server-filesystem@" + args.version,
        ],
        root.path / stage,
        180,
    )
    return ".local/filesystem-mcp-runtime.json", {
        "schema_version": 1,
        "version": args.version,
        "node": node,
        "node_sha256": node_hash,
        "entrypoint": MCP_ENTRY,
        "entrypoint_sha256": pinned_local(root, MCP_ENTRY, 8 * 1024 * 1024),
        "lock_sha256": pinned_local(root, stage + "/package-lock.json", 8 * 1024 * 1024),
    }


def setup(project, args):
    if not args.approve_download:
        raise CoreError("BOOTSTRAP_APPROVAL", "Setup requires the operator's explicit --approve-download", 3)
    target = {"speech": ".local/speech-runtime.json", "mcp": ".local/filesystem-mcp-runtime.json"}[args.component]
    with SafeRoot(project) as root, root.lock(".local/bootstrap.lock"):
        if root.exists(target):
            raise CoreError("BOOTSTRAP_EXISTS", "Existing runtime is preserved; inspect before any reinstall", 7)
        receipt = ".local/bootstrap/" + args.component + "-install.json"
        if root.exists(receipt):
            raise CoreError("BOOTSTRAP_RECONCILE", "A setup receipt already exists; inspect before another attempt", 3)
        report = {
            "schema_version": 1,
            "component": args.component,
            "at": now(),
            "status": "started",
            "operator_approved_download": True,
            "live_verification": "not_performed",
        }
        report["requested"] = {"version": args.version}
        if args.component == "speech":
            report["requested"].update(
                model_revision=args.model_revision, source_sha256=args.source_sha256, model_sha256=args.model_sha256
            )
        report["request_sha256"] = hashlib.sha256(canonical(report["requested"])).hexdigest()
        root.write(receipt, canonical(report))
        try:
            path, runtime = (_speech if args.component == "speech" else _mcp)(root, args)
            runtime["approval_receipt"] = receipt
            info = os.fstat(root.fd)
            runtime["local_root"] = {"device": info.st_dev, "inode": info.st_ino}
            root.write(path, canonical(runtime), immutable=True)
        except Exception as error:
            report.update(status="failed_or_incomplete", error_code=getattr(error, "code", type(error).__name__))
            root.write(receipt, canonical(report))
            raise
        report.update(status="installed_not_live_verified", completed_at=now(), runtime=path)
        root.write(receipt, canonical(report))
        return report


def init_budget(
    project,
    *,
    total_budget,
    leader_session,
    prior_consumption_upper_usd,
    unknown_reserve_usd=None,
    approve_local_setup=False,
):
    """Create a NEW ledger; never baseline away current/historic usage.

    All current leader usage is counted from zero at the next approved refresh.
    Unknown prior usage requires a positive conservative reserve, never zero.
    """
    if not approve_local_setup:
        raise CoreError("BOOTSTRAP_APPROVAL", "Budget creation requires explicit --approve-local-setup", 3)

    def money(value, positive=False):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
            or (positive and value == 0)
        ):
            raise CoreError("BOOTSTRAP_BUDGET", "Budget amounts must be finite and nonnegative")

    money(total_budget, True)
    if not re.fullmatch(r"ses_[A-Za-z0-9_]+", leader_session or ""):
        raise CoreError("BOOTSTRAP_SESSION", "Explicit current leader session identity is required")
    if prior_consumption_upper_usd is None:
        money(unknown_reserve_usd, True)
    else:
        money(prior_consumption_upper_usd)
        if unknown_reserve_usd is not None:
            money(unknown_reserve_usd, True)
    with SafeRoot(project) as root, root.lock(".local/subscription-budget.lock"):
        path = ".local/subscription-budget.json"
        if root.exists(path):
            return {"status": "existing_preserved", "ledger": path, "usage_reset": False}
        command, command_hash = executable("opencode")
        profile = ".local/opencode-runtime.json"
        if root.exists(profile):
            raise CoreError("BOOTSTRAP_EXISTS", "Existing OpenCode runtime must be inspected, not replaced", 7)
        known, reserve = prior_consumption_upper_usd, unknown_reserve_usd or 0
        state = {
            "schema_version": 1,
            "created_at": now(),
            "limit_USD": total_budget,
            "leader_session": leader_session,
            "baseline_upper_USD": 0,
            "other_sessions": ([{"id": "operator-prior-consumption", "upper_USD": known}] if known else []),
            "reservations": (
                [{"id": "bootstrap-unknown-prior", "USD": reserve, "status": "outcome_unknown"}] if reserve else []
            ),
            "prior_consumption_upper_USD": known,
            "measured_additional_API_equivalent_upper_USD": None,
            "available_API_equivalent_USD": None,
            "subscription_quota_remaining": None,
            "limitations": [
                "Current leader usage not read; refresh before dispatch. Baseline is zero, not historic usage.",
                "Unknown consumption is reserved, not reported as zero; subscription quota is unknown.",
                "Local setup is not data-transfer/model-call permission or live verification.",
            ],
        }
        info = os.fstat(root.fd)
        state["local_root"] = {"device": info.st_dev, "inode": info.st_ino}
        root.write(
            profile,
            canonical(
                {
                    "schema_version": 1,
                    "executable": command,
                    "executable_sha256": command_hash,
                    "local_root": state["local_root"],
                }
            ),
            immutable=True,
        )
        root.write(path, canonical(state), immutable=True)
        return {
            "status": "initialized_not_refreshed",
            "ledger": path,
            "runtime": profile,
            "usage_reset": False,
            "available_API_equivalent_USD": None,
        }


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="Read-only runtime diagnostics; no execution/network")
    inspect.add_argument("--project", type=Path, default=Path.cwd())
    install = commands.add_parser("setup", help="Explicit optional download/build setup")
    components = install.add_subparsers(dest="component", required=True)
    for name in ("speech", "mcp"):
        group = components.add_parser(name)
        group.add_argument("--project", type=Path, default=Path.cwd())
        group.add_argument("--approve-download", action="store_true")
        group.add_argument("--version", required=True)
        if name == "speech":
            group.add_argument("--source-sha256", required=True)
            group.add_argument("--model-sha256", required=True)
            group.add_argument("--model-revision", required=True)
    budget = commands.add_parser("budget-init", help="Create local budget; no credentials/host API calls")
    budget.add_argument("--project", type=Path, default=Path.cwd())
    budget.add_argument("--total-budget", type=float, required=True)
    budget.add_argument("--leader-session", required=True)
    prior = budget.add_mutually_exclusive_group(required=True)
    prior.add_argument("--prior-consumption-upper-usd", type=float)
    prior.add_argument("--prior-consumption-unknown", action="store_true")
    budget.add_argument("--unknown-reserve-usd", type=float)
    budget.add_argument("--approve-local-setup", action="store_true")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "inspect":
            from .diagnostics import diagnostics

            data = diagnostics(args.project)
        elif args.command == "setup":
            data = setup(args.project, args)
        else:
            data = init_budget(
                args.project,
                total_budget=args.total_budget,
                leader_session=args.leader_session,
                prior_consumption_upper_usd=args.prior_consumption_upper_usd,
                unknown_reserve_usd=args.unknown_reserve_usd,
                approve_local_setup=args.approve_local_setup,
            )
        print(canonical({"ok": True, "data": data}).decode())
        return 0
    except (CoreError, OSError, tarfile.TarError) as error:
        print(
            canonical(
                {
                    "ok": False,
                    "code": getattr(error, "code", "BOOTSTRAP_IO"),
                    "error": getattr(error, "reason", "Setup unavailable/incomplete; inspect retained receipt"),
                }
            ).decode()
        )
        return getattr(error, "exit_code", 5)


if __name__ == "__main__":
    raise SystemExit(main())
