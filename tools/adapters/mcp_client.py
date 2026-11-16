"""Pinned official stdio server, read-only client and persisted actual transport receipts."""

import asyncio
import hashlib
import json
import os
from pathlib import Path

from ..contracts import digest, key, ref, sha, validate_schema
from ..errors import CoreError
from ..records import RecordBatch
from ..safeio import SafeRoot, canonical, parse_json, parts

ROOT = Path(__file__).resolve().parents[2]


def installed():
    from ..diagnostics import mcp_runtime

    try:
        return mcp_runtime(ROOT)
    except FileNotFoundError as error:
        raise CoreError(
            "MCP_UNAVAILABLE", "Run the approved pinned project-local filesystem MCP setup first", 3
        ) from error


async def transport(runtime, root, operation, name=None, arguments=None, expected_schema=None):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from jsonschema import Draft202012Validator

    parameters = StdioServerParameters(
        command="/usr/bin/sandbox-exec",
        args=[
            "-p",
            "(version 1)(allow default)(deny network*)",
            runtime["node"],
            str(ROOT / runtime["entrypoint"]),
            str(root),
        ],
        env={"PATH": str(Path(runtime["node"]).parent) + ":/usr/bin:/bin", "NODE_ENV": "production"},
        cwd=str(root),
    )
    with open(os.devnull, "w") as errors:
        async with asyncio.timeout(20):
            async with stdio_client(parameters, errlog=errors) as (read, write):
                async with ClientSession(read, write, read_timeout_seconds=10) as session:
                    init = await session.initialize()
                    catalog = await session.list_tools()
                    if len(catalog.tools) > 128 or catalog.next_cursor:
                        raise CoreError("MCP_TOOL_LIMIT", "Unexpected oversized/paginated filesystem tool catalog", 4)
                    tools = {t.name: t.input_schema for t in catalog.tools}
                    if len(tools) != len(catalog.tools):
                        raise CoreError("MCP_TOOL_SCHEMA", "Duplicate tool names", 4)
                    report = {
                        "initialize": init.model_dump(mode="json", by_alias=True),
                        "tools": tools,
                        "schema_digest": digest(tools),
                        "network_used": False,
                    }
                    if operation == "call":
                        if report["schema_digest"] != expected_schema:
                            raise CoreError(
                                "MCP_TOOL_SCHEMA", "Live tool schema differs from pinned probe; no tool called", 4
                            )
                        if name not in {"read_text_file", "read_file"} or name not in tools:
                            raise CoreError(
                                "MCP_TOOL_DENIED", "Only an actually advertised full-text read tool may be called", 4
                            )
                        # The configured official schema is data, never authority to add tools.
                        if "$ref" in json.dumps(tools[name]):
                            raise CoreError("MCP_TOOL_SCHEMA", "External schema resolution is forbidden", 4)
                        Draft202012Validator(tools[name]).validate(arguments)
                        result = await session.call_tool(name, arguments)
                        report["result"] = result.model_dump(mode="json", by_alias=True)
                    return report


def notes(records, kind, fingerprint=None):
    found = []
    for record in records.values():
        if record["kind"] != "action" or record["payload"].get("operation") != "note":
            continue
        try:
            value = json.loads(record["payload"].get("note", ""))
        except ValueError:
            continue
        if (
            isinstance(value, dict)
            and value.get("type") == kind
            and (fingerprint is None or value.get("fingerprint") == fingerprint)
        ):
            found.append((record, value))
    return found


def verified_probe(store, records, reference, allowed_root, runtime):
    try:
        record = records[key(reference)]
        if record["kind"] != "action" or record["payload"]["operation"] != "note":
            raise ValueError("not an action note")
        note = json.loads(record["payload"]["note"])
        if note["type"] != "mcp_result_v1" or note["operation"] != "probe" or note["root"] != allowed_root:
            raise ValueError("not a matching probe")
        if note["runtime_digest"] != digest(runtime):
            raise ValueError("different runtime")
        if any(note[field].get("case_id") != store.case_id for field in ("artifact_ref", "intent_ref")):
            raise ValueError("cross-case probe dependency")
        artifact = records[key(note["artifact_ref"])]
        intent = records[key(note["intent_ref"])]
        if artifact["kind"] != "artifact" or intent["kind"] != "action" or intent["payload"]["operation"] != "note":
            raise ValueError("incorrect dependency kind")
        if note["intent_ref"] not in artifact["payload"]["parent_refs"]:
            raise ValueError("probe artifact not bound to intent")
        dispatch = json.loads(intent["payload"]["note"])
        if any(
            dispatch.get(k) != v
            for k, v in {
                "type": "mcp_intent_v1",
                "operation": "probe",
                "root": allowed_root,
                "runtime_digest": digest(runtime),
                "fingerprint": note["fingerprint"],
            }.items()
        ):
            raise ValueError("probe intent mismatch")
        report = parse_json(store.blob(artifact["payload"]["sha256"]))
        if len(canonical(report)) > 262144 or not report.get("initialize"):
            raise ValueError("missing transport initialization")
        if digest(report["tools"]) != report["schema_digest"] or report["schema_digest"] != note["schema_digest"]:
            raise ValueError("probe catalog digest mismatch")
        reads = [name for name in ("read_text_file", "read_file") if name in report["tools"]]
        if reads != note["available_read_tools"]:
            raise ValueError("probe read catalog mismatch")
        return note
    except (KeyError, ValueError, TypeError, AttributeError):
        raise CoreError("MCP_PROBE", "Probe must bind a valid persisted transport artifact, catalog digest and intent")


