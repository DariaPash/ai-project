import json
import os
import shutil

import pytest

from tools import bootstrap
from tools.diagnostics import diagnostics, speech_runtime
from tools.errors import CoreError
from tools.safeio import SafeRoot, canonical
from .test_bootstrap import binary


def speech(project):
    executable = ".local/integrations/whisper.cpp-v1.9.5/build/bin/whisper-cli"
    _, digest = binary(project / executable)
    with SafeRoot(project) as root:
        root.write(".local/models/ggml-base.bin", b"model")
        root.write(
            ".local/speech-runtime.json",
            canonical(
                {
                    "schema_version": 1,
                    "local_root": {"device": os.fstat(root.fd).st_dev, "inode": os.fstat(root.fd).st_ino},
                    "executable": executable,
                    "executable_sha256": digest,
                    "model": ".local/models/ggml-base.bin",
                    "model_sha256": bootstrap.hashlib.sha256(b"model").hexdigest(),
                }
            ),
        )


def test_no_installed_optional_components_is_not_unimplemented(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda *a, **k: pytest.fail("execution"))
    with SafeRoot(tmp_path) as root:
        root.write(".local/capabilities.json", b'{"stt":"live_verified"}')
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = diagnostics(tmp_path)
    for entry in result["capabilities"].values():
        assert entry["implementation"] == "implemented"
        assert entry["live_verification"] == "not_performed"
    assert result["capabilities"]["stt"]["availability"] == "unavailable"
    assert {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


def test_installed_speech_hashes_not_old_receipts(tmp_path):
    speech(tmp_path)
    assert speech_runtime(tmp_path)["schema_version"] == 1
    assert diagnostics(tmp_path)["capabilities"]["stt"]["reason"] in {
        "installed_profile_hashes_match",
        "network_deny_sandbox_unavailable",
    }
    (tmp_path / ".local/models/ggml-base.bin").write_bytes(b"modified")
    result = diagnostics(tmp_path)["capabilities"]["stt"]
    assert result["availability"] == "unavailable" and result["reason"] == "STT_RUNTIME_HASH"


def test_profile_cannot_point_to_arbitrary_local_secret(tmp_path):
    speech(tmp_path)
    path = tmp_path / ".local/speech-runtime.json"
    config = json.loads(path.read_text())
    config["model"] = ".local/credentials.json"
    path.write_text(json.dumps(config))
    assert diagnostics(tmp_path)["capabilities"]["stt"]["reason"] == "STT_RUNTIME_PATH"


def test_copied_runtime_does_not_inherit_root_binding(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    speech(source)
    path = source / ".local/speech-runtime.json"
    config = json.loads(path.read_text())
    info = source.stat()
    config["local_root"] = {"device": info.st_dev, "inode": info.st_ino}
    path.write_text(json.dumps(config))
    shutil.copytree(source, target)
    with pytest.raises(CoreError, match="another installation"):
        speech_runtime(target)
    assert diagnostics(target)["capabilities"]["stt"]["reason"] == "RUNTIME_IMPORTED"


def test_absent_local_directory_is_usefully_unavailable(tmp_path):
    result = diagnostics(tmp_path)
    for name in ("stt", "mcp", "opencode"):
        assert result["capabilities"][name]["reason"] == "runtime_not_configured"
    assert list(tmp_path.iterdir()) == []


def test_unbound_profile_does_not_gain_installation_trust(tmp_path):
    speech(tmp_path)
    path = tmp_path / ".local/speech-runtime.json"
    config = json.loads(path.read_text())
    del config["local_root"]
    path.write_text(json.dumps(config))
    assert diagnostics(tmp_path)["capabilities"]["stt"]["reason"] == "RUNTIME_IMPORTED"


@pytest.mark.parametrize(
    "module,hook,validator,code",
    [
        ("mcp_client", "installed", "mcp_runtime", "MCP_UNAVAILABLE"),
        ("stt_whisper", "runtime", "speech_runtime", "STT_UNAVAILABLE"),
    ],
)
def test_adapter_uses_narrow_validator_and_current_root(tmp_path, monkeypatch, module, hook, validator, code):
    import importlib
    from tools import diagnostics as diagnostic_module

    adapter = importlib.import_module("tools.adapters." + module)
    monkeypatch.setattr(adapter, "ROOT", tmp_path)
    with pytest.raises(CoreError) as error:
        getattr(adapter, hook)()
    assert error.value.code == code
    calls = []
    monkeypatch.setattr(diagnostic_module, validator, lambda project: calls.append(project) or {"mock": True})
    assert getattr(adapter, hook)() == {"mock": True}
    assert calls == [tmp_path]
