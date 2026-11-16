from tools.contracts import key
from tools.store import Store
from .step03_helpers import build_research, add_options, complete_fixture
from .step04_helpers import prepare_media, import_media, SPEC
from .step04_update import update


def test_full_story_media_changes_both_strategies_and_new_exact_approval(project):
    f = complete_fixture(add_options(build_research(project)))
    old = f.records()
    old_product = old[key(f.product)]["payload"]["text"]
    old_comm = old[key(f.communication)]["payload"]["text"]
    prepare_media(project)
    image, extraction = import_media(project, "image")
    dense, de = import_media(project, "video", **SPEC["dense"])
    source = f.records()[key(image["data"]["source_ref"])]
    ux = f.record(
        "ux_observation",
        {
            "contract_version": 4,
            "source_ref": image["data"]["source_ref"],
            "artifact_ref": source["payload"]["artifact_ref"],
            "artifact_sha256": source["payload"]["sha256"],
            "width": 960,
            "height": 540,
            "orientation": "top_left_pixels",
            "bbox": [35, 350, 220, 80],
            "journey_step": "First static step only",
            "visible_observation": "Rectangle labelled NEXT is present; no click was observed",
            "hypothesis": "Review effort may matter; actual completion unknown",
            "test": "Observe full permitted task after consent",
            "limitations": ["Owned artificial image, not actual behavior"],
            "completion_status": "unknown",
        },
    )
    journey = f.record(
        "ux_journey",
        {
            "contract_version": 4,
            "steps": [{"label": "Step1", "observation_ref": ux}],
            "unobserved_transitions": ["Click and final handoff not observed"],
            "completion_status": "unknown",
            "limitations": ["Static image/sampled video only"],
        },
    )
    revised = update(f, [image["data"]["source_ref"], dense["data"]["source_ref"]], ux, journey)
    records = f.records()
    assert revised["strategy_refs"][0]["revision"] == revised["strategy_refs"][1]["revision"] == 2
    assert records[key(revised["strategy_refs"][0])]["payload"]["text"] != old_product
    assert records[key(revised["strategy_refs"][1])]["payload"]["text"] != old_comm
    assert (
        revised["decision_ref"]["revision"] == 3
        and records[key(revised["decision_ref"])]["payload"]["status"] == "pending"
    )
    assert records[key(f.confirmed)]["payload"]["status"] == "confirmed"  # immutable old H/history retained
    with Store(project, f.case) as store:
        store.checkpoint("Media step full story saved, real H not inferred", store.status()["case_revision"])
        assert store.validate()["warnings"] == []
