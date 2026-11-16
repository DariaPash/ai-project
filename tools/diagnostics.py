"""Read-only diagnostics: implementation != installation != live proof.

No binary execution, models, downloads, credentials or old capability receipts.
"""

import importlib.util
import os
from pathlib import Path
import platform
import re
import shutil

from .bootstrap import MCP_ENTRY, file_hash, pinned_local
from .errors import CoreError
from .safeio import SafeRoot


def _profile(root, path):
    if not root.exists(".local") or not root.exists(path):
        raise FileNotFoundError(path)
    data = root.json(path)
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise CoreError("RUNTIME_SCHEMA", "Unknown runtime profile version", 6)
    info = os.fstat(root.fd)
    binding = data.get("local_root")
    if binding != {"device": info.st_dev, "inode": info.st_ino}:
        raise CoreError("RUNTIME_IMPORTED", "Runtime belongs to another installation; fresh setup required", 3)
    return data


def _external(data, field, names):
    path = Path(data[field])
    if not path.is_absolute() or path.name not in names or not os.access(path, os.X_OK):
        raise CoreError("RUNTIME_PATH", "Pinned executable path is unavailable/invalid", 3)
    if file_hash(path) != data[field + "_sha256"]:
        raise CoreError("RUNTIME_HASH", "Pinned executable changed; inspect before use", 6)


def speech_runtime(project):
    with SafeRoot(project) as root:
        data = _profile(root, ".local/speech-runtime.json")
        binary = data["executable"]
        if (
            not re.fullmatch(r"\.local/integrations/whisper\.cpp-v[0-9.]+/build/bin/whisper-cli", binary)
            or data["model"] != ".local/models/ggml-base.bin"
        ):
            raise CoreError("STT_RUNTIME_PATH", "Unexpected speech profile path", 4)
        for field, cap in (("executable", 64 * 1024 * 1024), ("model", 200 * 1024 * 1024)):
            if pinned_local(root, data[field], cap) != data[field + "_sha256"]:
                raise CoreError("STT_RUNTIME_HASH", "Speech runtime changed; no silent reinstall", 6)
        if not os.access(root.path / binary, os.X_OK):
            raise CoreError("STT_EXECUTABLE", "Speech binary is not executable", 3)
        return data


def mcp_runtime(project):
    with SafeRoot(project) as root:
        data = _profile(root, ".local/filesystem-mcp-runtime.json")
        if data["entrypoint"] != MCP_ENTRY:
            raise CoreError("MCP_RUNTIME_PATH", "Unexpected filesystem server path", 4)
        if pinned_local(root, MCP_ENTRY, 8 * 1024 * 1024) != data["entrypoint_sha256"]:
            raise CoreError("MCP_RUNTIME_HASH", "Filesystem server entrypoint changed", 6)
        if "lock_sha256" in data:
            lock = ".local/integrations/filesystem-mcp/package-lock.json"
            if pinned_local(root, lock, 8 * 1024 * 1024) != data["lock_sha256"]:
                raise CoreError("MCP_RUNTIME_HASH", "Filesystem server lock changed", 6)
        _external(data, "node", {"node", "nodejs"})
        return data


def opencode_runtime(project):
    with SafeRoot(project) as root:
        data = _profile(root, ".local/opencode-runtime.json")
        _external(data, "executable", {"opencode"})
        return data


def _capability(availability="unavailable", reason="runtime_not_configured"):
    return {
        "implementation": "implemented",
        "availability": availability,
        "reason": reason,
        "live_verification": "not_performed",
    }


def _installed(project, loader):
    try:
        loader(project)
        return _capability("available", "installed_profile_hashes_match")
    except FileNotFoundError:
        return _capability()
    except (CoreError, KeyError, TypeError, ValueError, OSError) as error:
        return _capability(reason=getattr(error, "code", "runtime_invalid"))


def diagnostics(project):
    """Return {capabilities, ...}; local prerequisites do not prove consent/login.

    Installed model and host isolation remain unknown without execution.
    """
    speech = _installed(project, speech_runtime)
    mcp = _installed(project, mcp_runtime)
    opencode = _installed(project, opencode_runtime)
    sandbox = platform.system() == "Darwin" and Path("/usr/bin/sandbox-exec").is_file()
    for capability in (speech, mcp):
        if capability["availability"] == "available" and not sandbox:
            capability.update(availability="unavailable", reason="network_deny_sandbox_unavailable")
    if mcp["availability"] == "available" and importlib.util.find_spec("mcp") is None:
        mcp.update(availability="unavailable", reason="python_mcp_sdk_not_installed")
    if opencode["availability"] == "available":
        # Never read usage or call the token API here; no balance claim.
        try:
            with SafeRoot(project) as root:
                exists = root.exists(".local/subscription-budget.json")
            opencode.update(
                availability="unknown" if exists else "unavailable",
                reason="budget_refresh_and_sign_in_unverified" if exists else "local_budget_missing",
            )
        except CoreError as error:
            opencode.update(availability="unavailable", reason=error.code)
    embeddings = _capability(
        "unknown" if sandbox and Path("/usr/bin/swift").is_file() else "unavailable",
        "installed_english_model_unverified" if sandbox else "apple_runtime_unavailable",
    )
    return {
        "capabilities": {
            "stt": speech,
            "mcp": mcp,
            "opencode": opencode,
            "embeddings": embeddings,
            "reviewer": _capability("unknown", "actual_isolated_context_receipt_required"),
            "second_host": _capability(
                "unknown" if shutil.which("codex") else "unavailable", "client_login_and_continuation_unverified"
            ),
        },
        "network_call_performed": False,
        "model_call_performed": False,
        "downloads_performed": False,
        "imported_capabilities_trusted": False,
    }
