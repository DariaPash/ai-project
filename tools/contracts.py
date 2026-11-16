"""Structural contracts and deterministic evidence invariants, not an LLM judge."""

from functools import lru_cache
import hashlib
from importlib.resources import files
import re

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable

from .errors import CoreError
from .safeio import canonical, parse_json

PREFIX = {
    "brief": "BRF",
    "question": "QST",
    "source": "SRC",
    "artifact": "ART",
    "extraction": "EXT",
    "calculation": "CAL",
    "claim": "CLM",
    "link": "LNK",
    "option": "OPT",
    "strategy": "STR",
    "promise": "PRM",
    "experiment": "EXP",
    "decision": "DEC",
    "approval": "APR",
    "action": "ACT",
    "permission": "PER",
    "research_plan": "RPL",
    "interview_guide": "IGD",
    "interview_analysis": "INA",
    "simulation": "SIM",
    "ux_observation": "UXO",
    "ux_journey": "UXJ",
    "route_result": "RTE",
    "review": "REV",
    "obligation": "OBL",
    "memory_index": "IDX",
    "evidence_match": "EMT",
}
CLI_KINDS = (
    "brief",
    "question",
    "claim",
    "link",
    "option",
    "strategy",
    "promise",
    "experiment",
    "decision",
    "action",
    "permission",
    "research_plan",
    "interview_guide",
    "interview_analysis",
    "simulation",
    "ux_observation",
    "ux_journey",
    "review",
    "obligation",
    "evidence_match",
)
SPECIAL = {"claim", "source", "artifact", "extraction", "calculation", "approval"}
CONTROL_REFS = {"approval_ref", "request_ref", "evidence_ref", "permission_ref", "consent_ref", "option_choice_ref"}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(canonical(value))


def case_slug(value):
    if not isinstance(value, str) or re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value) is None:
        raise CoreError("UNSAFE_CASE", "Case ID must be a safe slug of at most 64 characters", 4)
    return value


@lru_cache(maxsize=1)
def schema_registry():
    schemas = {}
    registry = Registry()  # No HTTP retrieval callback: all references are packaged.
    for path in files("schemas").iterdir():
        if path.name.endswith(".schema.json"):
            value = parse_json(path.read_bytes())
            Draft202012Validator.check_schema(value)
            schemas[path.name.removesuffix(".schema.json")] = value
            registry = registry.with_resource(value["$id"], Resource.from_contents(value))
    return schemas, registry


def validate_schema(name, value, definition=None):
    schemas, registry = schema_registry()
    schema = schemas[name] if definition is None else {"$ref": schemas[name]["$id"] + "#/$defs/" + definition}
    try:
        errors = list(
            Draft202012Validator(schema, registry=registry, format_checker=FormatChecker()).iter_errors(value)
        )
    except Unresolvable as exc:
        raise CoreError("SCHEMA_REFERENCE", "Schema references must resolve locally") from exc
    if errors:
        # Do not expose instance values, including credentials or hostile text.
        location = "/".join(str(p) for p in errors[0].absolute_path)
        raise CoreError("SCHEMA_INVALID", "Schema check failed at " + (location or "root"))


def validate_payload(kind, payload):
    """One schema dispatch for journal reads and new Store writes."""
    mapping = {
        "research_plan": ("research", "research_plan"),
        "interview_guide": ("interview", "interview_guide"),
        "interview_analysis": ("interview", "interview_analysis"),
        "simulation": ("simulation", None),
    }
    if kind in {"obligation", "memory_index", "evidence_match"}:
        validate_schema(
            {"obligation": "obligation", "memory_index": "memory-index", "evidence_match": "evidence-match"}[kind],
            payload,
        )
        return
    if kind in {"route_result", "review"}:
        if kind == "route_result":
            validate_schema("route", payload, "receipt")
        else:
            validate_schema("review", payload)
        return
    if kind in {"ux_observation", "ux_journey"}:
        validate_schema("ux", payload, kind)
        return
    if "contract_version" in payload and payload["contract_version"] != 3:
        raise CoreError("CONTRACT_VERSION", "Unknown payload contract version")
    if kind in mapping:
        name, definition = mapping[kind]
    elif payload.get("contract_version") == 3 and kind in {
        "question",
        "option",
        "strategy",
        "promise",
        "experiment",
        "decision",
    }:
        name, definition = ("research", "question") if kind == "question" else ("strategy", kind)
    else:
        name, definition = (kind, None) if kind in SPECIAL else ("payloads", kind)
    validate_schema(name, payload, definition)


