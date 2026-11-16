import copy
import pytest
from tools.errors import CoreError
from .helpers import init
from .step03_helpers import Fixture
from .step04_helpers import prepare_media, import_media


def test_bbox_image_identity_and_completion_unknown(project):
    prepare_media(project)
    init(project)
    saved, extraction = import_media(project, "image")
    f = Fixture(project)
    source = f.records()[saved["data"]["source_ref"]["entity_id"] + "@1"]
    payload = {
        "contract_version": 4,
        "source_ref": saved["data"]["source_ref"],
        "artifact_ref": source["payload"]["artifact_ref"],
        "artifact_sha256": source["payload"]["sha256"],
        "width": 960,
        "height": 540,
        "orientation": "top_left_pixels",
        "bbox": [35, 350, 220, 80],
        "journey_step": "Visible step 1 only",
        "visible_observation": "NEXT rectangle and text are visible, not observed clicking behavior",
        "hypothesis": "Review effort or privacy may block later steps; not demonstrated",
        "test": "Observe an entire permitted task after consent",
        "limitations": ["Owned artificial screenshot; no user behavior was recorded"],
        "completion_status": "unknown",
    }
    observation = f.record("ux_observation", payload)
    f.record(
        "ux_journey",
        {
            "contract_version": 4,
            "steps": [{"label": "First visible step", "observation_ref": observation}],
            "unobserved_transitions": ["Button activation and final handoff were not observed"],
            "completion_status": "unknown",
            "limitations": ["Static screen only"],
        },
    )
    for field, value, code in [
        ("bbox", [900, 500, 100, 100], "UX_BBOX"),
        ("width", 999, "UX_DIMENSIONS"),
        ("completion_status", "observed", "SCHEMA_INVALID"),
    ]:
        bad = copy.deepcopy(payload)
        bad[field] = value
        with pytest.raises(CoreError) as error:
            f.record("ux_observation", bad)
        assert error.value.code == code
