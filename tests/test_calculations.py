import copy
import csv
from io import StringIO

import pytest

from tools.calculations import compute, metrics, ratio, result_csv
from tools.contracts import key
from tools.errors import CoreError
from tools.store import Store
from .helpers import init
from .step02_helpers import ORACLE, import_source, input_refs, metric_spec, prepare, pure_tables


def assert_q(result):
    oracle = ORACLE["cohorts"]
    assert result["unique_registrations"] == oracle["unique_registrations"]
    assert result["mature"] == oracle["mature"] and result["d7_active"] == oracle["d7_active"]
    assert result["retention"]["rate"] == pytest.approx(
        oracle["rate_fraction"][0] / oracle["rate_fraction"][1], abs=1e-9
    )
    assert result["retention"]["numerator"] == 7 and result["retention"]["denominator"] == 15
    quality = result["data_quality"]
    assert quality["registration_duplicates"] == oracle["duplicates_excluded"]
    assert quality["immature_excluded"] == oracle["immature_excluded"]
    assert quality["event_duplicates"]["d7"] == oracle["duplicate_d7_events"]
    assert quality["event_missing_ids"]["d7"] == oracle["missing_d7_ids"]
    for name, expected in oracle["by_cohort"].items():
        assert result["by_cohort"][name]["numerator"] == expected["numerator"]
        assert result["by_cohort"][name]["denominator"] == expected["denominator"]
        if expected["denominator"]:
            assert result["by_cohort"][name]["rate"] == pytest.approx(
                expected["numerator"] / expected["denominator"], abs=1e-9
            )
    assert result["by_cohort"]["2026-11-05"]["rate"] is None
    for name, expected in ORACLE["segments"].items():
        assert result["by_segment"][name] == {**expected, "rate": expected["numerator"] / expected["denominator"]}


@pytest.mark.parametrize("operation", ["cohorts", "segments"])
def test_frozen_cohort_and_segment_oracle(operation):
    assert_q(compute(pure_tables(), metric_spec(operation)))


def test_frozen_funnel_oracle_and_ordered_window():
    tables = pure_tables()
    spec = metric_spec("funnel")
    result = compute(tables, spec)
    expected = ORACLE["funnel"]
    for name in ("mature_registrations", "activated", "d7_after_activation"):
        assert result[name] == expected[name]
    assert result["activation"]["rate"] == pytest.approx(10 / 15, abs=1e-9)
    assert result["conditional_d7"]["rate"] == pytest.approx(7 / 10, abs=1e-9)
    spec["parameters"]["cohort"] = "2026-10-20"
    first = compute(tables, spec)
    for name, value in expected["first_cohort"].items():
        if name != "conditional_fraction":
            assert first[name] == value
    assert first["conditional_d7"]["rate"] == pytest.approx(4 / 6, abs=1e-9)
    # Activation after the explicit seven-day window must not enter the funnel.
    tables["activations"]["rows"][0]["values"]["event_at"] = "2026-11-01"
    assert compute(tables, spec)["activated"] == 5


@pytest.mark.parametrize("operation", ["economics", "scenarios", "sensitivity"])
def test_frozen_decimal_economics_oracle(operation):
    result = compute(pure_tables(), metric_spec(operation))
    base = result if operation == "economics" else result["scenarios" if operation == "scenarios" else "cases"][0]
    for name, value in ORACLE["economics"].items():
        assert base[name] == value
    if operation != "economics":
        high = result["scenarios" if operation == "scenarios" else "cases"][1]
        for name, value in ORACLE["higher_variable_cost"].items():
            assert high[name] == value


@pytest.mark.parametrize("workbook", [False, True])
def test_persisted_calculations_reproducible_manifest_csv_and_lineage(project, workbook):
    prepare(project)
    init(project)
    inputs = input_refs(project, workbook=workbook)
    if workbook:
        assert len({v["source_ref"]["entity_id"] for v in inputs.values()}) == 1
    with Store(project, "test-core") as store:
        for operation in ("cohorts", "segments", "funnel", "economics", "scenarios", "sensitivity"):
            spec = metric_spec(operation, inputs)
            first = metrics(store, spec, store.status()["case_revision"])
            again = metrics(store, spec, first["case_revision"])
            assert again["data"]["reused"] and again["data"]["calculation_ref"] == first["data"]["calculation_ref"]
            snap, _, _ = store._load()
            records = store.records(snap)
            record = records[key(first["data"]["calculation_ref"])]
            assert record["lineage_roots"] == ["synthetic_fixture"]
            assert record["payload"]["input_manifest"]["registrations"]["row_count"] == 20
            for reference in record["payload"]["output_refs"]:
                assert records[key(reference)]["lineage_roots"] == ["synthetic_fixture"]
            assert (project / "cases/test-core/calculations" / record["id"] / "output-1.csv").is_file()
            if operation == "cohorts":
                assert_q(first["data"]["result"])
        assert store.validate()["warnings"] == []


def test_zero_denominator_missing_segment_dates_and_duplicates():
    tables = pure_tables()
    spec = metric_spec("cohorts")
    assert ratio(0, 0)["rate"] is ORACLE["edge_cases"]["zero_denominator_rate"]
    # Remove exact duplicate as well when changing U01's category.
    for row in tables["registrations"]["rows"]:
        if row["values"]["user_id"] == "U01":
            row["values"]["segment"] = ""
    assert compute(tables, spec)["by_segment"]["unknown"] == {"numerator": 1, "denominator": 1, "rate": 1.0}
    tables["registrations"]["rows"][0]["values"]["signup_at"] = "01/02/26"
    with pytest.raises(CoreError) as error:
        compute(tables, spec)
    assert error.value.exit_code == 2
    tables = pure_tables()
    tables["registrations"]["rows"][-1]["values"]["segment"] = "conflict"
    with pytest.raises(CoreError) as error:
        compute(tables, spec)
    assert error.value.code == "DUPLICATE_CONFLICT"


