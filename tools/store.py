"""Small local commit journal. Immutable snapshots are accepted only by COMMIT.

ALLOCATE rows make exposed numeric IDs monotonic even across aborted writes.
JSON/Markdown projections are disposable, but unknown/corrupt state is never
silently reset. This is not a distributed database or a network-FS lock service.
"""

import copy
from datetime import datetime, timezone
import os
import re
import time
import uuid

from .contracts import (
    PREFIX,
    business_digest,
    case_slug,
    digest,
    inherited_origin,
    key,
    ref,
    references,
    sha,
    target_digest,
    validate_records,
    validate_schema,
    validate_payload,
)
from .errors import CoreError
from .safeio import SafeRoot, canonical, parse_json, parts


def now():
    return datetime.now(timezone.utc).isoformat()


def unknown_usage(duration_ms=None):
    return {
        "duration_ms": duration_ms,
        "model": None,
        "tokens": None,
        "money": {"amount": None, "currency": None, "basis": "unknown"},
        "human_minutes": None,
        "unknown_reason": "Host billing/tokens and human time are not exposed; local helper timing only",
    }


def lifecycle_stage(snapshot, records):
    """Progress for a NEW commit only, never a reinterpretation of old snapshots.

    Stages describe work/proposals, not human approval or business success.
    awaiting_human remains independent, including resource blockers.
    """
    active = [records[f"{entity}@{rev}"] for entity, rev in snapshot["active"].items()]
    kinds = {record["kind"] for record in active}
    decisions = [r for r in active if r["kind"] == "decision"]
    pending = snapshot["runtime"].get("awaiting_human")
    if pending in {"reconsideration", "final_decision", "option_choice"}:
        return {"reconsideration": "reconsideration", "final_decision": "decision", "option_choice": "options"}[pending]
    if pending == "reconsideration" or any(
        r["payload"].get("status") in {"review_required", "basis_invalid", "needs_revalidation"}
        or (
            r["payload"].get("status") in {"pending", "proposed"}
            and any(
                old.get("id") == r.get("id")
                and old["revision"] < r["revision"]
                and old["payload"].get("status") in {"confirmed", "review_required"}
                for old in records.values()
                if old["kind"] == "decision"
            )
        )
        for r in decisions
    ):
        return "reconsideration"
    if pending == "final_decision" or any(r["payload"].get("status") == "pending" for r in decisions):
        return "decision"
    if decisions:
        return "follow_up" if any(r["payload"].get("status") == "confirmed" for r in decisions) else "decision"
    if kinds & {"strategy", "promise", "experiment"}:
        return "strategy"
    if pending == "option_choice" or "option" in kinds:
        return "options"
    if kinds & {"interview_analysis", "simulation", "claim", "calculation"}:
        return "research"
    if "research_plan" in kinds:
        return "research_plan"
    if snapshot["runtime"].get("stage") == "brief_clarification":
        return "brief_clarification"  # Explicit core action contract, before semantic work.
    return "brief"


