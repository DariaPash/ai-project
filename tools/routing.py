"""Small host-dispatch bridge. No model API, agent loop or IDE model switching."""

from datetime import datetime
import json

from .contracts import digest, key, ref, sha, validate_schema, references
from .errors import CoreError
from .records import RecordBatch
from .safeio import canonical, parse_json


def inputs(records, references, case_id):
    result = []
    for reference in references:
        if reference["case_id"] != case_id or key(reference) not in records:
            raise CoreError("ROUTE_REF", "Route needs existing pinned inputs in this case")
        record = records[key(reference)]
        result.append({"ref": reference, "record_sha256": digest(record)})
    return digest(result)


def permitted_inputs(snapshot, records, refs, case_id):
    """Current effective rights through bounded dependencies; never rewrite past receipts."""
    pending = list(refs)
    seen = set()
    while pending:
        reference = pending.pop()
        identity = key(reference)
        if reference["case_id"] != case_id or identity not in records:
            raise CoreError("ROUTE_REF", "Missing route dependency")
        if identity in seen:
            continue
        seen.add(identity)
        if len(seen) > 2048:
            raise CoreError("ROUTE_GRAPH_LIMIT", "Input dependency closure exceeds cap", 4)
        record = records[identity]
        latest = records[f"{record['id']}@{snapshot['active'][record['id']]}"]
        p = latest["payload"]
        if record["kind"] == "artifact":
            owners = [
                r
                for r in records.values()
                if r["kind"] == "source"
                and (
                    r["payload"].get("artifact_ref") == reference
                    or r["payload"].get("sha256") == record["payload"]["sha256"]
                )
            ]
            pending.extend(ref(owner) for owner in owners)
        if latest["kind"] == "source" and (p["status"] != "available" or not p["rights"]["processing"]):
            raise CoreError(
                "PROCESSING_DENIED", "Current source rights/status deny route, including historical/derived inputs", 4
            )
        if latest["kind"] == "claim" and p["status"] in {"retracted", "stale"}:
            raise CoreError("ROUTE_STALE", "Current claim was withdrawn or marked stale", 3)
        pending.extend(references(record["payload"], grounding=True))


def check_usage(usage):
    validate_schema("common", usage, "usage")
    money = usage["money"]
    if money["basis"] == "unknown" and money["amount"] is not None:
        raise CoreError("UNKNOWN_COST", "Unknown money remains null")
    if money["basis"] != "unknown" and (money["amount"] is None or not money["currency"]):
        raise CoreError("KNOWN_COST", "Known cost needs amount/currency")
    if (usage["tokens"] is None or usage["human_minutes"] is None or money["basis"] == "unknown") and not usage[
        "unknown_reason"
    ]:
        raise CoreError("UNKNOWN_REASON", "Missing accounting requires reason")


def dispatches(records):
    found = []
    for record in records.values():
        if record["kind"] != "action" or record["payload"].get("operation") != "note":
            continue
        note = record["payload"].get("note", "")
        try:
            value = json.loads(note)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict) and value.get("type") in {"host_dispatch_v5", "host_dispatch_v5_1"}:
            if value["type"] == "host_dispatch_v5_1":
                validate_schema("route", value, "intent")
            elif set(value) != {"type", "input_digest", "spec"}:
                raise CoreError("ROUTE_INTENT", "Malformed legacy dispatch intent")
            else:
                validate_schema("route", value["spec"], "spec")
            found.append((record, value))
    return found


def check_escalation(records, spec, fingerprint, own_intent=None):
    parent = spec.get("parent_result_ref")
    if not parent:
        return
    prior = records.get(key(parent))
    if not prior or prior["kind"] != "route_result" or prior["payload"]["status"] != "failed_quality":
        raise CoreError("ESCALATION_REQUIRED", "Escalation needs failed-quality parent")
    parent_intent = intent_payload(records, prior["payload"]["intent_ref"])
    if parent_intent["spec"].get("parent_result_ref") or parent_intent["spec"]["max_escalations"] != 1:
        raise CoreError("ESCALATION_LIMIT", "Only one approved escalation", 3)
    if parent_intent["input_digest"] != fingerprint:
        raise CoreError("ESCALATION_INPUT", "Escalation must keep pinned inputs")
    other = [
        record
        for record, value in dispatches(records)
        if value["spec"].get("parent_result_ref") == parent and (own_intent is None or ref(record) != own_intent)
    ]
    if other:
        raise CoreError("ESCALATION_LIMIT", "Parent already has a reserved/pending or completed escalation intent", 3)


