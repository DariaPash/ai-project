"""Scoped local-format diagnostics; never installs, authorizes Speech or uploads."""

from .contracts import key, ref, digest
from .errors import CoreError
from .records import RecordBatch
from .safeio import canonical
from datetime import datetime, timezone


def _authorize(snapshot, records, approval_id):
    revision = snapshot["active"].get(approval_id)
    approval = records.get(f"{approval_id}@{revision}")
    if (
        not approval
        or approval["kind"] != "approval"
        or approval["payload"]["status"] != "approve"
        or approval["payload"]["scope"] not in {"development_resource", "source_access"}
    ):
        raise CoreError("APPROVAL_REQUIRED", "Format probe requires a current scoped approved APR", 3)
    payload = approval["payload"]
    if payload.get("approval_kind") == "fixture" and snapshot["namespace"] != "test":
        raise CoreError("FIXTURE_APPROVAL", "Fixture probe approval is test-only", 4)
    terms = payload.get("terms", {})
    engines = terms.get("engines")
    sources = terms.get("source_refs")
    try:
        expiry = datetime.fromisoformat(terms.get("expires_at", "").replace("Z", "+00:00"))
        valid_expiry = expiry.tzinfo is not None and expiry > datetime.now(timezone.utc)
    except (TypeError, ValueError):
        valid_expiry = False
    if (
        terms.get("operation") != "doctor:formats"
        or terms.get("processing") is not True
        or not valid_expiry
        or not isinstance(engines, list)
        or not engines
        or any(name not in {"tesseract", "pdftoppm", "ffmpeg", "ffprobe", "swift"} for name in engines)
        or not isinstance(sources, list)
    ):
        raise CoreError(
            "APPROVAL_REQUIRED",
            "Probe APR needs exact operation, engines, source_refs, processing=true and future timezone expiry",
            3,
        )
    try:
        if any(
            key(r) not in records or records[key(r)]["kind"] != "source" or r not in payload["targets"] for r in sources
        ):
            raise ValueError("Unapproved source")
    except (TypeError, KeyError, ValueError):
        raise CoreError("APPROVAL_REQUIRED", "Probe sources must be pinned SRC targets of this APR", 3)
    return terms


def run(store, approval_id, expected):
    from .adapters.base import probe

    # Reuse only the same engine/config and corpus, not every call with this APR.
    status = store.status()
    if status["case_revision"] != expected:
        raise CoreError("CONFLICT", "Read a fresh case revision before probing", 7)
    snapshot, _, _ = store._load()
    records = store.records(snapshot)
    terms = _authorize(snapshot, records, approval_id)
    report = probe({"engines": terms["engines"]}, live=False)
    corpus = [ref(r) for r in records.values() if r["kind"] in {"source", "extraction"}]
    fingerprint = digest({"report": report, "corpus": corpus})

    def builder(snapshot):
        records = store.records(snapshot)
        _authorize(snapshot, records, approval_id)
        local_report = dict(report)
        media = {}
        for record in records.values():
            if record["kind"] != "extraction" or "media" not in record["payload"].get("coverage", {}):
                continue
            source = records[key(record["payload"]["source_ref"])]
            if ref(source) not in terms["source_refs"]:
                continue
            if (
                snapshot["active"].get(source["id"]) != source["revision"]
                or source["payload"]["status"] != "available"
                or not source["payload"]["rights"]["processing"]
            ):
                continue
            result = record["payload"]["coverage"]["media"]
            media.setdefault(result["format"], []).append(
                {
                    "extraction_ref": ref(record),
                    "source_ref": ref(source),
                    "status": result["status"],
                    "origin_roots": record["lineage_roots"],
                }
            )
        local_report.update(
            case_processing_receipts=media,
            processing_executed_by_probe=False,
            speech_authorization_requested=False,
            external_calls=False,
            limitations="Engine version/probe plus saved local processing receipts, not all-format live acceptance or fieldwork",
        )
        batch = RecordBatch(store, snapshot)
        receipt = batch.artifact(
            canonical(local_report),
            "application/json",
            "synthetic_fixture" if snapshot["namespace"] == "test" else "unknown",
            [],
        )
        return batch.finish({"capability_report_ref": receipt, "formats": local_report})

    return store._mutate(
        "doctor:formats",
        {"approval_id": approval_id, "approval_ref": snapshot["active"].get(approval_id), "fingerprint": fingerprint},
        expected,
        builder,
    )