class Store:
    def __init__(self, project, case_id):
        self.case_id = case_slug(case_id)
        self.io = SafeRoot(project)
        self.base = "cases/" + self.case_id
        self.events = self.base + "/events.jsonl"
        self.lock_path = "cases/.locks/" + self.case_id + ".lock"
        self.rows = []
        self.counters = {}
        self.namespace = None

    def close(self):
        self.io.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def blob(self, content_hash):
        if re.fullmatch(r"[a-f0-9]{64}", content_hash) is None:
            raise CoreError("INVALID_HASH", "Invalid artifact hash")
        return self.io.read(self.base + "/artifacts/sha256/" + content_hash)

    def _append(self, body):
        row = {
            "schema_version": 1,
            "seq": len(self.rows) + 1,
            "previous_hash": self.rows[-1]["sha256"] if self.rows else None,
            "at": now(),
            **body,
        }
        row["sha256"] = digest(row)
        self.io.append(self.events, canonical(row) + b"\n")
        self.rows.append(row)

    def _allocate(self, prefix):
        value = self.counters.get(prefix, 0) + 1
        self._append({"type": "ALLOCATE", "prefix": prefix, "value": value})
        self.counters[prefix] = value
        return f"{prefix}-{value:03}"

    def _load(self, *, allow_tail=False, check_projection=True):
        self.rows, self.counters = [], {}
        try:
            raw = self.io.read(self.events, 64 * 1024 * 1024)
        except FileNotFoundError as exc:
            raise CoreError(
                "STORE_INCOMPLETE",
                "Case has no committed journal",
                6,
                next_action="Inspect the incomplete case; do not reinitialize it",
            ) from exc
        tail = b""
        if raw and not raw.endswith(b"\n"):
            split = raw.rfind(b"\n") + 1
            raw, tail = raw[:split], raw[split:]
            if not allow_tail:
                raise CoreError(
                    "JOURNAL_TAIL",
                    "Journal has an unfinished final line",
                    6,
                    next_action="Run recover read-only, then explicitly repair the saved tail",
                )
        snapshot, previous_prepare, last_commit = None, None, None
        previous_revision = -1
        try:
            for line in raw.splitlines():
                row = parse_json(line)
                if not isinstance(row, dict) or row.get("schema_version") != 1:
                    raise CoreError("STORE_SCHEMA", "Unknown journal version", 6)
                if (
                    row.get("seq") != len(self.rows) + 1
                    or row.get("previous_hash") != (self.rows[-1]["sha256"] if self.rows else None)
                    or row.get("sha256") != digest({k: v for k, v in row.items() if k != "sha256"})
                ):
                    raise CoreError("JOURNAL_HASH", "Journal sequence or hash chain is damaged", 6)
                kind = row.get("type")
                if kind == "ALLOCATE":
                    prefix, value = row.get("prefix"), row.get("value")
                    if (
                        prefix not in PREFIX.values()
                        or type(value) is not int
                        or value != self.counters.get(prefix, 0) + 1
                    ):
                        raise CoreError("ALLOCATION_CORRUPT", "ID allocation sequence is invalid", 6)
                    self.counters[prefix] = value
                elif kind == "PREPARE":
                    if row.get("previous_commit") != last_commit or not isinstance(row.get("files"), dict):
                        raise CoreError("PREPARE_CORRUPT", "Prepare does not follow the committed chain", 6)
                    previous_prepare = row
                elif kind == "COMMIT":
                    if (
                        not previous_prepare
                        or row.get("tx_id") != previous_prepare.get("tx_id")
                        or row.get("prepare_hash") != previous_prepare["sha256"]
                    ):
                        raise CoreError("COMMIT_CORRUPT", "Commit does not match its prepare", 6)
                    for path, expected_hash in previous_prepare["files"].items():
                        if not path.startswith(self.base + "/") or sha(self.io.read(path)) != expected_hash:
                            raise CoreError("COMMITTED_HASH", "Committed file is missing or altered", 6)
                    path = previous_prepare["snapshot_path"]
                    if path not in previous_prepare["files"]:
                        raise CoreError("SNAPSHOT_MANIFEST", "Snapshot is absent from the committed manifest", 6)
                    candidate = self.io.json(path)
                    if candidate.get("schema_version") != 1:
                        raise CoreError("STORE_SCHEMA", "Unknown snapshot schema version", 6)
                    validate_schema("snapshot", candidate)
                    if candidate["case_id"] != self.case_id or candidate["case_revision"] != previous_revision + 1:
                        raise CoreError("SNAPSHOT_IDENTITY", "Snapshot identity or revision sequence is invalid", 6)
                    if snapshot is not None:
                        if candidate["namespace"] != snapshot["namespace"] or any(
                            candidate["records"].get(k) != v for k, v in snapshot["records"].items()
                        ):
                            raise CoreError("HISTORY_CHANGED", "Committed history or namespace was removed/changed", 6)
                    snapshot = candidate
                    previous_revision = candidate["case_revision"]
                    last_commit = row["sha256"]
                    previous_prepare = None
                elif kind != "ERROR":
                    raise CoreError("JOURNAL_EVENT", "Unknown event type", 6)
                self.rows.append(row)
            if snapshot is None:
                raise CoreError("NO_COMMIT", "Case has no durable commit", 6)
            self.namespace = snapshot["namespace"]
            records = self.records(snapshot)
            validate_records(records, self.namespace, self.case_id, self.blob)
            for record in records.values():
                if record["action_id"] not in snapshot["actions"]:
                    raise CoreError("ACTION_MISSING", "Record has no committed action receipt", 6)
            self._validate_ledger(snapshot)
            warnings = self._projection_warnings(snapshot) if check_projection else []
        except (FileNotFoundError, KeyError, TypeError, UnicodeError, ValueError) as exc:
            raise CoreError("STORE_CORRUPT", "Committed journal, snapshot or content is malformed/missing", 6) from exc
        except CoreError as exc:
            if exc.exit_code == 2:
                raise CoreError("STORE_CORRUPT", "Committed content violates its schema/invariants", 6) from exc
            raise
        return snapshot, warnings, tail

    def records(self, snapshot):
        result = {}
        for record_key, manifest in snapshot["records"].items():
            path = manifest["path"]
            if not path.startswith(self.base + "/records/"):
                raise CoreError("RECORD_PATH", "Record path is outside the case records", 6)
            raw = self.io.read(path)
            if sha(raw) != manifest["sha256"]:
                raise CoreError("RECORD_HASH", "Immutable record was modified", 6)
            result[record_key] = parse_json(raw)
        return result

    def _projection_bytes(self, snapshot):
        records = self.records(snapshot)
        active = [records[f"{entity}@{rev}"] for entity, rev in snapshot["active"].items()]
        state = {
            "schema_version": 1,
            "case_id": self.case_id,
            "case_revision": snapshot["case_revision"],
            "snapshot_digest": digest(snapshot),
            "updated_at": snapshot["updated_at"],
            **snapshot["runtime"],
        }
        result = {"state.json": canonical(state) + b"\n"}
        for kind, name in (("source", "sources.json"), ("claim", "claims.json")):
            result[name] = (
                canonical(
                    {
                        "schema_version": 1,
                        "case_revision": snapshot["case_revision"],
                        "snapshot_digest": digest(snapshot),
                        "records": [r for r in active if r["kind"] == kind],
                    }
                )
                + b"\n"
            )
        for record in active:
            if record["kind"] == "extraction":
                result[f"extracted/{record['id']}/manifest.json"] = canonical(record) + b"\n"
            if record["kind"] == "calculation":
                result[f"calculations/{record['id']}/manifest.json"] = canonical(record) + b"\n"
                for index, reference in enumerate(record["payload"].get("output_refs", [])):
                    artifact = records[key(reference)]["payload"]
                    suffix = "csv" if artifact["media_type"] == "text/csv" else "json"
                    result[f"calculations/{record['id']}/output-{index}.{suffix}"] = self.blob(artifact["sha256"])
        result["usage.jsonl"] = b"".join(
            canonical(
                {
                    "entry_kind": "local_action",
                    "action_id": action_id,
                    "attempt_id": action["attempt_id"],
                    "status": action["status"],
                    "usage": action["usage"],
                }
            )
            + b"\n"
            for action_id, action in snapshot["actions"].items()
        )
        result["usage.jsonl"] += b"".join(
            canonical(
                {
                    "entry_kind": "adapter_attempt",
                    "action_id": attempt["reservation_action_id"],
                    "attempt_id": attempt_id,
                    "status": attempt["status"],
                    "adapter": attempt["adapter"],
                    "usage": attempt["usage"],
                }
            )
            + b"\n"
            for attempt_id, attempt in snapshot["attempts"].items()
        )
        from .research_projections import host_usage_rows

        result["usage.jsonl"] += b"".join(canonical(row) + b"\n" for row in host_usage_rows(records))
        lines = [
            "# Передача контекста кейса",
            "",
            f"Case: {self.case_id}; revision: {snapshot['case_revision']}; digest: {digest(snapshot)}",
            f"Этап: {state['stage']}",
            "Далее: " + state["next_action"],
            "Ожидаем человека: " + (state["awaiting_human"] or "нет"),
            "",
            "Открытые вопросы:",
        ]
        lines += ["- " + question for question in state["open_questions"]]
        lines += [
            "",
            f"Выполненных действий: {len(state['completed_actions'])}",
            "Проверяемые записи: records/; authoritative snapshot: journal/; история: events.jsonl.",
            "Прошлый ответ агента не является первоисточником; расходы host unknown.",
        ]
        for record in active:
            if record["kind"] == "brief":
                result["brief.md"] = ("# Бриф\n\n" + record["payload"]["goal"] + "\n").encode()
        result["handoff.md"] = ("\n".join(lines) + "\n").encode()
        from .research_projections import projections

        result.update(projections(snapshot, records, self.blob))
        return result

    def _projection_warnings(self, snapshot):
        expected = self._projection_bytes(snapshot)
        warnings = []
        for name, raw in expected.items():
            path = self.base + "/" + name
            if not self.io.exists(path):
                warnings.append("missing_projection:" + name)
                continue
            actual = self.io.read(path)
            if name == "state.json":
                try:
                    state = parse_json(actual)
                except CoreError as exc:
                    raise CoreError(
                        "STATE_CORRUPT", "State projection is malformed; preserve it and diagnose", 6
                    ) from exc
                if not isinstance(state, dict) or state.get("schema_version") != 1:
                    raise CoreError("STATE_SCHEMA", "Unknown state schema; no silent reset", 6)
            if actual != raw:
                warnings.append("stale_projection:" + name)
        return warnings

    def _project(self, snapshot):
        for index, (name, raw) in enumerate(self._projection_bytes(snapshot).items()):
            self.io.write(self.base + "/" + name, raw)
            if index == 0:
                self._failpoint("during_projection")

    def _failpoint(self, point):
        selected = os.environ.get("STRATEGIST_TEST_FAILPOINT")
        if selected:
            if (
                self.namespace != "test"
                or not self.case_id.startswith("test-")
                or os.environ.get("STRATEGIST_TEST_MODE") != "1"
            ):
                raise CoreError("TEST_ONLY", "Fault injection is restricted to explicit test cases", 4)
            if selected == point:
                os._exit(97)

    def _commit(self, snapshot, files, *, name, fingerprint, result, status="succeeded", started=None):
        action_id = self._allocate("ACT")
        attempt_id = str(uuid.uuid4())
        snapshot["case_revision"] += 1
        snapshot["updated_at"] = now()
        duration = (time.monotonic() - started) * 1000 if started is not None else None
        snapshot["actions"][action_id] = {
            "operation": name,
            "input_fingerprint": fingerprint,
            "attempt_id": attempt_id,
            "status": status,
            "at": snapshot["updated_at"],
            "usage": unknown_usage(duration),
        }
        if "reserved_attempt_id" in result:
            snapshot["attempts"][result["reserved_attempt_id"]]["reservation_action_id"] = action_id
        if status == "succeeded":
            snapshot["runtime"]["completed_actions"].append(action_id)
            snapshot["operations"][fingerprint] = {
                "action_id": action_id,
                "attempt_id": attempt_id,
                "data": copy.deepcopy(result),
            }
        for record in result.pop("_records", []):
            record["action_id"] = action_id
            path = f"{self.base}/records/{record['kind']}/{record['id']}/{record['revision']}.json"
            raw = canonical(record) + b"\n"
            files[path] = raw
            snapshot["records"][key(ref(record))] = {"path": path, "sha256": sha(raw)}
            snapshot["active"][record["id"]] = record["revision"]
        # Never store the internal staging records in idempotency receipts.
        if status == "succeeded":
            snapshot["operations"][fingerprint]["data"] = copy.deepcopy(result)
        existing = self.records(
            {**snapshot, "records": {k: v for k, v in snapshot["records"].items() if v["path"] not in files}}
        )
        all_records = {
            **existing,
            **{key(ref(parse_json(raw))): parse_json(raw) for path, raw in files.items() if "/records/" in path},
        }
        snapshot["runtime"]["stage"] = lifecycle_stage(snapshot, all_records)
        blob_reader = lambda h: (
            files[self.base + "/artifacts/sha256/" + h]
            if self.base + "/artifacts/sha256/" + h in files
            else self.blob(h)
        )
        validate_schema("snapshot", snapshot)
        validate_records(all_records, snapshot["namespace"], self.case_id, blob_reader)
        self._validate_ledger(snapshot)
        tx = uuid.uuid4().hex
        snapshot_path = f"{self.base}/journal/{tx}/snapshot.json"
        files[snapshot_path] = canonical(snapshot) + b"\n"
        for path, raw in files.items():
            self.io.write(path, raw, immutable=True)
        self._failpoint("before_prepare")
        previous_commit = next((row["sha256"] for row in reversed(self.rows) if row["type"] == "COMMIT"), None)
        self._append(
            {
                "type": "PREPARE",
                "tx_id": tx,
                "previous_commit": previous_commit,
                "snapshot_path": snapshot_path,
                "files": {path: sha(raw) for path, raw in files.items()},
            }
        )
        self._failpoint("after_prepare")
        prepare_hash = self.rows[-1]["sha256"]
        self._append({"type": "COMMIT", "tx_id": tx, "prepare_hash": prepare_hash})
        self._failpoint("after_commit")
        self._project(snapshot)
        return {
            "case_revision": snapshot["case_revision"],
            "action_id": action_id,
            "attempt_id": attempt_id,
            "data": {**result, "reused": False},
            "warnings": [],
        }

    def init(self, namespace):
        if namespace not in {"test", "demo", "official"} or (namespace == "test") != self.case_id.startswith("test-"):
            raise CoreError(
                "NAMESPACE", "Test namespaces require test-* IDs and may not masquerade as demo/official", 4
            )
        with self.io.lock(self.lock_path):
            gates = self.io.json("config/gates.json")
            gate = "B" if namespace == "official" else "D" if namespace == "demo" else None
            if gate and (gates["gates"][gate]["status"] != "confirmed" or not gates["gates"][gate].get("evidence")):
                raise CoreError("GATE_REQUIRED", "Case namespace needs a real brief/demo confirmation", 3)
            self.io.mkdir_exclusive(self.base)
            self.namespace = namespace
            snapshot = {
                "schema_version": 1,
                "case_id": self.case_id,
                "namespace": namespace,
                "case_revision": -1,
                "updated_at": now(),
                "records": {},
                "active": {},
                "actions": {},
                "operations": {},
                "attempts": {},
                "runtime": {
                    "stage": "brief",
                    "completed_actions": [],
                    "open_questions": [],
                    "awaiting_human": None,
                    "next_action": "Record the goal, constraints and critical unknowns",
                },
            }
            return self._commit(
                snapshot,
                {},
                name="init",
                fingerprint=digest({"case": self.case_id, "namespace": namespace}),
                result={"initialized": True},
            )

    def status(self):
        with self.io.lock(self.lock_path):
            snapshot, warnings, _ = self._load()
            return {
                "case_revision": snapshot["case_revision"],
                "data": {
                    "case_id": self.case_id,
                    "namespace": self.namespace,
                    "state": snapshot["runtime"],
                    "snapshot_digest": digest(snapshot),
                    "active": snapshot["active"],
                    "record_count": len(snapshot["records"]),
                    "action_count": len(snapshot["actions"]),
                    "attempts": snapshot["attempts"],
                },
                "warnings": warnings,
            }

    def validate(self):
        result = self.status()
        if result["warnings"]:
            raise CoreError(
                "PROJECTIONS_STALE",
                "Committed snapshot is valid but projections need a checkpoint rebuild",
                6,
                saved=result["case_revision"],
            )
        result["data"]["validation"] = "structural_only"
        return result

    def note_failure(self, operation, fingerprint, error, expected=None):
        """Journal a known-case preflight failure; never write to corrupt/stale state."""
        if error.exit_code in {6, 7} or getattr(error, "journaled", False):
            return
        with self.io.lock(self.lock_path):
            snapshot, _, _ = self._load()
            if expected is not None and snapshot["case_revision"] != expected:
                return
            self._append(
                {
                    "type": "ERROR",
                    "operation": operation,
                    "code": error.code,
                    "input_fingerprint": fingerprint,
                    "usage": unknown_usage(),
                }
            )
            error.journaled = True
            error.saved = snapshot["case_revision"]

    def _mutate(self, name, request, expected, builder, *, reuse_if=None):
        started = time.monotonic()
        if type(expected) is not int or expected < 0:
            raise CoreError("EXPECTED_REVISION", "Mutation requires a nonnegative expected revision")
        with self.io.lock(self.lock_path):
            snapshot, _, _ = self._load()
            if snapshot["case_revision"] != expected:
                raise CoreError(
                    "CONFLICT",
                    "Snapshot changed; reread status and inspect the previous result",
                    7,
                    saved=snapshot["case_revision"],
                )
            if os.environ.get("STRATEGIST_TEST_FAILPOINT"):
                self._failpoint("check_scope")
            fingerprint = digest({"schema_version": 1, "case_id": self.case_id, "command": name, "request": request})
            reserve = name == "record:action" and request.get("payload", {}).get("operation") == "reserve"
            if (
                fingerprint in snapshot["operations"]
                and not reserve
                and (reuse_if is None or reuse_if(snapshot, snapshot["operations"][fingerprint]["data"]))
            ):
                prior = snapshot["operations"][fingerprint]
                self._project(snapshot)
                return {
                    "case_revision": expected,
                    "action_id": prior["action_id"],
                    "attempt_id": prior["attempt_id"],
                    "data": {**prior["data"], "reused": True},
                    "warnings": [],
                }
            original = copy.deepcopy(snapshot)
            try:
                result, staged = builder(snapshot)
                return self._commit(
                    snapshot, staged, name=name, fingerprint=fingerprint, result=result, started=started
                )
            except CoreError as exc:
                if exc.code in {"BUDGET_EXHAUSTED", "OUTCOME_UNKNOWN", "ATTEMPT_PENDING"}:
                    original["runtime"].update(awaiting_human=exc.reason, next_action=exc.next_action)
                    saved = self._commit(
                        original,
                        {},
                        name=name,
                        fingerprint=fingerprint,
                        result={"blocked": exc.code},
                        status="blocked",
                        started=started,
                    )
                    exc.saved = saved["case_revision"]
                    exc.journaled = True
                elif exc.exit_code not in {6, 7}:
                    self._append(
                        {
                            "type": "ERROR",
                            "operation": name,
                            "code": exc.code,
                            "input_fingerprint": fingerprint,
                            "usage": unknown_usage((time.monotonic() - started) * 1000),
                        }
                    )
                    exc.journaled = True
                raise

    def _new_record(self, snapshot, records, kind, payload, entity_id=None, created_by="host_agent"):
        if kind not in PREFIX:
            raise CoreError("UNKNOWN_KIND", "Unsupported record kind")
        validate_payload(kind, payload)
        if entity_id is not None and not isinstance(entity_id, str):
            raise CoreError("UPDATE_ID", "An existing entity ID must be a string")
        if kind == "artifact" and entity_id is not None:
            raise CoreError(
                "ARTIFACT_IMMUTABLE", "An artifact is a content identity; changed metadata/bytes require a new ART ID"
            )
        if entity_id is not None and entity_id in snapshot["active"]:
            prior = records[f"{entity_id}@{snapshot['active'][entity_id]}"]
            if prior["payload"].get("contract_version") == 3 and payload.get("contract_version") != 3:
                raise CoreError("CONTRACT_VERSION", "An existing v3 entity cannot downgrade to a legacy payload")
        from .research_contracts import validate_new

        validate_new(snapshot, records, kind, payload)
        if entity_id is not None:
            if (
                not isinstance(entity_id, str)
                or re.fullmatch(PREFIX[kind] + r"-[0-9]{3,}", entity_id) is None
                or entity_id not in snapshot["active"]
            ):
                raise CoreError("UPDATE_ID", "Updates must reference an existing ID of the same kind")
        else:
            entity_id = self._allocate(PREFIX[kind])
        previous = snapshot["active"].get(entity_id)
        revision = 1
        directory = f"{self.base}/records/{kind}/{entity_id}"
        if self.io.exists(directory):
            revision = (
                max(
                    [int(name[:-5]) for name in self.io.listdir(directory) if re.fullmatch(r"[0-9]+\.json", name)] + [0]
                )
                + 1
            )
        record = {
            "schema_version": 1,
            "case_id": self.case_id,
            "id": entity_id,
            "kind": kind,
            "revision": revision,
            "previous_revision": previous,
            "created_at": now(),
            "created_by": created_by,
            "action_id": "ACT-000",
            "payload": payload,
            "lineage_roots": [],
        }
        record["lineage_roots"] = inherited_origin(record, records, snapshot["namespace"])
        return record

    def record(self, kind, request, expected, *, artifacts=None):
        if not isinstance(request, dict) or set(request) - {"id", "payload", "created_by"} or "payload" not in request:
            raise CoreError("RECORD_REQUEST", "Record file requires payload and optional id/created_by only")

        def builder(snapshot):
            records = self.records(snapshot)
            payload = copy.deepcopy(request["payload"])
            record = self._new_record(
                snapshot, records, kind, payload, request.get("id"), request.get("created_by", "host_agent")
            )
            data = {"ref": ref(record)}
            if kind == "action":
                data.update(self._apply_action(snapshot, payload, records))
            if kind == "brief":
                snapshot["runtime"]["open_questions"] = payload["open_questions"]
                snapshot["runtime"]["next_action"] = (
                    "Clarify up to three critical questions; do not invent missing facts"
                )
            if kind == "approval":
                for target in payload["targets"]:
                    if snapshot["active"].get(target["entity_id"]) != target["revision"]:
                        raise CoreError("APPROVAL_STALE", "Approval target is no longer the current proposal", 3)
                if payload["status"] != "requested" and any(
                    r["kind"] == "approval" and r["payload"].get("request_ref") == payload.get("request_ref")
                    for r in records.values()
                ):
                    raise CoreError(
                        "APPROVAL_ANSWERED", "Request already has a receipt; create a new request for a new choice", 3
                    )
                if payload["scope"] in {"option_choice", "final_decision", "reconsideration"}:
                    if payload["status"] == "requested":
                        snapshot["runtime"].update(
                            awaiting_human=payload["scope"],
                            next_action="Obtain the real product user's response to this exact bundle; do not infer approval",
                        )
                    elif payload["status"] == "approve":
                        snapshot["runtime"].update(
                            awaiting_human=None,
                            next_action="Prepare the next explicit proposal; this receipt does not approve future revisions",
                        )
                    else:
                        snapshot["runtime"].update(
                            awaiting_human=None,
                            next_action="Revise the proposal using the recorded rejection/revision; request a new approval",
                        )
            staged = {}
            for content_hash, raw in (artifacts or {}).items():
                if sha(raw) != content_hash:
                    raise CoreError("ARTIFACT_HASH", "Staged bytes have a different hash")
                staged[self.base + "/artifacts/sha256/" + content_hash] = raw
            return {**data, "_records": [record]}, staged

        return self._mutate("record:" + kind, request, expected, builder)

    def checkpoint(self, reason, expected):
        if not isinstance(reason, str) or not reason.strip():
            raise CoreError("CHECKPOINT_REASON", "Checkpoint reason is required")
        return self._mutate("checkpoint", {"reason": reason}, expected, lambda snapshot: ({"checkpoint": True}, {}))

    def recover(self, expected=None, repair_tail=False):
        with self.io.lock(self.lock_path):
            snapshot, warnings, tail = self._load(allow_tail=True)
            if not repair_tail:
                return {
                    "case_revision": snapshot["case_revision"],
                    "data": {"tail_bytes": len(tail), "projections_need_rebuild": bool(warnings), "read_only": True},
                    "warnings": warnings + (["unfinished_tail"] if tail else []),
                }
            if type(expected) is not int or snapshot["case_revision"] != expected:
                raise CoreError("CONFLICT", "Repair needs the diagnosed committed revision", 7)
            if not tail:
                raise CoreError("NO_TAIL", "No proven unfinished tail to repair")
            raw = self.io.read(self.events, 64 * 1024 * 1024)
            quarantine = f"{self.base}/journal/tail-{uuid.uuid4().hex}.bin"
            self.io.write(quarantine, tail, immutable=True)
            self.io.write(self.events, raw[: -len(tail)])
            self._append(
                {
                    "type": "ERROR",
                    "operation": "recover",
                    "code": "TAIL_QUARANTINED",
                    "quarantine": quarantine,
                    "sha256_tail": sha(tail),
                }
            )
            self._project(snapshot)
            return {
                "case_revision": snapshot["case_revision"],
                "data": {"tail_saved": quarantine, "repaired": True},
                "warnings": [],
            }

    @staticmethod
    def _validate_ledger(snapshot):
        def usage_check(usage):
            validate_schema("common", usage, "usage")
            money = usage["money"]
            if money["basis"] == "unknown" and money["amount"] is not None:
                raise CoreError("UNKNOWN_COST", "Unknown money must remain null, not zero")
            if money["basis"] != "unknown" and (money["amount"] is None or not money["currency"]):
                raise CoreError("KNOWN_COST", "Known/estimated money requires an amount and currency")
            if (usage["tokens"] is None or usage["human_minutes"] is None or money["basis"] == "unknown") and not usage[
                "unknown_reason"
            ]:
                raise CoreError("UNKNOWN_REASON", "Missing usage requires an explicit unknown reason")

        for action_id, action in snapshot["actions"].items():
            if not re.fullmatch(r"ACT-[0-9]{3,}", action_id) or action.get("status") not in {"succeeded", "blocked"}:
                raise CoreError("ACTION_LEDGER", "Action ledger is invalid", 6)
            usage_check(action["usage"])
        if any(
            action_id not in snapshot["actions"] or snapshot["actions"][action_id]["status"] != "succeeded"
            for action_id in snapshot["runtime"]["completed_actions"]
        ):
            raise CoreError("FALSE_COMPLETION", "Only successful actions may be completed", 6)
        for attempt_id, attempt in snapshot["attempts"].items():
            if attempt.get("status") not in {
                "reserved",
                "succeeded",
                "failed",
                "outcome_unknown",
            } or attempt_id != attempt.get("attempt_id"):
                raise CoreError("ATTEMPT_LEDGER", "Attempt ledger is invalid", 6)
            if attempt.get("reservation_action_id") not in snapshot["actions"]:
                raise CoreError("RESERVATION_ACTION", "Attempt has no committed reservation action", 6)
            if attempt.get("usage"):
                usage_check(attempt["usage"])

    def _apply_action(self, snapshot, payload, records):
        operation = payload["operation"]
        if operation == "note":
            snapshot["runtime"].update(payload.get("runtime", {}))
            return {}
        if operation == "reserve":
            required = {"operation_key", "permission_ref", "external", "adapter", "estimated_money"}
            if not required.issubset(payload):
                raise CoreError(
                    "RESERVATION_FIELDS", "Reservation needs key, permission, adapter, external flag and money estimate"
                )
            for attempt in snapshot["attempts"].values():
                if attempt["operation_key"] == payload["operation_key"]:
                    if attempt["status"] in {"reserved", "outcome_unknown"}:
                        code = "OUTCOME_UNKNOWN" if attempt["status"] == "outcome_unknown" else "ATTEMPT_PENDING"
                        raise CoreError(
                            code,
                            "External outcome is unresolved; do not repeat the operation",
                            3,
                            next_action="Reconcile the saved attempt using a real provider/host receipt",
                        )
                    raise CoreError(
                        "ATTEMPT_FINISHED",
                        "Operation already has a terminal receipt; reuse it instead of calling again",
                        3,
                        data=attempt,
                    )
            permission_record = records.get(key(payload["permission_ref"]))
            if not permission_record or permission_record["kind"] != "permission":
                raise CoreError("PERMISSION_REQUIRED", "Reservation needs an existing approved permission", 3)
            permission = permission_record["payload"]
            approval = records[key(permission["approval_ref"])]["payload"]
            if payload["external"] and (not permission["external_allowed"] or approval.get("approval_kind") != "real"):
                raise CoreError("EXTERNAL_DENIED", "No real permission for an external call", 4)
            if not payload["external"] and snapshot["namespace"] != "test":
                raise CoreError("SIMULATION_ONLY", "Simulated reservations are restricted to test cases", 4)
            # A second PER record backed by the same APR must not reset its quota.
            calls = [
                a
                for a in snapshot["attempts"].values()
                if records[key(a["permission_ref"])]["payload"]["approval_ref"] == permission["approval_ref"]
            ]
            if len(calls) >= permission["call_limit"]:
                raise CoreError(
                    "BUDGET_EXHAUSTED",
                    "Approved call count is exhausted",
                    3,
                    next_action="Request a new scoped resource approval; progress is checkpointed",
                )
            estimate = payload["estimated_money"]
            if (
                estimate is not None
                and permission["money_limit"] is not None
                and (not permission.get("currency") or payload.get("estimated_currency") != permission["currency"])
            ):
                raise CoreError("CURRENCY_REQUIRED", "Strict money caps need a matching explicit estimate currency", 3)
            if permission["money_limit"] is not None and any(
                a["status"] != "reserved" and a["usage"]["money"]["amount"] is None for a in calls
            ):
                raise CoreError(
                    "BUDGET_EXHAUSTED",
                    "Unknown settled cost prevents a monetary guarantee",
                    3,
                    next_action="Reconcile the previous cost before another paid operation",
                )
            known_reserved = sum(max(a["estimated_money"] or 0, a["usage"]["money"]["amount"] or 0) for a in calls)
            if (
                estimate is None and (not permission["allow_unknown_money"] or permission["money_limit"] is not None)
            ) or (
                permission["money_limit"] is not None and known_reserved + (estimate or 0) > permission["money_limit"]
            ):
                raise CoreError(
                    "BUDGET_EXHAUSTED",
                    "Unknown/estimated cost cannot fit the approved monetary cap",
                    3,
                    next_action="Approve a known cost or an explicit count/time capped unknown-cost route",
                )
            attempt_id = str(uuid.uuid4())
            snapshot["attempts"][attempt_id] = {
                "attempt_id": attempt_id,
                "operation_key": payload["operation_key"],
                "permission_ref": payload["permission_ref"],
                "external": payload["external"],
                "adapter": payload["adapter"],
                "estimated_money": estimate,
                "estimated_currency": payload.get("estimated_currency"),
                "status": "reserved",
                "provider_request_id": None,
                "usage": unknown_usage(),
                "reserved_at": now(),
            }
            return {"reserved_attempt_id": attempt_id, "external_call_performed": False}
        if not {"attempt_id", "status", "usage"}.issubset(payload) or payload["attempt_id"] not in snapshot["attempts"]:
            raise CoreError(
                "ATTEMPT_REQUIRED", "Settlement/reconciliation needs an existing attempt and actual usage fields"
            )
        attempt = snapshot["attempts"][payload["attempt_id"]]
        if attempt["estimated_currency"] and payload["usage"]["money"]["currency"] not in (
            None,
            attempt["estimated_currency"],
        ):
            raise CoreError("CURRENCY_MISMATCH", "Do not silently combine costs in different currencies")
        if operation == "settle" and attempt["status"] != "reserved":
            raise CoreError("ATTEMPT_TERMINAL", "Settled/unknown attempts may not be blindly settled again", 3)
        if operation == "reconcile":
            evidence = payload.get("evidence_ref")
            if (
                attempt["status"] not in {"reserved", "outcome_unknown"}
                or not evidence
                or key(evidence) not in records
                or records[key(evidence)]["kind"] != "artifact"
                or not payload.get("provider_request_id")
            ):
                raise CoreError(
                    "RECONCILE_EVIDENCE", "Reconciliation needs a real saved receipt and provider/host request ID", 3
                )
        attempt.update(
            status=payload["status"],
            usage=payload["usage"],
            provider_request_id=payload.get("provider_request_id"),
            settled_at=now(),
        )
        if attempt["status"] == "outcome_unknown":
            snapshot["runtime"].update(
                awaiting_human="Reconcile an unknown external outcome",
                next_action="Inspect the provider/host receipt; do not repeat the call",
            )
        return {"settled_attempt_id": payload["attempt_id"], "status": attempt["status"]}
