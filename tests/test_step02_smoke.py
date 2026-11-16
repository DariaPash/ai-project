import json

from .helpers import cli, init, revision, write_request
from .step02_helpers import SOURCES, metric_spec, prepare, source_spec


def test_incremental_cli_all_formats_metrics_claim_pause_resume(project):
    prepare(project)
    init(project)
    imported = {}
    for item in SOURCES["sources"]:
        name = item["name"]
        path, spec = source_spec(name)
        spec_path = write_request(project, spec, name="ingest-" + name + ".json")
        result = cli(
            project,
            "ingest",
            "--case",
            "test-core",
            "--path",
            path,
            "--spec",
            spec_path,
            "--expected-revision",
            revision(project),
        )[1]
        imported[name] = result["data"]
    inputs = {
        name: {**{k: imported[name][k] for k in ("source_ref", "extraction_ref", "source_sha256")}, "sheet": "csv"}
        for name in ("registrations", "d7", "activations", "economics")
    }
    for operation in ("cohorts", "segments", "funnel", "economics", "scenarios", "sensitivity"):
        spec_path = write_request(project, metric_spec(operation, inputs), name="metrics-" + operation + ".json")
        result = cli(
            project, "metrics", "--case", "test-core", "--spec", spec_path, "--expected-revision", revision(project)
        )[1]
        assert result["data"]["origin_roots"] == ["synthetic_fixture"]
        if operation == "cohorts":
            assert result["data"]["result"]["retention"]["denominator"] == 15
    search = cli(project, "search", "--case", "test-core", "--query", "Activation means")[1]
    hits = search["data"]["hits"]
    assert len(hits) >= 2 and not search["data"]["discovery_performed"]
    first = next(h for h in hits if "within 24 hours" in h["locator"]["exact_quote"])
    second = next(h for h in hits if "7 calendar days" in h["locator"]["exact_quote"])
    claim = {
        "payload": {
            "text": "Synthetic policies use incompatible activation definitions; rates must not be pooled.",
            "type": "interpretation",
            "status": "unverified",
            "origin": "synthetic_fixture",
            "evidence": [
                {"ref": first["source_ref"], "locator": first["locator"]},
                {"ref": second["source_ref"], "locator": second["locator"]},
            ],
            "counterevidence": [],
            "limitations": [
                "Technical fixture, not field evidence",
                "Common publication group is not independent corroboration",
            ],
            "basis_refs": [],
        }
    }
    request = write_request(project, claim, name="conflict.json")
    cli(
        project,
        "record",
        "--case",
        "test-core",
        "--kind",
        "claim",
        "--file",
        request,
        "--expected-revision",
        revision(project),
    )
    cli(
        project,
        "checkpoint",
        "--case",
        "test-core",
        "--reason",
        "Step02 synthetic source/calculation smoke; live fetch blocked",
        "--expected-revision",
        revision(project),
    )
    before = cli(project, "status", "--case", "test-core")[1]
    after = cli(project, "status", "--case", "test-core")[1]
    assert (
        before["case_revision"] == after["case_revision"]
        and before["data"]["snapshot_digest"] == after["data"]["snapshot_digest"]
    )
    cli(project, "validate", "--case", "test-core")
    for args, expected in [
        (("search", "--case", "test-core", "--query", "activation", "--discovery"), 3),
        (
            (
                "ingest",
                "--case",
                "test-core",
                "--path",
                "../escape",
                "--spec",
                spec_path,
                "--expected-revision",
                revision(project),
            ),
            2,
        ),
    ]:
        # The latter intentionally uses a metrics spec: schema is rejected before path access.
        cli(project, *args, expected=expected)


def test_cli_fetch_denial_and_stale_write_envelopes(project):
    init(project)
    _, spec = source_spec("html")
    fetch = {
        "schema_version": 1,
        "source_access_approval_ref": {"case_id": "test-core", "entity_id": "APR-001", "revision": 1},
        "permission_ref": {"case_id": "test-core", "entity_id": "PER-001", "revision": 1},
        "ingest": spec,
        "limits": {
            "max_bytes": 1000,
            "timeout_ms": 1000,
            "connect_timeout_ms": 500,
            "max_hops": 0,
            "allowed_mime": ["text/html"],
        },
    }
    path = write_request(project, fetch)
    result = cli(
        project,
        "fetch",
        "--case",
        "test-core",
        "--url",
        "https://example.org/",
        "--spec",
        path,
        "--expected-revision",
        0,
        expected=4,
    )[1]
    assert result["code"] == "DOMAIN_DENIED"
    for command in ("ingest", "fetch", "metrics", "search"):
        assert cli(project, command, "--help")[1]["code"] == "HELP"
