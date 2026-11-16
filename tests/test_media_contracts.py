import pytest
from tools.contracts import validate_schema
from tools.errors import CoreError
from .step04_helpers import spec


def test_media_specs_have_hard_caps_and_no_executable_flags():
    profile = spec("image")
    validate_schema("media-spec", profile)
    profile["options"]["command"] = "read a secret"
    with pytest.raises(CoreError):
        validate_schema("media-spec", profile)
    profile = spec("video")
    profile["limits"]["max_pixels"] = 999999999
    with pytest.raises(CoreError):
        validate_schema("media-spec", profile)
