import json
import shutil
from tools.sources import ingest
from tools.store import Store
from tools.contracts import key
from .helpers import PROJECT

SPEC = json.loads((PROJECT / "tests/specs/04-media.json").read_text())


def prepare_media(root, case=None):
    shutil.copytree(
        PROJECT / "tests/fixtures/media",
        root / (f"cases/{case}/input/media" if case else "tests/fixtures/media"),
        ignore=shutil.ignore_patterns("oracle.json", "manifest.json"),
    )


def spec(format_name, **options):
    return {
        "schema_version": 1,
        "format": format_name,
        "title": "Owned synthetic media " + format_name,
        "origin": SPEC["origin"],
        "rights": dict(SPEC["rights"]),
        "options": options,
        "limits": dict(SPEC["limits"]),
    }


def import_media(root, format_name, case="test-core", **options):
    profile = spec(format_name, **options)
    with Store(root, case) as store:
        prefix = (
            f"cases/{case}/input/media/" if (root / f"cases/{case}/input/media").is_dir() else "tests/fixtures/media/"
        )
        saved = ingest(store, prefix + SPEC["inputs"][format_name], profile, store.status()["case_revision"])
        snapshot, _, _ = store._load()
        extraction = store.records(snapshot)[key(saved["data"]["extraction_ref"])]
    return saved, extraction
