from tools.contracts import key
from .helpers import cli
from .step03_helpers import add_options, build_research, complete_fixture


def test_full_fixture_e2e_pause_resume(project):
    f = complete_fixture(add_options(build_research(project, via_cli=True)))
    records = f.records()
    assert len(f.options) == 4
    assert all(records[key(r)]["payload"]["execution"]["mode"] == "fixture" for r in f.simulations)
    assert records[key(f.confirmed)]["payload"]["status"] == "confirmed"
    assert {"model_simulation", "synthetic_fixture"} <= set(records[key(f.confirmed)]["lineage_roots"])
    cli(
        project,
        "checkpoint",
        "--case",
        f.case,
        "--reason",
        "Step03 fixture H only",
        "--expected-revision",
        f.status()["case_revision"],
    )
    before = f.status()
    after = cli(project, "status", "--case", f.case)[1]
    assert after["data"]["snapshot_digest"] == before["data"]["snapshot_digest"] and not after["data"]["attempts"]
    cli(project, "validate", "--case", f.case)