def test_formula_cache_missing_blocks_required_numeric_result():
    tables = pure_tables()
    spec = metric_spec("economics")
    row = tables["economics"]["rows"][0]
    row["formula_cells"]["value"] = {"formula": "=1+1", "cache_missing": True, "cell": "B2"}
    row["values"]["value"] = None
    with pytest.raises(CoreError) as error:
        compute(tables, spec)
    assert error.value.exit_code == ORACLE["edge_cases"]["missing_formula_cache_exit"]


def test_actual_xlsx_formula_cell_is_not_recalculated(project):
    prepare(project)
    init(project)
    data = import_source(project, "formula")
    with Store(project, "test-core") as store:
        snapshot, _, _ = store._load()
        records = store.records(snapshot)
        ext = records[key(data["extraction_ref"])]["payload"]
        import json

        bundle = json.loads(store.blob(records[key(ext["tables_ref"])]["payload"]["sha256"]))
        row = bundle["tables"]["formula"]["rows"][0]
        assert row["values"]["value"] is None and row["formula_cells"]["value"]["cache_missing"]
        assert "formula_not_recalculated:B2" in ext["warnings"]


def test_export_formula_injection_is_escaped_without_changing_raw_values():
    values = {"=danger": '=HYPERLINK("https://example.invalid")', "safe": "ordinary", "control": "\t=1+1"}
    rows = list(csv.reader(StringIO(result_csv(values, ["synthetic_fixture"]).decode())))
    assert rows[1][0] == "'=danger" and rows[1][1].startswith("'=")
    assert rows[3][1].startswith("'\t") and values["=danger"].startswith("=")


@pytest.mark.parametrize("change", ["currency", "missing", "negative", "expression", "ambiguous_spec"])
def test_invalid_economics_not_guessed(change):
    tables = pure_tables()
    spec = metric_spec("economics")
    if change == "currency":
        tables["economics"]["rows"][0]["values"]["currency"] = "USD"
    if change == "missing":
        tables["economics"]["rows"].pop()
    if change == "negative":
        spec["parameters"]["overrides"] = {"payers": "-1"}
    if change == "expression":
        spec["parameters"]["overrides"] = {"price": "__import__('os').system('never')"}
    if change == "ambiguous_spec":
        spec["parameters"]["overrides"] = []
    with pytest.raises(CoreError) as error:
        compute(tables, spec)
    assert error.value.exit_code == 2


def test_nonpositive_margin_and_incremental_net_are_undefined():
    spec = metric_spec("economics")
    spec["parameters"]["overrides"] = {"variable_cost": "1000", "incremental_net": "0"}
    result = compute(pure_tables(), spec)
    assert result["break_even_customers"] is None and result["payback_months"] is None


def test_cached_formula_values_require_opt_in_and_warning():
    tables = pure_tables()
    spec = metric_spec("economics")
    tables["economics"]["rows"][0]["formula_cells"]["value"] = {"cell": "B2", "formula": "=100", "cache_missing": False}
    with pytest.raises(CoreError) as error:
        compute(tables, spec)
    assert error.value.exit_code == 3
    spec["definitions"]["formula_cache_policy"] = "allow_cached_with_warning"
    result = compute(tables, spec)
    assert result["net"] == "30000.00" and any("cache freshness" in s for s in result["limitations"])


def test_current_rights_override_historical_opt_in(project):
    from .helpers import add

    prepare(project)
    init(project)
    inputs = input_refs(project)
    spec = metric_spec("cohorts", inputs)
    with Store(project, "test-core") as store:
        metrics(store, spec, store.status()["case_revision"])
        snapshot, _, _ = store._load()
        records = store.records(snapshot)
        source = records[key(inputs["registrations"]["source_ref"])]
    payload = copy.deepcopy(source["payload"])
    payload["rights"]["processing"] = False
    add(project, "source", payload, entity_id=source["id"])
    spec["parameters"]["allow_historical"] = True
    with Store(project, "test-core") as store:
        with pytest.raises(CoreError) as error:
            metrics(store, spec, store.status()["case_revision"])
        assert error.value.exit_code == 3


def test_stale_ref_and_hash_rejected_even_on_repeat(project):
    prepare(project)
    init(project)
    inputs = input_refs(project)
    spec = metric_spec("cohorts", inputs)
    with Store(project, "test-core") as store:
        first = metrics(store, spec, store.status()["case_revision"])
        bad = copy.deepcopy(spec)
        bad["inputs"]["registrations"]["source_sha256"] = "0" * 64
        with pytest.raises(CoreError) as error:
            metrics(store, bad, first["case_revision"])
        assert error.value.code == "INPUT_HASH"
        path = project / "tests/fixtures/quantitative/registrations.csv"
        path.write_bytes(path.read_bytes() + b"U20,2026-11-05,small\n")
        import_source(project, "registrations")
        with pytest.raises(CoreError) as error:
            metrics(store, spec, store.status()["case_revision"])
        assert error.value.exit_code == 3
        spec["parameters"]["allow_historical"] = True
        assert_q(metrics(store, spec, store.status()["case_revision"])["data"]["result"])
