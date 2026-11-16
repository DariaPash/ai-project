"""Regressions for independent review findings; doubles are not live STT proof."""

import copy
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from tools.adapters.base import AdapterRequest, run, bounded_read
from tools.adapters import stt, video
from tools.contracts import sha
from tools.errors import CoreError
from tools import media
from tools.store import Store
from .helpers import PROJECT, init
from .step04_helpers import spec, prepare_media, import_media


def alive(pid):
    result = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return result.returncode == 0 and bool(result.stdout.strip()) and not result.stdout.strip().startswith("Z")


def assert_reaped(pid):
    deadline = time.monotonic() + 2
    while alive(pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not alive(pid)


@pytest.mark.parametrize("inherit_pipes", [True, False])
def test_parent_exit_does_not_leave_sleeping_descendant(tmp_path, inherit_pipes):
    receipt = tmp_path / "pid"
    code = (
        "import subprocess,sys; from pathlib import Path; "
        'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"],'
        + ("" if inherit_pipes else "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,")
        + ");Path(sys.argv[1]).write_text(str(p.pid))"
    )
    try:
        if inherit_pipes:
            with pytest.raises(CoreError) as error:
                run([sys.executable, "-c", code, str(receipt)], time.monotonic() + 0.5)
            assert error.value.code == "MEDIA_TIMEOUT"
        else:
            run([sys.executable, "-c", code, str(receipt)], time.monotonic() + 2)
        assert_reaped(int(receipt.read_text()))
    finally:
        if receipt.exists() and alive(int(receipt.read_text())):
            os.kill(int(receipt.read_text()), 9)


def test_outer_worker_timeout_reaps_engine_group(monkeypatch, tmp_path):
    receipt = tmp_path / "pid"
    real_popen = subprocess.Popen
    code = (
        "import subprocess,sys,time;from pathlib import Path;"
        'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"]);'
        f"Path({str(receipt)!r}).write_text(str(p.pid));time.sleep(30)"
    )

    def fake_worker(args, **kwargs):
        return real_popen([sys.executable, "-c", code], **kwargs)

    with monkeypatch.context() as context:
        context.setattr(media.subprocess, "Popen", fake_worker)
        profile = spec("image")
        profile["limits"]["timeout_ms"] = 100
        with pytest.raises(CoreError) as error:
            media.parse(b"x", profile)
        assert error.value.code == "MEDIA_TIMEOUT"
    assert_reaped(int(receipt.read_text()))


def test_unlistened_high_confidence_words_are_uncertain(monkeypatch, tmp_path):
    monkeypatch.setattr(stt, "runtime_configured", lambda: False)
    raw = (PROJECT / "tests/fixtures/media/speech.wav").read_bytes()
    result = {
        "status": "ok",
        "segments": [
            {"start_ms": i * 200, "end_ms": i * 200 + 100, "text": word, "confidence": 0.99}
            for i, word in enumerate(["twenty", "never", "million", "без", "обычное"])
        ],
    }
    monkeypatch.setattr(stt, "run", lambda *a, **k: json.dumps(result).encode())
    monkeypatch.setattr(stt, "executable", lambda *a: "/usr/bin/swift")
    monkeypatch.setattr(stt, "profile", lambda *a: {"engine": "protocol_double"})
    parsed = stt.execute(AdapterRequest(raw, sha(raw), spec("audio"), time.monotonic() + 5), tmp_path)
    assert all(s["uncertain"] for s in parsed["segments"])


def test_delayed_audio_explicitly_unavailable(monkeypatch, tmp_path):
    metadata = {
        "format": {"duration": "4"},
        "streams": [
            {
                "codec_type": "video",
                "width": 10,
                "height": 10,
                "avg_frame_rate": "25",
                "r_frame_rate": "25",
                "nb_frames": "100",
                "start_time": "0",
            },
            {"codec_type": "audio", "start_time": "2", "duration": "2"},
        ],
    }
    monkeypatch.setattr(
        video,
        "run",
        lambda args, *a, **k: json.dumps(
            {"frames": [{"best_effort_timestamp_time": str(i / 25)} for i in range(100)]}
            if "-show_frames" in args
            else metadata
        ).encode(),
    )
    monkeypatch.setattr(video, "executable", lambda name: name)
    with pytest.raises(CoreError) as error:
        video.execute(
            AdapterRequest(b"0000ftyp" + b"0" * 8, "", spec("video", mode="audio_only"), time.monotonic() + 5), tmp_path
        )
    assert error.value.code == "VIDEO_AUDIO_TIMING"


def test_derived_file_hard_cap_and_bounded_read(tmp_path):
    output = tmp_path / "large"
    with pytest.raises(CoreError) as error:
        run(
            [sys.executable, "-c", 'import sys;open(sys.argv[1],"wb").write(b"x"*10000)', str(output)],
            time.monotonic() + 5,
            file_cap=100,
            output_files=(output,),
        )
    assert error.value.code == "MEDIA_OUTPUT_LIMIT"
    assert output.stat().st_size <= 100
    output.write_bytes(b"x" * 101)
    with pytest.raises(CoreError):
        bounded_read(output, 100)


@pytest.mark.parametrize(
    "format_name,options",
    [("video", {"mode": "audio_only"}), ("video", {"mode": "sampled_frames", "timestamps_ms": [0]}), ("scan_pdf", {})],
)
def test_tiny_derived_cap_fails_without_oversized_files(format_name, options):
    names = {"video": "event.mp4", "scan_pdf": "scan.pdf"}
    profile = spec(format_name, **options)
    profile["limits"]["max_output_bytes"] = 100
    with pytest.raises(CoreError) as error:
        media.parse((PROJECT / "tests/fixtures/media" / names[format_name]).read_bytes(), profile)
    assert error.value.code == "MEDIA_OUTPUT_LIMIT"


def test_locator_mutations_rejected(project):
    prepare_media(project)
    init(project)
    _, extraction = import_media(project, "video", mode="sampled_frames", timestamps_ms=[0, 4000])
    with Store(project, "test-core") as store:
        snapshot, _, _ = store._load()
        records = store.records(snapshot)
        for mutation in ("negative", "hash", "index", "dimensions", "offset", "uncertainty"):
            bad = copy.deepcopy(extraction)
            m = bad["payload"]["coverage"]["media"]
            if mutation == "negative":
                m["segments"][0]["coordinates"]["timestamp_ms"] = -1000
            if mutation == "hash":
                m["segments"][0]["coordinates"]["frame_sha256"] = "a" * 64
            if mutation == "index":
                m["segments"][0]["coordinates"]["frame_index"] = -1
            if mutation == "dimensions":
                m["children"][0]["mapping"]["width"] += 1
            if mutation == "offset":
                m["children"][0]["mapping"]["offset_ms"] = 10
            if mutation == "uncertainty":
                m["segments"][0]["uncertain"] = False
            bad["payload"]["fragments"] = [{k: s[k] for k in ("kind", "coordinates", "text")} for s in m["segments"]]
            with pytest.raises(CoreError):
                media.validate_record(bad, records, store.blob)


def test_scan_aggregate_budget_across_pages(tmp_path):
    from pypdf import PdfReader, PdfWriter
    from tools.adapters import ocr

    original = (PROJECT / "tests/fixtures/media/scan.pdf").read_bytes()
    single = tmp_path / "single"
    single.mkdir()
    initial = ocr.execute(AdapterRequest(original, sha(original), spec("scan_pdf"), time.monotonic() + 20), single)
    size = len(initial["children"][0]["raw"])
    writer = PdfWriter()
    page = PdfReader(BytesIO(original)).pages[0]
    writer.add_page(page)
    writer.add_page(page)
    out = BytesIO()
    writer.write(out)
    profile = spec("scan_pdf")
    profile["limits"]["max_output_bytes"] = size + 100
    target = tmp_path / "double"
    target.mkdir()
    with pytest.raises(CoreError) as error:
        ocr.execute(AdapterRequest(out.getvalue(), "", profile, time.monotonic() + 20), target)
    assert error.value.code == "MEDIA_OUTPUT_LIMIT"
    assert sum(p.stat().st_size for p in target.glob("page-*.png")) <= size + 100


def test_equal_declared_fps_with_irregular_pts_is_rejected(tmp_path):
    import struct

    raw = bytearray((PROJECT / "tests/fixtures/media/event.mp4").read_bytes())
    location = raw.index(b"ctts")
    offset = location + 16 + 10 * 8
    original = struct.unpack_from(">I", raw, offset)[0]
    struct.pack_into(">I", raw, offset, original + 256)
    path = tmp_path / "irregular.mp4"
    path.write_bytes(raw)
    metadata = json.loads(
        run(
            [
                video.executable("ffprobe"),
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_streams",
                "-of",
                "json",
                str(path),
            ],
            time.monotonic() + 5,
        )
    )
    assert metadata["streams"][0]["avg_frame_rate"] == metadata["streams"][0]["r_frame_rate"] == "25/1"
    with pytest.raises(CoreError) as error:
        video.execute(
            AdapterRequest(
                bytes(raw), sha(raw), spec("video", mode="sampled_frames", timestamps_ms=[0, 80]), time.monotonic() + 10
            ),
            tmp_path,
        )
    assert error.value.code == "VIDEO_TIMING"


@pytest.mark.parametrize(
    "terms",
    [
        None,
        {},
        {
            "operation": "doctor:formats",
            "engines": ["ffprobe"],
            "source_refs": [],
            "processing": False,
            "expires_at": "2099-01-01T00:00:00Z",
        },
        {
            "operation": "doctor:formats",
            "engines": ["ffprobe"],
            "source_refs": [],
            "processing": True,
            "expires_at": "2000-01-01T00:00:00Z",
        },
    ],
)
def test_probe_denied_before_engine_calls(project, monkeypatch, terms):
    from tools import formats_probe
    from .step03_helpers import Fixture

    init(project)
    f = Fixture(project)
    approval_id = "APR-999"
    if terms is not None:
        approval_id = f.approve("source_access", [], terms)["entity_id"]
    calls = []
    monkeypatch.setattr("tools.adapters.base.probe", lambda *a, **k: calls.append(True))
    with Store(project, "test-core") as store:
        with pytest.raises(CoreError) as error:
            formats_probe.run(store, approval_id, store.status()["case_revision"])
        assert error.value.code == "APPROVAL_REQUIRED"
    assert calls == []


def test_probe_scope_and_corpus_fingerprint(project, monkeypatch):
    from tools import formats_probe
    from .step03_helpers import Fixture

    init(project)
    f = Fixture(project)
    terms = {
        "operation": "doctor:formats",
        "engines": ["ffprobe"],
        "source_refs": [],
        "processing": True,
        "expires_at": "2099-01-01T00:00:00Z",
    }
    approval = f.approve("source_access", [], terms)
    reports = []

    def probe(config, live=False):
        reports.append(config)
        return {"engines": {"ffprobe": {"version": str(len(reports))}}, "network_used": False}

    monkeypatch.setattr("tools.adapters.base.probe", probe)
    with Store(project, "test-core") as store:
        first = formats_probe.run(store, approval["entity_id"], store.status()["case_revision"])
        second = formats_probe.run(store, approval["entity_id"], store.status()["case_revision"])
    assert first["data"]["capability_report_ref"] != second["data"]["capability_report_ref"]
    assert reports == [{"engines": ["ffprobe"]}, {"engines": ["ffprobe"]}]