def ref(record):
    return {"case_id": record["case_id"], "entity_id": record["id"], "revision": record["revision"]}


def key(reference):
    return f"{reference['entity_id']}@{reference['revision']}"


def references(value, *, grounding=False):
    if isinstance(value, dict):
        if set(value) == {"case_id", "entity_id", "revision"}:
            validate_schema("common", value, "ref")
            yield value
        else:
            for name, child in value.items():
                if not grounding or name not in CONTROL_REFS:
                    yield from references(child, grounding=grounding)
    elif isinstance(value, list):
        for child in value:
            yield from references(child, grounding=grounding)


def business_digest(payload):
    return digest(
        {
            k: v
            for k, v in payload.items()
            if k not in {"status", "approved_proposal_ref", "approval_ref", "business_content_digest"}
        }
    )


def target_digest(scope, targets, records, terms=None):
    if scope in ("final_decision", "reconsideration") and len(targets) == 1:
        target = records[key(targets[0])]
        if target["kind"] == "decision":
            return business_digest(target["payload"])
    return digest(
        {
            "scope": scope,
            "targets": [{"ref": target, "record_sha256": digest(records[key(target)])} for target in targets],
            "terms": terms or {},
        }
    )


def inherited_origin(record, records, namespace):
    payload = record["payload"]
    roots = set()
    deps = (
        list(references(payload, grounding=True))
        if record["kind"] not in {"link", "approval", "permission", "action"}
        else []
    )
    for dependency in deps:
        if key(dependency) in records:
            parent = records[key(dependency)]
            if parent["kind"] not in {"approval", "permission", "action"}:
                roots.update(parent["lineage_roots"])
    if "origin" in payload:
        roots.add(payload["origin"])
    if record["kind"] == "artifact":
        order = lambda r: (int(r["id"].split("-")[1]), r["revision"])
        for other in records.values():
            if (
                other["kind"] == "artifact"
                and other["payload"]["sha256"] == payload["sha256"]
                and order(other) < order(record)
            ):
                roots.update(other["lineage_roots"])
    if record["kind"] == "simulation":
        roots.add("model_simulation")
    if not roots:
        roots.add("synthetic_fixture" if namespace == "test" else "unknown")
    return sorted(roots)


def _check_quote(item, records):
    source = records[key(item["ref"])]
    locator = item["locator"]
    if (
        source["kind"] != "source"
        or locator["source_revision"] != source["revision"]
        or locator["source_hash"] != source["payload"]["sha256"]
    ):
        raise CoreError("LOCATOR_SOURCE", "Locator does not identify the pinned source revision")
    ext_ref = {"case_id": source["case_id"], "entity_id": locator["extraction_id"], "revision": None}
    candidates = [
        r
        for r in records.values()
        if r["id"] == ext_ref["entity_id"]
        and r["kind"] == "extraction"
        and r["payload"]["source_ref"] == item["ref"]
        and r["payload"]["source_hash"] == locator["source_hash"]
    ]
    fragments = [
        fragment
        for ext in candidates
        for fragment in ext["payload"]["fragments"]
        if fragment["kind"] == locator["kind"] and fragment["coordinates"] == locator["coordinates"]
    ]
    if not fragments:
        raise CoreError("LOCATOR_MISSING", "No extracted fragment matches the exact locator")
    quote = locator.get("exact_quote")
    if quote is not None and not any(quote in fragment["text"] for fragment in fragments):
        raise CoreError("QUOTE_MISMATCH", "Quote is absent from the specified fragment")
    if "quote_hash" in locator and (quote is None or sha(quote.encode()) != locator["quote_hash"]):
        raise CoreError("QUOTE_HASH", "Quote hash does not match")


