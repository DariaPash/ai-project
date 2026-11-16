import pytest
from tools.errors import CoreError
from tools.media import parse
from .helpers import PROJECT
from .step04_helpers import spec


def test_no_stt_auth_means_no_oracle_or_fabricated_transcript(monkeypatch, tmp_path):
    import json
    import time
    from tools.adapters import stt
    from tools.adapters.base import AdapterRequest
    from tools.contracts import sha

    raw = (PROJECT / "tests/fixtures/media/speech.wav").read_bytes()
    monkeypatch.setattr(stt, "runtime_configured", lambda: False)
    monkeypatch.setattr(stt, "executable", lambda *a: "/usr/bin/swift")
    monkeypatch.setattr(
        stt,
        "run",
        lambda *a, **k: json.dumps(
            {"status": "unavailable", "reason": "authorization not granted in controlled technical double"}
        ).encode(),
    )
    with pytest.raises(CoreError) as error:
        stt.execute(AdapterRequest(raw, sha(raw), spec("audio", language="eng"), time.monotonic() + 5), tmp_path)
    assert error.value.code == "STT_AUTH_REQUIRED" and error.value.exit_code == 3


def test_corrupt_audio_is_not_replaced_by_known_fixture_text():
    with pytest.raises(CoreError) as error:
        parse(b"not wav", spec("audio"))
    assert error.value.code == "WAV_INVALID"
