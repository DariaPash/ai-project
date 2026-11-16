import subprocess
import sys
import time
import pytest
from tools.adapters.base import run
from tools.adapters.ocr import png_dimensions
from tools.errors import CoreError
from tools.media import parse
from .helpers import PROJECT
from .step04_helpers import spec


def test_dimensions_before_decode_and_protocol_denial():
    raw = (PROJECT / "tests/fixtures/media/screen.png").read_bytes()
    with pytest.raises(CoreError) as error:
        png_dimensions(raw, 1)
    assert error.value.exit_code == 4
    with pytest.raises(CoreError) as error:
        parse(b"#EXTM3U\nhttps://127.0.0.1/secret", spec("video", mode="sampled_frames", timestamps_ms=[0]))
    assert error.value.code == "VIDEO_CONTAINER"


def test_bounded_tool_output_and_timeout():
    with pytest.raises(CoreError) as error:
        run([sys.executable, "-c", 'print("x"*10000)'], time.monotonic() + 5, cap=100)
    assert error.value.exit_code == 4
    with pytest.raises(CoreError) as error:
        run([sys.executable, "-c", "import time;time.sleep(5)"], time.monotonic() + 0.1)
    assert error.value.exit_code == 5