def quality(output, spec):
    failures = []
    rules = spec["quality"]
    if len(canonical(output)) > spec["max_output_bytes"]:
        failures.append("output_byte_cap")
    for name in rules.get("required_fields", []):
        if name not in output:
            failures.append("missing_field:" + name)
    for name, expected in rules.get("expected_values", {}).items():
        if name not in output or canonical(output[name]) != canonical(expected):
            failures.append("value_mismatch:" + name)
    if "exact_quote" in rules and output.get("quote") != rules["exact_quote"]:
        failures.append("exact_quote_mismatch")
    if rules.get("coverage_statement_required") and not output.get("limitations"):
        failures.append("missing_coverage_limits")
    return {"passed": not failures, "failures": failures}


def plan(store, spec):
    validate_schema("route", spec, "spec")
    snapshot, _, _ = store._load()
    records = store.records(snapshot)
    fingerprint = inputs(records, spec["input_refs"], store.case_id)
    permitted_inputs(snapshot, records, spec["input_refs"], store.case_id)
    if spec["task_type"] == "deterministic":
        return {
            "case_revision": snapshot["case_revision"],
            "data": {
                "route": "deterministic_cli",
                "model_call_performed": False,
                "next_action": "Use ingest/metrics/search with explicit specs; model dispatch is unnecessary",
                "input_digest": fingerprint,
            },
        }
    check_escalation(records, spec, fingerprint)
    escalation = spec.get("parent_result_ref")
    if escalation:
        prior = records.get(key(escalation))
        if not prior or prior["kind"] != "route_result" or prior["payload"]["status"] != "failed_quality":
            raise CoreError("ESCALATION_REQUIRED", "Escalation needs a recorded failed-quality result")
        intent = intent_payload(records, prior["payload"]["intent_ref"])
        if intent["spec"].get("parent_result_ref") or intent["spec"]["max_escalations"] != 1:
            raise CoreError("ESCALATION_LIMIT", "At most one explicitly allowed escalation", 3)
        if intent["input_digest"] != fingerprint:
            raise CoreError("ESCALATION_INPUT", "Escalation must keep the same pinned input corpus")
        if any(
            r["kind"] == "route_result"
            and intent_payload(records, r["payload"]["intent_ref"])["spec"].get("parent_result_ref") == escalation
            for r in records.values()
        ):
            raise CoreError("ESCALATION_LIMIT", "This parent already has a recorded escalation", 3)
    return {
        "case_revision": snapshot["case_revision"],
        "data": {
            "route": "host_manual_bridge",
            "input_digest": fingerprint,
            "isolated_context_required": True,
            "model_identity": None,
            "model_call_performed": False,
            "limits": "One isolated host dispatch; Python cannot spawn this harness or switch the leading IDE model. No economical/strong price claim.",
            "spec": spec,
        },
    }


def intent_payload(records, reference):
    record = records.get(key(reference))
    if not record or record["kind"] != "action" or record["payload"].get("operation") != "note":
        raise CoreError("ROUTE_INTENT", "Host receipt needs the committed dispatch intent ACT")
    try:
        result = json.loads(record["payload"]["note"])
    except (KeyError, ValueError) as error:
        raise CoreError("ROUTE_INTENT", "Invalid dispatch intent") from error
    if not isinstance(result, dict):
        raise CoreError("ROUTE_INTENT", "Dispatch intent must be an object")
    if result.get("type") not in {"host_dispatch_v5", "host_dispatch_v5_1"}:
        raise CoreError("ROUTE_INTENT", "Action is not a host dispatch")
    if result.get("type") == "host_dispatch_v5_1":
        validate_schema("route", result, "intent")
    else:
        if set(result) != {"type", "input_digest", "spec"}:
            raise CoreError("ROUTE_INTENT", "Malformed legacy dispatch intent")
        validate_schema("route", result["spec"], "spec")
    return result


