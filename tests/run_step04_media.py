"""Actual processing in the accepted step03 fixture case; no visual oracle input."""

import json
from pathlib import Path
import shutil
from tools.contracts import key, sha
from tools.development import ROOT, now, write_json
from tools.errors import CoreError
from tools.store import Store
from .step03_helpers import Fixture
from .step04_helpers import prepare_media, import_media, SPEC


def main():
    p = json.loads((ROOT / "planning/progress.json").read_text())
    run = ROOT / p["active_run"]
    assert "/04/" in p["active_run"]
    target = run / "processing-receipt.json"
    assert not target.exists(), "Inspect prior processing result, never overwrite or repeat blindly"
    predecessor = json.loads((ROOT / p["steps"]["03"]["evidence"][0]).read_text())
    case = predecessor["fixture_case"]
    project = ROOT / case["project"]
    from .helpers import cli

    before = cli(project, "status", "--case", case["case_id"])[1]
    assert before["data"]["snapshot_digest"] == case["state"]["snapshot_digest"], (
        "Existing case changed; diagnose before extending it"
    )
    # Material staging is not authoritative records; original immutable history
    # stays in the same case. Observer-only key/manifest are not copied.
    prepare_media(project, case=case["case_id"])
    imported = {}
    started = now()
    for name, format_name, options in [
        ("screen", "image", {}),
        ("scan", "scan_pdf", {"pages": [1], "dpi": 72}),
        ("sparse", "video", SPEC["sparse"]),
        ("dense", "video", SPEC["dense"]),
        ("audio_track", "video", {"mode": "audio_only"}),
    ]:
        saved, extraction = import_media(project, format_name, case=case["case_id"], **options)
        imported[name] = {"result": saved, "extraction": extraction}
        media = extraction["payload"]["coverage"]["media"]
        with Store(project, case["case_id"]) as store:
            snapshot, _, _ = store._load()
            records = store.records(snapshot)
            for index, child in enumerate(media["children"]):
                if child["media_type"] == "image/png":
                    path = run / "frames" / name / f"{index:02}.png"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    raw = store.blob(child["sha256"])
                    assert not path.exists()
                    path.write_bytes(raw)
    try:
        import_media(project, "audio", case=case["case_id"], language="eng")
    except CoreError as error:
        assert error.code == "STT_AUTH_REQUIRED"
        speech = {
            "status": "blocked",
            "code": error.code,
            "reason": error.reason,
            "actual_recognition_performed": False,
        }
    else:
        speech = {"status": "processed", "actual_recognition_performed": True}
    with Store(project, case["case_id"]) as store:
        after = store.validate()
        snapshot, _, _ = store._load()
        counts = {
            "case_revision": snapshot["case_revision"],
            "committed_actions": len(snapshot["actions"]),
            "network_attempts": len(snapshot["attempts"]),
            "errors": sum(r["type"] == "ERROR" for r in store.rows),
        }
    write_json(
        target,
        {
            "actual": True,
            "started_at": started,
            "ended_at": now(),
            "project": case["project"],
            "case_id": case["case_id"],
            "before": before,
            "after": after,
            "counts_from_journal": counts,
            "imports": imported,
            "speech": speech,
            "visual_analysis_performed_by_extractor": False,
            "observer_key_in_processing_inputs": False,
            "note": "Same existing strategic fixture case, no second disconnected demo. Audio blocked receipt retained, no fake transcript.",
        },
    )
    print(
        json.dumps(
            {
                "receipt": str(target.relative_to(ROOT)),
                "counts": counts,
                "speech": speech,
                "frames": str((run / "frames").relative_to(ROOT)),
            }
        )
    )


if __name__ == "__main__":
    main()
