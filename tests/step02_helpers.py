import copy
import json
from pathlib import Path
import shutil

from tools.sources import ingest, parse_bytes
from tools.store import Store
from .helpers import PROJECT

SOURCES = json.loads((PROJECT / "tests/specs/02-sources.json").read_text())
CALCULATIONS = json.loads((PROJECT / "tests/specs/02-calculations.json").read_text())
ORACLE = json.loads((PROJECT / "tests/fixtures/quantitative/oracle.json").read_text())


def prepare(root):
    for folder in ("sources", "quantitative"):
        shutil.copytree(PROJECT / "tests/fixtures" / folder, root / "tests/fixtures" / folder)


def source_spec(name):
    item = next(copy.deepcopy(s) for s in SOURCES["sources"] if s["name"] == name)
    path = item.pop("file")
    item.pop("name")
    return path, {
        "schema_version": 1,
        "origin": SOURCES["origin"],
        "rights": copy.deepcopy(SOURCES["rights"]),
        "limits": copy.deepcopy(SOURCES["limits"]),
        **item,
    }


def import_source(root, name, *, sheet=None, case="test-core"):
    path, spec = source_spec(name)
    if sheet:
        spec["options"]["sheet"] = sheet
    with Store(root, case) as store:
        result = ingest(store, path, spec, store.status()["case_revision"])
    return result["data"]


def metric_spec(operation, inputs=None):
    economic = operation in {"economics", "scenarios", "sensitivity"}
    return {
        "schema_version": 1,
        "operation_version": 1,
        "operation": operation,
        "inputs": copy.deepcopy(
            inputs
            or {
                "placeholder": {
                    "source_ref": {"case_id": "test-core", "entity_id": "SRC-001", "revision": 1},
                    "extraction_ref": {"case_id": "test-core", "entity_id": "EXT-001", "revision": 1},
                    "source_sha256": "0" * 64,
                    "sheet": "csv",
                }
            }
        ),
        "fields": copy.deepcopy(CALCULATIONS["economic_fields" if economic else "cohort_fields"]),
        "definitions": copy.deepcopy(CALCULATIONS["economic_definitions" if economic else "cohort_definitions"]),
        "parameters": copy.deepcopy(CALCULATIONS["operations"][operation]),
    }


def input_refs(root, *, workbook=False):
    result = {}
    for name in ("registrations", "d7", "activations", "economics"):
        item = import_source(root, "workbook" if workbook else name, sheet=name if workbook else None)
        result[name] = {k: item[k] for k in ("source_ref", "extraction_ref", "source_sha256")}
        result[name]["sheet"] = name if workbook else "csv"
    return result


def pure_tables():
    tables = {}
    for name in ("registrations", "d7", "activations", "economics"):
        path, spec = source_spec(name)
        tables[name] = parse_bytes((PROJECT / path).read_bytes(), spec)["tables"]["csv"]
    return tables
