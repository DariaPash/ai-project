import shutil
import pytest
from tools.contracts import key
from tools.store import Store
from .helpers import init
from .step04_helpers import SPEC, prepare_media, import_media


def test_actual_sparse_dense_and_audio_extraction(project):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("No local FFmpeg/ffprobe; live video processing blocked")
    prepare_media(project)
    init(project)
    sparse, se = import_media(project, "video", **SPEC["sparse"])
    dense, de = import_media(project, "video", **SPEC["dense"])
    audio, ae = import_media(project, "video", mode="audio_only")
    assert sparse["data"]["source_ref"] == dense["data"]["source_ref"] == audio["data"]["source_ref"]
    sm = se["payload"]["coverage"]["media"]
    dm = de["payload"]["coverage"]["media"]
    assert len(sm["children"]) == 4 and len(dm["children"]) == 11
    assert dm["coverage"]["observed_timestamps_ms"] == [
        5000,
        5120,
        5200,
        5280,
        5400,
        5520,
        5600,
        5680,
        5800,
        5920,
        6000,
    ]
    assert dm["children"][1]["mapping"]["requested_ms"] == 5100
    assert dm["children"][1]["mapping"]["offset_ms"] == 20
    assert not sm["coverage"]["visual_analysis_performed"] and not sm["coverage"]["full_visual_coverage"]
    assert any(5200 <= c["mapping"]["timestamp_ms"] < 5600 for c in dm["children"])
    assert not any(5200 <= c["mapping"]["timestamp_ms"] < 5600 for c in sm["children"])
    assert ae["payload"]["coverage"]["media"]["children"][0]["media_type"] == "audio/wav"
    with Store(project, "test-core") as store:
        assert store.validate()["warnings"] == []
