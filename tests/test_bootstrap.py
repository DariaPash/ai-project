import io
import json
from pathlib import Path
import tarfile
from types import SimpleNamespace

import pytest

from tools import bootstrap
from tools.contracts import sha
from tools.diagnostics import mcp_runtime, speech_runtime
from tools.errors import CoreError
from tools.safeio import SafeRoot


def args(component="mcp", **extra):
    return SimpleNamespace(component=component, approve_download=True, version="2.3.0", **extra)


def binary(path, raw=b"fake executable"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(0o700)
    return str(path), sha(raw)


def test_inspect_no_planning_or_execution(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda *a, **kw: pytest.fail("execution"))
    monkeypatch.setattr(bootstrap.urllib.request, "build_opener", lambda *a: pytest.fail("network"))
    assert bootstrap.main(["inspect", "--project", str(tmp_path)]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["capabilities"]["stt"]["implementation"] == "implemented"
    assert list(tmp_path.iterdir()) == []


def test_setup_requires_explicit_download_permission(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "_mcp", lambda *a: pytest.fail("installer"))
    request = args()
    request.approve_download = False
    with pytest.raises(CoreError, match="approve-download"):
        bootstrap.setup(tmp_path, request)
    assert not (tmp_path / ".local").exists()


def test_mcp_mock_install_pins_dynamic_node_and_preserves(tmp_path, monkeypatch):
    node = binary(tmp_path / "runtime/bin/node")
    npm = binary(tmp_path / "runtime/lib/npm-cli.js")
    monkeypatch.setattr(bootstrap, "executable", lambda name: {"node": node, "npm": npm}[name])
    calls = []

    def install(command, cwd, timeout):
        calls.append(command)
        assert "--ignore-scripts" in command and timeout == 180
        with SafeRoot(tmp_path) as root:
            root.write(bootstrap.MCP_ENTRY, b"server")
            root.write(".local/integrations/filesystem-mcp/package-lock.json", b"{}")

    monkeypatch.setattr(bootstrap, "_run", install)
    report = bootstrap.setup(tmp_path, args())
    assert report["status"] == "installed_not_live_verified"
    assert mcp_runtime(tmp_path)["node"] == node[0]
    assert calls[0][:2] == [node[0], npm[0]]
    with pytest.raises(CoreError, match="preserved"):
        bootstrap.setup(tmp_path, args())
    assert len(calls) == 1


def test_failed_install_records_attempt_no_retry(tmp_path, monkeypatch):
    def fail(*unused):
        raise CoreError("TEST_FAILURE", "mock failure", 5)

    monkeypatch.setattr(bootstrap, "_mcp", fail)
    with pytest.raises(CoreError, match="mock failure"):
        bootstrap.setup(tmp_path, args())
    receipt = json.loads((tmp_path / ".local/bootstrap/mcp-install.json").read_text())
    assert receipt["status"] == "failed_or_incomplete"
    with pytest.raises(CoreError, match="receipt already exists"):
        bootstrap.setup(tmp_path, args())


def test_mock_speech_download_and_build_without_development_files(tmp_path, monkeypatch):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo("whisper.cpp-1.9.5/CMakeLists.txt")
        info.size = 1
        archive.addfile(info, io.BytesIO(b"x"))
    source, model = buffer.getvalue(), b"fake model"
    cmake = binary(tmp_path / "runtime/cmake")
    monkeypatch.setattr(bootstrap, "executable", lambda name: cmake)

    def download(root, url, destination, digest, cap):
        raw = model if destination.endswith(".bin") else source
        assert sha(raw) == digest and len(raw) < cap
        root.write(destination, raw, immutable=True)

    def build(command, cwd, timeout):
        if "--build" in command:
            binary(Path(command[2]) / "bin/whisper-cli")

    monkeypatch.setattr(bootstrap, "_download", download)
    monkeypatch.setattr(bootstrap, "_run", build)
    request = args("speech", source_sha256=sha(source), model_sha256=sha(model), model_revision="a" * 40)
    request.version = "v1.9.5"
    bootstrap.setup(tmp_path, request)
    assert speech_runtime(tmp_path)["model_sha256"] == sha(model)
    assert not (tmp_path / "planning").exists()


def test_download_caps_hash_and_redirect_allowlist(tmp_path, monkeypatch):
    class Opener:
        def open(self, url, timeout):
            return io.BytesIO(b"abc")

    monkeypatch.setattr(bootstrap.urllib.request, "build_opener", lambda *unused: Opener())
    with SafeRoot(tmp_path) as root:
        with pytest.raises(CoreError, match="byte cap"):
            bootstrap._download(root, "https://huggingface.co/file", ".local/file", sha(b"abc"), 2)
        with pytest.raises(CoreError, match="differs"):
            bootstrap._download(root, "https://huggingface.co/file", ".local/file", "0" * 64, 4)
        assert not root.exists(".local/file")
    for url in (
        "http://huggingface.co/x",
        "https://localhost/x",
        "https://evil.test/x",
        "https://a:b@huggingface.co/x",
    ):
        with pytest.raises(CoreError):
            bootstrap._download_url(url)


@pytest.mark.parametrize("known,reserve", [(12.5, None), (None, 15)])
def test_budget_no_reset_no_baseline_erasure_or_null_to_zero(tmp_path, monkeypatch, known, reserve):
    command = binary(tmp_path / "runtime/opencode")
    monkeypatch.setattr(bootstrap, "executable", lambda name: command)
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda *a, **k: pytest.fail("host call"))
    request = dict(
        total_budget=100,
        leader_session="ses_current",
        prior_consumption_upper_usd=known,
        unknown_reserve_usd=reserve,
        approve_local_setup=True,
    )
    bootstrap.init_budget(tmp_path, **request)
    path = tmp_path / ".local/subscription-budget.json"
    raw = path.read_bytes()
    state = json.loads(raw)
    assert state["baseline_upper_USD"] == 0
    assert state["prior_consumption_upper_USD"] == known
    assert state["available_API_equivalent_USD"] is None
    if known:
        assert state["other_sessions"][0]["upper_USD"] == known
    else:
        assert state["reservations"][0]["status"] == "outcome_unknown"
    assert bootstrap.init_budget(tmp_path, **request)["status"] == "existing_preserved"
    assert path.read_bytes() == raw


@pytest.mark.parametrize("known,reserve", [(None, None), (None, 0), (-1, None), (float("nan"), None)])
def test_budget_rejects_unknown_unreserved_or_invalid(tmp_path, known, reserve):
    with pytest.raises(CoreError):
        bootstrap.init_budget(
            tmp_path,
            total_budget=100,
            leader_session="ses_current",
            prior_consumption_upper_usd=known,
            unknown_reserve_usd=reserve,
            approve_local_setup=True,
        )
    assert not (tmp_path / ".local/subscription-budget.json").exists()


def test_symlink_local_root_rejected_without_writes(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    (project / ".local").symlink_to(outside, target_is_directory=True)
    with pytest.raises(CoreError):
        bootstrap.setup(project, args())
    assert list(outside.iterdir()) == []


def test_setup_process_does_not_forward_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "canary-not-a-real-key")
    monkeypatch.setenv("NPM_TOKEN", "canary-not-a-real-token")

    def run(command, **options):
        assert "OPENAI_API_KEY" not in options["env"]
        assert "NPM_TOKEN" not in options["env"]
        assert options["env"]["HOME"] == str(tmp_path)
        assert options["timeout"] == 12
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(bootstrap.subprocess, "run", run)
    bootstrap._run(["/custom/bin/node", "/custom/npm-cli.js"], tmp_path, 12)


def test_setup_speech_compatibility_is_explicit(monkeypatch):
    from tools import setup_speech

    calls = []
    monkeypatch.setattr(setup_speech, "bootstrap_main", lambda argv: calls.append(argv) or 0)
    assert setup_speech.main(["--help"]) == 0
    assert calls == [["setup", "speech", "--help"]]


def test_speech_archive_traversal_rejected_before_build(tmp_path, monkeypatch):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo("whisper.cpp-1.9.5/../../escape")
        info.size = 1
        archive.addfile(info, io.BytesIO(b"x"))
    source = buffer.getvalue()
    monkeypatch.setattr(bootstrap, "executable", lambda name: ("/mock/cmake", "0" * 64))
    monkeypatch.setattr(bootstrap, "_download", lambda root, url, path, digest, cap: root.write(path, source))
    monkeypatch.setattr(bootstrap, "_run", lambda *a: pytest.fail("build"))
    request = args("speech", source_sha256=sha(source), model_sha256="0" * 64, model_revision="a" * 40)
    request.version = "v1.9.5"
    with pytest.raises(CoreError):
        bootstrap.setup(tmp_path, request)
    assert not (tmp_path / "escape").exists()