def validate_records(records, namespace, case_id, blob_reader):
    edges = {}
    for record_key, record in records.items():
        validate_schema("record", record)
        kind = record["kind"]
        if kind not in PREFIX or record_key != key(ref(record)) or record["case_id"] != case_id:
            raise CoreError("RECORD_IDENTITY", "Record identity or kind is invalid")
        if not re.fullmatch(PREFIX[kind] + r"-[0-9]{3,}", record["id"]):
            raise CoreError("RECORD_PREFIX", "Entity ID has the wrong prefix")
        payload = record["payload"]
        validate_payload(kind, payload)
        for dependency in references(payload):
            if dependency["case_id"] != case_id or key(dependency) not in records:
                raise CoreError("MISSING_REF", "Pinned reference is missing or crosses a case boundary")
        from .research_contracts import validate_research_record

        validate_research_record(record, records, namespace, blob_reader)
        if kind == "obligation":
            if payload["status"] == "completed" and not payload["completion_refs"]:
                raise CoreError("COMPLETION_EVIDENCE", "Completed obligation needs actual completion evidence")
        if kind == "evidence_match":
            if records[key(payload["source_ref"])]["kind"] != "source" or any(
                records[key(r)]["kind"] != "claim" for r in payload["claim_refs"]
            ):
                raise CoreError("MATCH_REF", "Evidence match requires exact SRC and CLM refs")
            if payload["relation"] != "unrelated" and not payload["claim_refs"]:
                raise CoreError("MATCH_REF", "Related evidence must name affected claims")
            for evidence in payload["evidence"]:
                if evidence["ref"] != payload["source_ref"]:
                    raise CoreError("MATCH_SOURCE", "Quote must come from declared new source")
                _check_quote(evidence, records)
        if kind in {"route_result", "review"}:
            from .routing import validate_record as validate_route

            validate_route(record, records, blob_reader)
        if kind in {"ux_observation", "ux_journey"} or (
            kind == "extraction" and "media" in payload.get("coverage", {})
        ):
            from .media import validate_record

            validate_record(record, records, blob_reader)
        previous = record["previous_revision"]
        if previous is not None and (previous >= record["revision"] or f"{record['id']}@{previous}" not in records):
            raise CoreError("PREVIOUS_REVISION", "Previous revision must exist and precede this record")
        for dependency in references(payload, grounding=True):
            if kind not in {"link", "approval", "permission", "action"}:
                edges.setdefault(key(dependency), set()).add(record_key)
        if record["lineage_roots"] != inherited_origin(record, records, namespace):
            raise CoreError("LINEAGE_MISMATCH", "Derived origin roots must be inherited without erasure")
        if kind == "link":
            a, b = key(payload["from_ref"]), key(payload["to_ref"])
            if payload["relation"] in ("evidence", "derivation"):
                edges.setdefault(a, set()).add(b)
            elif payload["relation"] == "supersedes":
                if (
                    a == b
                    or payload["from_ref"]["entity_id"] != payload["to_ref"]["entity_id"]
                    or payload["from_ref"]["revision"] <= payload["to_ref"]["revision"]
                ):
                    raise CoreError(
                        "SUPERSEDES_ORDER", "Supersedes must point to an earlier revision of the same entity"
                    )
        if kind == "artifact":
            if record["revision"] != 1 or record["previous_revision"] is not None:
                raise CoreError("ARTIFACT_IMMUTABLE", "An ART ID identifies one immutable content/metadata manifest")
            raw = blob_reader(payload["sha256"])
            if sha(raw) != payload["sha256"] or len(raw) != payload["size"]:
                raise CoreError("ARTIFACT_HASH", "Artifact bytes do not match the manifest", 6)
        if kind == "source":
            if sha(blob_reader(payload["sha256"])) != payload["sha256"]:
                raise CoreError("SOURCE_HASH", "Source bytes do not match the manifest", 6)
            if "artifact_ref" in payload:
                artifact = records[key(payload["artifact_ref"])]
                if artifact["kind"] != "artifact" or artifact["payload"]["sha256"] != payload["sha256"]:
                    raise CoreError("SOURCE_ARTIFACT", "Source must identify its exact raw artifact")
        if kind == "extraction":
            if record["revision"] != 1 or record["previous_revision"] is not None:
                raise CoreError(
                    "EXTRACTION_IMMUTABLE",
                    "Changed extraction gets a new EXT ID; locator IDs identify one immutable extraction",
                )
            source = records[key(payload["source_ref"])]
            if source["kind"] != "source" or source["payload"]["sha256"] != payload["source_hash"]:
                raise CoreError("EXTRACTION_SOURCE", "Extraction has a different source/hash")
            artifact = records[key(payload["artifact_ref"])]
            if (
                artifact["kind"] != "artifact"
                or blob_reader(artifact["payload"]["sha256"]).decode("utf-8") != payload["text"]
            ):
                raise CoreError("EXTRACTION_TEXT", "Extracted text must match its immutable UTF-8 artifact")
            if any(fragment["text"] not in payload["text"] for fragment in payload["fragments"]):
                raise CoreError("FRAGMENT_TEXT", "Fragment is absent from the registered extraction")
            if "tables_ref" in payload:
                table_record = records[key(payload["tables_ref"])]
                if (
                    table_record["kind"] != "artifact"
                    or table_record["payload"]["media_type"] != "application/json"
                    or payload["source_ref"] not in table_record["payload"]["parent_refs"]
                ):
                    raise CoreError(
                        "TABLE_ARTIFACT", "Tables must be an immutable JSON artifact derived from the source"
                    )
                bundle = parse_json(blob_reader(table_record["payload"]["sha256"]))
                if (
                    not isinstance(bundle, dict)
                    or bundle.get("schema_version") != 1
                    or not isinstance(bundle.get("tables"), dict)
                ):
                    raise CoreError("TABLE_SCHEMA", "Unknown table bundle schema")
                for table in bundle["tables"].values():
                    if (
                        not isinstance(table, dict)
                        or not isinstance(table.get("columns"), list)
                        or not isinstance(table.get("rows"), list)
                    ):
                        raise CoreError("TABLE_SCHEMA", "Table requires explicit columns and located rows")
                    columns = table["columns"]
                    if (
                        not 1 <= len(columns) <= 64
                        or any(not isinstance(c, str) or not c for c in columns)
                        or len(set(columns)) != len(columns)
                        or len(table["rows"]) > 2000
                    ):
                        raise CoreError("TABLE_SCHEMA", "Table dimensions/headers are invalid")
                    for row in table["rows"]:
                        if (
                            not isinstance(row, dict)
                            or not isinstance(row.get("values"), dict)
                            or set(row["values"]) != set(columns)
                            or not isinstance(row.get("coordinates"), dict)
                            or not isinstance(row.get("formula_cells"), dict)
                        ):
                            raise CoreError("TABLE_SCHEMA", "Row values/coordinates/formula metadata are invalid")
                        if not any(
                            fragment["coordinates"] == row["coordinates"]
                            and fragment["text"] == canonical(row["values"]).decode()
                            for fragment in payload["fragments"]
                        ):
                            raise CoreError("TABLE_LOCATOR", "Tabular row must match its exact extracted fragment")
        if kind == "calculation" and "spec_ref" in payload:
            for reference in [payload["spec_ref"], *payload.get("output_refs", [])]:
                if records[key(reference)]["kind"] != "artifact":
                    raise CoreError("CALCULATION_ARTIFACT", "Calculation spec/results must be immutable artifacts")
            spec_artifact = records[key(payload["spec_ref"])]
            spec = parse_json(blob_reader(spec_artifact["payload"]["sha256"]))
            validate_schema("metrics-spec", spec)
            if spec["operation"] != payload["operation"]:
                raise CoreError("CALCULATION_SPEC", "Calculation operation does not match its spec")
        if kind == "claim":
            for evidence in payload["evidence"] + payload["counterevidence"]:
                _check_quote(evidence, records)
            if payload["status"] == "supported":
                for evidence in payload["evidence"]:
                    locator = evidence["locator"]
                    for extraction in records.values():
                        if extraction["kind"] == "extraction" and extraction["id"] == locator["extraction_id"]:
                            for segment in (
                                extraction["payload"].get("coverage", {}).get("media", {}).get("segments", [])
                            ):
                                if (
                                    segment["kind"] == locator["kind"]
                                    and segment["coordinates"] == locator["coordinates"]
                                    and segment["uncertain"]
                                ):
                                    raise CoreError(
                                        "UNCERTAIN_MEDIA",
                                        "Unverified critical/low-confidence media fragment cannot support a confident fact",
                                        3,
                                    )
                if not payload["evidence"] or not payload.get("support_review"):
                    raise CoreError(
                        "SUPPORT_MISSING", "Supported claims require located evidence and an explicit review receipt"
                    )
                if payload.get("support_scope") not in {"technical_fixture", "real_world"}:
                    raise CoreError(
                        "SUPPORT_SCOPE", "Supported claims need an explicit technical_fixture/real_world scope"
                    )
                if payload.get("support_scope") == "real_world" and set(record["lineage_roots"]) & {
                    "unknown",
                    "synthetic_fixture",
                    "model_simulation",
                }:
                    raise CoreError(
                        "SYNTHETIC_AS_REAL", "Synthetic/unknown roots cannot establish real-world support", 4
                    )
        if kind == "approval":
            expected = target_digest(payload["scope"], payload["targets"], records, payload.get("terms"))
            if expected != payload["target_digest"]:
                raise CoreError("APPROVAL_DIGEST", "Approval does not match the exact pinned targets and terms")
            if payload["status"] != "requested":
                request = records[key(payload["request_ref"])]["payload"]
                if records[key(payload["request_ref"])]["kind"] != "approval":
                    raise CoreError("APPROVAL_REQUEST", "Receipt must refer to an APR request")
                for field in ("scope", "targets", "target_digest", "question", "terms"):
                    if payload.get(field) != request.get(field):
                        raise CoreError("APPROVAL_REQUEST", "Receipt changed the original request")
                if request["status"] != "requested":
                    raise CoreError("APPROVAL_REQUEST", "Receipt must refer to a request, not another receipt")
                if payload["approval_kind"] == "fixture" and namespace != "test":
                    raise CoreError("FIXTURE_APPROVAL", "Fixture approvals are restricted to test cases", 4)
                evidence = records[key(payload["evidence_ref"])]
                if evidence["kind"] != "artifact" or evidence["payload"]["size"] == 0:
                    raise CoreError("APPROVAL_EVIDENCE", "Approval needs a nonempty immutable transcript artifact")
                if payload["approval_kind"] == "real" and (
                    set(evidence["lineage_roots"]) & {"synthetic_fixture", "model_simulation", "unknown"}
                    or evidence["payload"].get("processing_kind") != "human"
                ):
                    raise CoreError(
                        "SYNTHETIC_APPROVAL",
                        "A real approval cannot be backed by synthetic/unknown or generated human evidence",
                        4,
                    )
        if kind == "permission":
            if records[key(payload["approval_ref"])]["kind"] != "approval":
                raise CoreError("PERMISSION_APPROVAL", "Permission must refer to an APR receipt", 3)
            approval = records[key(payload["approval_ref"])]["payload"]
            terms = {k: v for k, v in payload.items() if k != "approval_ref"}
            if (
                approval.get("status") != "approve"
                or approval["scope"] != payload["scope"]
                or approval.get("terms") != terms
            ):
                raise CoreError("PERMISSION_APPROVAL", "Permission limits must match the approved resource terms", 3)
            if payload["external_allowed"] and approval.get("approval_kind") != "real":
                raise CoreError("FIXTURE_EXTERNAL", "Fixture approvals never authorize real external work", 4)
        if kind == "decision":
            typed = [(payload["selected_option_ref"], "option"), (payload["experiment_ref"], "experiment")]
            typed += [(r, "option") for r in payload["rejected_refs"]]
            typed += [(r, "strategy") for r in payload["strategy_refs"]]
            if any(records[key(target)]["kind"] != expected for target, expected in typed):
                raise CoreError(
                    "DECISION_REF_KIND", "Decision references must identify options, strategies and experiment"
                )
        if kind == "decision" and payload["status"] == "confirmed":
            if not {"approved_proposal_ref", "approval_ref", "business_content_digest"}.issubset(payload):
                raise CoreError("HUMAN_REQUIRED", "Confirmed decision requires a proposal and human receipt", 3)
            if records[key(payload["approval_ref"])]["kind"] != "approval":
                raise CoreError("HUMAN_REQUIRED", "Confirmation needs an APR receipt", 3)
            proposal = records[key(payload["approved_proposal_ref"])]
            approval = records[key(payload["approval_ref"])]["payload"]
            if (
                proposal["kind"] != "decision"
                or proposal["payload"]["status"] not in ("proposed", "pending")
                or proposal["id"] != record["id"]
            ):
                raise CoreError(
                    "DECISION_PROPOSAL", "Confirmation must refer to an immutable proposal of this decision"
                )
            business = business_digest(payload)
            if (
                business != business_digest(proposal["payload"])
                or payload["business_content_digest"] != business
                or approval["target_digest"] != business
            ):
                raise CoreError("DECISION_CHANGED", "Business content changed since approval", 3)
            if (
                approval["status"] != "approve"
                or approval["scope"] not in ("final_decision", "reconsideration")
                or payload["approved_proposal_ref"] not in approval["targets"]
            ):
                raise CoreError("HUMAN_REQUIRED", "No applicable approval for this decision", 3)
    from .routing import dispatches, check_escalation, inputs

    contexts = set()
    for record, intent in dispatches(records):
        if inputs(records, intent["spec"]["input_refs"], case_id) != intent["input_digest"]:
            raise CoreError("ROUTE_BINDING", "Dispatch input digest differs from pinned records")
        check_escalation(records, intent["spec"], intent["input_digest"], ref(record))
    for record in records.values():
        if record["kind"] == "route_result":
            context = record["payload"]["context_id"]
            if context in contexts:
                raise CoreError("ROUTE_EXECUTION_REUSED", "Execution context reused for different receipts")
            contexts.add(context)
    visiting, visited = set(), set()

    def walk(node):
        if node in visiting:
            raise CoreError("EVIDENCE_CYCLE", "Evidence and derivation must form a DAG")
        if node in visited:
            return
        if len(visiting) > 400 or len(visited) > 10000:
            raise CoreError("GRAPH_LIMIT", "Graph exceeds the bounded core traversal limit", 4)
        visiting.add(node)
        for child in edges.get(node, ()):
            walk(child)
        visiting.remove(node)
        visited.add(node)

    for node in list(edges):
        walk(node)
    for record in records.values():
        if record["kind"] == "link" and record["payload"]["relation"] in ("evidence", "derivation"):
            payload = record["payload"]
            target = records[key(payload["to_ref"])]
            if payload["from_ref"] not in list(references(target["payload"], grounding=True)):
                raise CoreError(
                    "UNDECLARED_EVIDENCE", "Revise target basis refs before registering a new evidence link"
                )
