import pytest

from .helpers import make_project


@pytest.fixture
def project(tmp_path):
    return make_project(tmp_path / "project")