def prepare(store, spec, expected):
    author = spec.get("author_context_id")
    if not isinstance(author, str) or not author.startswith("ses_"):
        raise CoreError("ROUTE_AUTHOR", "New dispatch requires the actual leading host session ID in author_context_id")
    planned = plan(store, spec)
    if planned["case_revision"] != expected:
        raise CoreError("CONFLICT", "Read fresh status", 7)
    if planned["data"]["route"] == "deterministic_cli":
        return planned
    note = {
        "type": "host_dispatch_v5_1",
        "input_digest": planned["data"]["input_digest"],
        "spec": spec,
        "author_context_id": author,
    }

    def builder(snapshot):
        batch = RecordBatch(store, snapshot)
        permitted_inputs(snapshot, batch.records, spec["input_refs"], store.case_id)
        check_escalation(batch.records, spec, note["input_digest"])
        receipt = batch.add("action", {"operation": "note", "note": canonical(note).decode()})
        return batch.finish({"ref": receipt})

    saved = store._mutate("route:prepare", note, expected, builder)
    if saved["data"].get("reused"):
        snapshot, _, _ = store._load()
        records = store.records(snapshot)
        prior = next(
            (
                r
                for r in records.values()
                if r["kind"] == "route_result" and r["payload"]["intent_ref"] == saved["data"]["ref"]
            ),
            None,
        )
        return {
            **saved,
            "data": {
                **saved["data"],
                "dispatch_required": False,
                "model_call_performed": False,
                "route_ref": ref(prior) if prior else None,
                "reconcile_required": prior is None,
                "next_action": "Reuse the accepted result"
                if prior
                else "Inspect the original host execution; pending does not mean no call occurred. Do not dispatch again.",
            },
        }
    return {
        **saved,
        "data": {
            **saved["data"],
            "dispatch_required": True,
            "model_call_performed": False,
            "input_digest": note["input_digest"],
            "spec": spec,
            "next_action": "Leading host passes only this pinned bundle to a new isolated context, saves actual raw tool response, then route accept. Do not fabricate a receipt.",
        },
    }


def accept(store, request, expected):
    validate_schema("route", request, "accept")
    check_usage(request["usage"])
    if canonical(parse_json(request["raw_response"].encode())) != canonical(request["output"]):
        raise CoreError("ROUTE_RAW", "Output must equal the actual raw JSON response; no rewritten result")
    if request["context_id"] == request["author_context_id"]:
        raise CoreError("ISOLATION_REQUIRED", "A separate host context is required", 3)
    if datetime.fromisoformat(request["ended_at"]) < datetime.fromisoformat(request["started_at"]):
        raise CoreError("ROUTE_TIME", "Host execution end precedes start")

    def builder(snapshot):
        batch = RecordBatch(store, snapshot)
        intent = intent_payload(batch.records, request["intent_ref"])
        # Preserve the already-dispatched v5 bridge with its fixed leading author.
        # This compatibility path does not claim stronger historical binding.
        if request["author_context_id"] != intent.get("author_context_id", "leading-author-context"):
            raise CoreError("ROUTE_CONTEXT", "Author identity differs from committed intent")
        if intent["type"] == "host_dispatch_v5_1":
            receipt = request.get("tool_receipt")
            expected_receipt = {
                "context_id": request["context_id"],
                "author_context_id": request["author_context_id"],
                "intent_ref": request["intent_ref"],
                "input_digest": intent["input_digest"],
                "raw_response_sha256": sha(request["raw_response"].encode()),
            }
            if not isinstance(receipt, dict) or canonical(receipt) != canonical(expected_receipt):
                raise CoreError(
                    "ROUTE_TOOL_RECEIPT", "Actual host tool metadata must bind context/intent/input/raw response"
                )
        if any(
            r["kind"] == "route_result" and r["payload"]["context_id"] == request["context_id"]
            for r in batch.records.values()
        ):
            raise CoreError("ROUTE_EXECUTION_REUSED", "This isolated execution context already belongs to a receipt", 3)
        if any(
            r["kind"] == "route_result" and r["payload"]["intent_ref"] == request["intent_ref"]
            for r in batch.records.values()
        ):
            raise CoreError("ROUTE_FINISHED", "This dispatch already has a receipt; reuse it", 3)
        spec = intent["spec"]
        permitted_inputs(snapshot, batch.records, spec["input_refs"], store.case_id)
        fingerprint = inputs(batch.records, spec["input_refs"], store.case_id)
        if fingerprint != intent["input_digest"]:
            raise CoreError("ROUTE_INPUT_CHANGED", "Pinned input digest changed", 6)
        check_escalation(batch.records, spec, fingerprint, request["intent_ref"])
        raw = request["raw_response"].encode()
        out = canonical(request["output"])
        if len(raw) > 65536 or len(out) > spec["max_output_bytes"]:
            raise CoreError("ROUTE_OUTPUT_LIMIT", "Host result exceeds approved output cap", 4)
        result = quality(request["output"], spec)
        output_ref = batch.artifact(out, "application/json", "model_simulation", spec["input_refs"])
        raw_ref = batch.artifact(raw, "text/plain", "model_simulation", spec["input_refs"])
        payload = {
            name: request[name]
            for name in ("intent_ref", "context_id", "author_context_id", "model", "usage", "started_at", "ended_at")
        }
        payload.update(
            contract_version=5,
            input_refs=spec["input_refs"],
            input_digest=fingerprint,
            output_ref=output_ref,
            raw_response_ref=raw_ref,
            output_sha256=sha(out),
            quality=result,
            status="passed" if result["passed"] else "failed_quality",
        )
        if "tool_receipt" in request:
            payload["tool_receipt"] = request["tool_receipt"]
        receipt = batch.add("route_result", payload)
        return batch.finish(
            {
                "route_ref": receipt,
                "quality": result,
                "external_API_call": False,
                "accounting": "Actual host usage retained; no API/model-switch claim. Host receipt provenance is auditable, not cryptographic attestation.",
            }
        )

    return store._mutate("route:accept", request, expected, builder)


