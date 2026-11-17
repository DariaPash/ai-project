"""Explicit durable hooks: validate, release gate, pause and evidence reminder."""

from tools.contracts import key, ref, validate_schema
from tools.errors import CoreError
from tools.safeio import canonical
from tools.graph import effective


def release_blockers(snapshot, records, state, request):
    """Exact strategy/material checks; this hook never performs legal submission."""
    scope = request.get("release_scope", "strategy")
    if scope not in {"strategy", "materials", "contest_submission"}:
        raise CoreError("HOOK_SCOPE", "release_scope must be strategy, materials or contest_submission")
    targets = request.get("basis_refs", [])
    wanted = {key(r) for r in targets}
    blocked = []
    if not wanted:
        return ["Release requires explicit exact basis_refs"]
    if any(snapshot["active"].get(r["entity_id"]) != r["revision"] for r in targets):
        blocked.append("Release targets are superseded; obtain fresh review and approval")
    if any(not effective(snapshot, records, r)["eligible"] for r in targets):
        blocked.append("Release targets contain withdrawn or processing-denied dependencies")
    reviewed = set()
    for record in records.values():
        if record["kind"] != "review" or snapshot["active"].get(record["id"]) != record["revision"]:
            continue
        payload = record["payload"]
        refs = payload["target_refs"]
        if not all(snapshot["active"].get(r["entity_id"]) == r["revision"] for r in refs):
            continue
        overlap = wanted & {key(r) for r in refs}
        if not overlap:
            continue
        if payload["verdict"] == "changes_required" or any(f["severity"] in {"P1", "P2"} for f in payload["findings"]):
            blocked.append("Current review has blocking findings: " + record["id"])
        else:
            reviewed.update(overlap)
    if wanted - reviewed:
        blocked.append("No clean isolated review covering every exact release target")
    if scope == "strategy":
        if state["awaiting_human"]:
            blocked.append("Business approval still pending")
        confirmed = []
        for record in records.values():
            if (
                record["kind"] != "decision"
                or snapshot["active"].get(record["id"]) != record["revision"]
                or record["payload"]["status"] != "confirmed"
            ):
                continue
            approval_ref = record["payload"].get("approval_ref")
            approval = records.get(key(approval_ref)) if approval_ref else None
            if (
                approval
                and approval["kind"] == "approval"
                and snapshot["active"].get(approval["id"]) == approval["revision"]
                and approval["payload"].get("status") == "approve"
                and approval["payload"].get("scope") in {"final_decision", "reconsideration"}
                and approval["payload"].get("approval_kind") == "real"
                and effective(snapshot, records, ref(record))["eligible"]
            ):
                confirmed.append(record)
        if not any(
            wanted <= {key(ref(r)), *(key(x) for x in r["payload"].get("strategy_refs", []))} for r in confirmed
        ):
            blocked.append("No real confirmed decision binding these exact strategy targets")
    else:
        reference = request.get("approval_ref")
        approval = records.get(key(reference)) if reference else None
        payload = approval["payload"] if approval and approval["kind"] == "approval" else {}
        destination = request.get("destination")
        if (
            not approval
            or snapshot["active"].get(approval["id"]) != approval["revision"]
            or payload.get("scope") != "publication"
            or payload.get("status") != "approve"
            or payload.get("approval_kind") != "real"
            or {key(r) for r in payload.get("targets", [])} != wanted
            or not isinstance(destination, str)
            or not destination.strip()
            or payload.get("terms", {}).get("destination") != destination
        ):
            blocked.append("Publication requires a current real approval for exactly these targets and destination")
        if scope == "contest_submission":
            blocked.append(
                "This hook cannot attest legal contest submission; the captain must perform and receipt it separately"
            )
    return blocked


def run(store, request, expected):
    if not isinstance(request, dict) or set(request) - {
        "event",
        "procedure_id",
        "procedure_version",
        "basis_refs",
        "release_scope",
        "approval_ref",
        "destination",
    }:
        raise CoreError("HOOK_SPEC", "Hook needs event, procedure identity and pinned basis refs")
    event = request.get("event")
    if event not in {"post-ingest", "pre-release", "on-pause", "on-new-evidence", "procedure"}:
        raise CoreError("HOOK_EVENT", "Unknown explicit workflow event")
    for name in ("procedure_id", "procedure_version"):
        if not isinstance(request.get(name), str) or not request[name]:
            raise CoreError("HOOK_SPEC", "Procedure identity/version required")
    validate_schema("common", request.get("basis_refs", []), "refs")
    if request.get("approval_ref") is not None:
        validate_schema("common", request["approval_ref"], "ref")
    status = store.status()
    if status["case_revision"] != expected:
        raise CoreError("CONFLICT", "Read a fresh revision", 7)
    checked = store.validate()
    snapshot, _, _ = store._load()
    records = store.records(snapshot)
    for reference in request.get("basis_refs", []):
        if reference.get("case_id") != store.case_id or key(reference) not in records:
            raise CoreError("HOOK_REF", "Procedure basis must exist in this case")
    if request.get("approval_ref") and request["approval_ref"]["case_id"] != store.case_id:
        raise CoreError("HOOK_REF", "Approval must belong to this case")
    blocked = []
    if event == "pre-release":
        blocked = release_blockers(snapshot, records, status["data"]["state"], request)
    note = {
        **request,
        "type": "explicit_hook_v5",
        "structural_warnings": checked["warnings"],
        "blocked": blocked,
        "automation": "Explicit CLI wrapper only; does not intercept IDE calls",
    }
    saved = store.record("action", {"payload": {"operation": "note", "note": canonical(note).decode()}}, expected)
    if event == "on-pause":
        return store.checkpoint("Explicit on-pause hook", saved["case_revision"])
    if blocked:
        raise CoreError("RELEASE_BLOCKED", "; ".join(blocked), 3, saved=saved["case_revision"], data=saved["data"])
    return {
        **saved,
        "data": {
            **saved["data"],
            "event": event,
            "hook_executed": True,
            "impact_computed": False,
            "next_action": "Map new evidence to affected decisions explicitly"
            if event == "on-new-evidence"
            else "Continue the explicit workflow",
        },
    }