def execute(store, request, expected, operation):
    validate_schema("mcp-request", request, operation)
    status = store.status()
    if status["case_revision"] != expected:
        raise CoreError("CONFLICT", "Read fresh status before MCP execution", 7)
    runtime = installed()
    allowed_root = store.base + "/input/mcp-materials"
    if request["root"] != allowed_root:
        raise CoreError("MCP_ROOT_DENIED", "MCP root must be this case input/mcp-materials directory, never HOME", 4)
    with store.io.directory(parts(allowed_root)):
        pass
    root = store.io.path / allowed_root
    snapshot, _, _ = store._load()
    records = store.records(snapshot)
    raw = None
    location = None
    previous_probe = None
    if operation == "call":
        if request["probe_ref"]["case_id"] != store.case_id:
            raise CoreError("MCP_PROBE", "Probe must belong to this case")
        previous_probe = verified_probe(store, records, request["probe_ref"], allowed_root, runtime)
        relative_parts = parts(request["path"])
        location = allowed_root + "/" + "/".join(relative_parts)
        if (
            request["ingest"]["format"] not in {"txt", "md"}
            or request["ingest"]["options"].get("encoding", "utf-8") != "utf-8"
        ):
            raise CoreError("MCP_FORMAT", "This bounded read bridge imports UTF-8 TXT/MD only")
        if not request["ingest"]["rights"]["processing"]:
            raise CoreError("PROCESSING_DENIED", "Input processing permission required", 4)
        raw = store.io.read(location, min(65536, request["ingest"]["limits"]["max_bytes"]))
        if len(raw.decode("utf-8")) > 65536:
            raise CoreError("MCP_OUTPUT_LIMIT", "Text exceeds local read cap", 4)
    fingerprint = digest(
        {
            "request": request,
            "runtime": runtime,
            "implementation_sha256": sha(Path(__file__).read_bytes()),
            "input_sha256": sha(raw) if raw is not None else None,
        }
    )
    external_identity = digest(
        {
            "operation": operation,
            "root": allowed_root,
            "runtime_digest": digest(runtime),
            "path": location,
            "input_sha256": sha(raw) if raw is not None else None,
            "read_semantics": "full_utf8_text" if operation == "call" else None,
            "schema_digest": previous_probe["schema_digest"] if previous_probe else None,
        }
    )
    # Stable external identity excludes implementation, titles, ingest settings,
    # probe record identity and tool aliases: metadata cannot authorize a repeat.
    for record, saved in notes(records, "mcp_result_v1"):
        if saved.get("external_identity") == external_identity:
            return {
                "case_revision": snapshot["case_revision"],
                "data": {
                    **saved,
                    "receipt_ref": ref(record),
                    "reused": True,
                    "new_server_call": False,
                    "requested_metadata_not_applied": saved["fingerprint"] != fingerprint,
                },
            }
    for _, pending in notes(records, "mcp_intent_v1"):
        if pending.get("external_identity") == external_identity:
            raise CoreError(
                "MCP_RECONCILE_REQUIRED",
                "Pending/unknown operation identity cannot be bypassed by metadata or code changes",
                3,
            )
        if "external_identity" not in pending:
            same_legacy = all(
                pending.get(k) == v
                for k, v in {
                    "operation": operation,
                    "root": allowed_root,
                    "runtime_digest": digest(runtime),
                    "input_sha256": sha(raw) if raw is not None else None,
                }.items()
            )
            completed = notes(records, "mcp_result_v1", pending.get("fingerprint"))
            if same_legacy and not completed:
                raise CoreError(
                    "MCP_RECONCILE_REQUIRED",
                    "Unfinished legacy read intent must be reconciled; code/metadata changes do not clear it",
                    3,
                )
    done = notes(records, "mcp_result_v1", fingerprint)
    if done:
        record, saved = done[-1]
        return {
            "case_revision": snapshot["case_revision"],
            "data": {**saved, "receipt_ref": ref(record), "reused": True, "new_server_call": False},
        }
    if notes(records, "mcp_intent_v1", fingerprint):
        raise CoreError(
            "MCP_RECONCILE_REQUIRED",
            "Pending/unknown read intent exists; inspect saved execution instead of blind repeat",
            3,
        )
    intent = store.record(
        "action",
        {
            "payload": {
                "operation": "note",
                "note": canonical(
                    {
                        "type": "mcp_intent_v1",
                        "operation": operation,
                        "fingerprint": fingerprint,
                        "external_identity": external_identity,
                        "root": allowed_root,
                        "runtime_digest": digest(runtime),
                        "input_sha256": sha(raw) if raw is not None else None,
                    }
                ).decode(),
            }
        },
        expected,
    )
    try:
        result = asyncio.run(
            transport(
                runtime,
                root,
                operation,
                request.get("tool"),
                {"path": str(store.io.path / location)} if location else None,
                previous_probe["schema_digest"] if previous_probe else None,
            )
        )
        encoded = canonical(result)
        if len(encoded) > 262144:
            raise CoreError("MCP_OUTPUT_LIMIT", "MCP response exceeds persisted receipt cap", 4)
        if previous_probe and result["schema_digest"] != previous_probe["schema_digest"]:
            raise CoreError("MCP_TOOL_SCHEMA", "Live tool schema differs from pinned probe", 4)
        if operation == "call":
            reply = result["result"]
            if reply.get("isError") or any(c.get("type") != "text" for c in reply.get("content", [])):
                raise CoreError("MCP_READ_FAILED", "Read returned an error or non-text content", 5)
            actual = "".join(c["text"] for c in reply.get("content", []))
            if actual != raw.decode("utf-8") or store.io.read(location, 65536) != raw:
                raise CoreError(
                    "MCP_CONTENT_CHANGED", "MCP bytes differ from descriptor-safe input snapshot; not imported", 7
                )

        def builder(current):
            batch = RecordBatch(store, current)
            source_data = {}
            if operation == "call":
                from ..sources import parse_snapshot, stage_source

                source_data = stage_source(
                    batch, raw, parse_snapshot(raw, request["ingest"]), request["ingest"], location
                )
            artifact = batch.artifact(
                encoded,
                "application/json",
                request["ingest"]["origin"] if operation == "call" else "owner_observation",
                [intent["data"]["ref"]] + ([source_data["source_ref"]] if source_data else []),
            )
            saved = {
                "type": "mcp_result_v1",
                "operation": operation,
                "fingerprint": fingerprint,
                "external_identity": external_identity,
                "root": allowed_root,
                "runtime_digest": digest(runtime),
                "schema_digest": result["schema_digest"],
                "artifact_ref": artifact,
                "intent_ref": intent["data"]["ref"],
                "network_used": False,
                "available_read_tools": [name for name in ("read_text_file", "read_file") if name in result["tools"]],
            }
            if operation == "call":
                saved.update(source_data)
            receipt = batch.add("action", {"operation": "note", "note": canonical(saved).decode()})
            return batch.finish({**saved, "receipt_ref": receipt, "reused": False, "new_server_call": True})

        return store._mutate(
            "mcp:" + operation + ":result", {"fingerprint": fingerprint}, intent["case_revision"], builder
        )
    except Exception as error:
        core = (
            error
            if isinstance(error, CoreError)
            else CoreError(
                "MCP_TRANSPORT_FAILED", "Bounded filesystem MCP failed; intent retained, no retry or fake result", 5
            )
        )

        def categories(exc):
            return [type(exc).__name__] + [
                name for child in getattr(exc, "exceptions", ()) for name in categories(child)
            ]

        store.record(
            "action",
            {
                "payload": {
                    "operation": "note",
                    "note": canonical(
                        {
                            "type": "mcp_failure_v1",
                            "intent_ref": intent["data"]["ref"],
                            "fingerprint": fingerprint,
                            "error_categories": categories(error),
                            "code": core.code,
                            "remote_outcome": "unknown_read_only",
                            "next_action": "Inspect installed SDK/runtime before any new implementation attempt",
                        }
                    ).decode(),
                }
            },
            store.status()["case_revision"],
        )
        store.note_failure("mcp:" + operation, fingerprint, core, store.status()["case_revision"])
        raise core from error


def unavailable(store, request, expected, operation):
    # Compatibility entry point for old imports; the CLI uses execute below.
    if not isinstance(request, dict):
        raise CoreError("MCP_REQUEST", "MCP request must be an object")
    tool = request.get("tool", "")
    if operation == "call" and tool not in {"read_text_file", "read_file"}:
        error = CoreError(
            "MCP_TOOL_DENIED", "No advertised/verified read tool; write/delete and arbitrary tools are denied", 4
        )
    else:
        error = CoreError(
            "MCP_UNAVAILABLE",
            "Official filesystem MCP server and Python SDK not installed/approved. No server started. Use ordinary ingest for the same permitted local file; this is CLI fallback, not live MCP.",
            3,
        )
    store.note_failure("mcp:" + operation, digest(request), error, expected)
    raise error