def validate_record(record, records, blob_reader):
    p = record["payload"]
    if record["kind"] == "route_result":
        check_usage(p["usage"])
        intent = intent_payload(records, p["intent_ref"])
        if intent["type"] == "host_dispatch_v5_1":
            expected = {
                "context_id": p["context_id"],
                "author_context_id": intent["author_context_id"],
                "intent_ref": p["intent_ref"],
                "input_digest": intent["input_digest"],
                "raw_response_sha256": records[key(p["raw_response_ref"])]["payload"]["sha256"],
            }
            if (
                canonical(p.get("tool_receipt")) != canonical(expected)
                or p["author_context_id"] != intent["author_context_id"]
            ):
                raise CoreError("ROUTE_TOOL_RECEIPT", "Tool context metadata differs from saved intent/response")
        spec = intent["spec"]
        if (
            p["input_refs"] != spec["input_refs"]
            or p["input_digest"] != intent["input_digest"]
            or inputs(records, p["input_refs"], record["case_id"]) != p["input_digest"]
        ):
            raise CoreError("ROUTE_BINDING", "Receipt differs from pinned dispatch")
        if p["context_id"] == p["author_context_id"]:
            raise CoreError("ISOLATION_REQUIRED", "Receipt reuses author context")
        for field in ("output_ref", "raw_response_ref"):
            artifact = records[key(p[field])]
            if artifact["kind"] != "artifact":
                raise CoreError("ROUTE_ARTIFACT", "Receipt output must be immutable ART")
        raw = blob_reader(records[key(p["output_ref"])]["payload"]["sha256"])
        response = blob_reader(records[key(p["raw_response_ref"])]["payload"]["sha256"])
        output = parse_json(raw)
        if canonical(parse_json(response)) != canonical(output):
            raise CoreError("ROUTE_RAW", "Actual response and normalized output differ")
        report = quality(output, spec)
        if (
            sha(raw) != p["output_sha256"]
            or report != p["quality"]
            or p["status"] != ("passed" if report["passed"] else "failed_quality")
        ):
            raise CoreError("ROUTE_QUALITY", "Receipt differs from actual output quality")
    elif record["kind"] == "review":
        route = records[key(p["route_ref"])]
        if route["kind"] != "route_result":
            raise CoreError("REVIEW_ROUTE", "Review needs actual isolated route receipt")
        route_payload = route["payload"]
        intent = intent_payload(records, route_payload["intent_ref"])
        if intent["spec"]["task_type"] != "independent_review":
            raise CoreError("REVIEW_CONTEXT", "Route was not an independent review dispatch")
        output = parse_json(blob_reader(records[key(route_payload["output_ref"])]["payload"]["sha256"]))
        if output != {k: v for k, v in p.items() if k not in {"contract_version", "route_ref"}}:
            raise CoreError("REVIEW_RAW", "Normalized review must equal actual route output, not rewritten findings")
        if any(r not in route_payload["input_refs"] for r in p["target_refs"]):
            raise CoreError("REVIEW_TARGET", "Reviewer targets must be in the actually dispatched bundle")
        for finding in p["findings"]:
            if finding["target_ref"] not in p["target_refs"] or any(
                r not in route_payload["input_refs"] for r in finding["evidence_refs"]
            ):
                raise CoreError("REVIEW_EVIDENCE", "Finding evidence must have been visible in the review bundle")
        if p["verdict"] == "no_blocking_findings" and any(f["severity"] in {"P1", "P2"} for f in p["findings"]):
            raise CoreError("REVIEW_VERDICT", "Blocking findings cannot be a clean verdict")
