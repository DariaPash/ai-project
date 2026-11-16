from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from tools.contracts import digest, ref, sha, target_digest
from tools.store import Store

PROJECT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT / "tests/fixtures/core"


def make_project(path):
    path.mkdir(parents=True, exist_ok=True)
    shutil.copytree(PROJECT / "config", path / "config")
    return path.resolve()


def cli(root, *args, expected=0, env=None):
    safe_env = {"PATH": os.defpath, "PYTHONPATH": str(PROJECT), "PYTHONDONTWRITEBYTECODE": "1"}
    safe_env.update(env or {})
    process = subprocess.run(
        [sys.executable, "-m", "tools.cli", *map(str, args)],
        cwd=root,
        env=safe_env,
        text=True,
        capture_output=True,
        timeout=25,
    )
    if expected is not None:
        assert process.returncode == expected, (process.returncode, process.stdout, process.stderr)
    if process.returncode == 97:
        return process, None
    value = json.loads(process.stdout)
    assert set(value) == {"ok", "code", "action_id", "attempt_id", "case_revision", "data", "warnings", "error"}
    assert value["ok"] == (process.returncode == 0)
    return process, value


def init(root, case="test-core"):
    return cli(root, "init", "--case", case, "--namespace", "test")[1]


def revision(root, case="test-core"):
    return cli(root, "status", "--case", case)[1]["case_revision"]


def write_request(root, value, case="test-core", name="request.json"):
    path = root / "cases" / case / "requests" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False))
    return str(path.relative_to(root))


def record_cli(root, kind, payload, *, case="test-core", entity_id=None, expected=0):
    request = {"payload": payload}
    if entity_id:
        request["id"] = entity_id
    path = write_request(root, request, case)
    return cli(
        root,
        "record",
        "--case",
        case,
        "--kind",
        kind,
        "--file",
        path,
        "--expected-revision",
        revision(root, case),
        expected=expected,
    )[1]


def add(root, kind, payload, *, case="test-core", entity_id=None, artifacts=None):
    with Store(root, case) as store:
        request = {"payload": payload}
        if entity_id:
            request["id"] = entity_id
        return store.record(kind, request, store.status()["case_revision"], artifacts=artifacts)["data"]["ref"]


def artifact(
    root, raw=b"Synthetic fixture, not a real human approval.", *, case="test-core", origin="synthetic_fixture"
):
    value = {"sha256": sha(raw), "size": len(raw), "media_type": "text/plain", "origin": origin, "parent_refs": []}
    return add(root, "artifact", value, case=case, artifacts={sha(raw): raw})


def source_and_extraction(root, *, case="test-core"):
    raw = b"Technical fixture.\nRetention is unknown.\n"
    a = artifact(root, raw, case=case)
    source = add(
        root,
        "source",
        {
            "title": "Technical fixture",
            "location": "fixture.txt",
            "origin": "synthetic_fixture",
            "retrieved_at": "2026-11-08T00:00:00Z",
            "published_at": "unknown",
            "sha256": sha(raw),
            "status": "available",
            "rights": {"processing": True, "external_transfer": False, "publication": False},
            "artifact_ref": a,
        },
        case=case,
    )
    extraction = add(
        root,
        "extraction",
        {
            "source_ref": source,
            "artifact_ref": a,
            "source_hash": sha(raw),
            "extractor": "test-manual-fragments-v1",
            "text": raw.decode(),
            "fragments": [{"kind": "lines", "coordinates": {"start": 2, "end": 2}, "text": "Retention is unknown."}],
            "warnings": [],
        },
        case=case,
    )
    return source, {
        "source_revision": source["revision"],
        "source_hash": sha(raw),
        "extraction_id": extraction["entity_id"],
        "kind": "lines",
        "coordinates": {"start": 2, "end": 2},
        "exact_quote": "Retention is unknown.",
    }


def approval(root, scope, *, terms=None, targets=None, case="test-core", approval_kind="fixture"):
    targets = targets or []
    evidence = artifact(root, case=case)
    with Store(root, case) as store:
        snapshot, _, _ = store._load()
        records = store.records(snapshot)
    payload = {
        "scope": scope,
        "targets": targets,
        "terms": terms or {},
        "target_digest": target_digest(scope, targets, records, terms),
        "question": "Technical approval fixture only",
        "status": "requested",
    }
    request = add(root, "approval", payload, case=case)
    return add(
        root,
        "approval",
        {
            **payload,
            "status": "approve",
            "request_ref": request,
            "approval_kind": approval_kind,
            "actor": "test_actor",
            "channel": "synthetic_fixture",
            "timestamp": "2026-11-08T00:00:00Z",
            "evidence_ref": evidence,
        },
        case=case,
    )


def permission(root, *, calls=1, money_limit=None, allow_unknown=True):
    terms = {
        "scope": "development_resource",
        "call_limit": calls,
        "external_allowed": False,
        "money_limit": money_limit,
        "allow_unknown_money": allow_unknown,
    }
    approved = approval(root, "development_resource", terms=terms)
    return add(root, "permission", {**terms, "approval_ref": approved})
