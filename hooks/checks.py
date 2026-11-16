"""Explicit durable hooks: validate, release gate, pause and evidence reminder."""

from tools.contracts import key, ref
from tools.errors import CoreError
from tools.safeio import canonical


def run(store, request, expected):
    if not isinstance(request, dict) or set(request) - {"event", "procedure_id", "procedure_version", "basis_refs"}:
        raise CoreError("HOOK_SPEC", "Hook needs event, procedure identity and pinned basis refs")
    event = request.get("event")
    if event not in {"post-ingest", "pre-release", "on-pause", "on-new-evidence", "procedure"}:
        raise CoreError("HOOK_EVENT", "Unknown explicit workflow event")
    for name in ("procedure_id", "procedure_version"):
        if not isinstance(request.get(name), str) or not request[name]:
            raise CoreError("HOOK_SPEC", "Procedure identity/version required")
    status = store.status()
    if status["case_revision"] != expected:
        raise CoreError("CONFLICT", "Read a fresh revision", 7)
    checked = store.validate()
    snapshot, _, _ = store._load()
    records = store.records(snapshot)
    for reference in request.get("basis_refs", []):
        if reference.get("case_id") != store.case_id or key(reference) not in records:
            raise CoreError("HOOK_REF", "Procedure basis must exist in this case")
    blocked = []
    if event == "pre-release":
        reviews = [r for r in records.values() if r["kind"] == "review"]
        if not reviews:
            blocked.append("No actual isolated review receipt")
        for r in reviews:
            if snapshot["active"].get(r["id"]) != r["revision"]:
                continue
            p = r["payload"]
            current = all(snapshot["active"].get(x["entity_id"]) == x["revision"] for x in p["target_refs"])
            if current and p["verdict"] == "changes_required":
                blocked.append("Current review has blocking findings: " + r["id"])
        if not any(
            r["payload"]["verdict"] == "no_blocking_findings"
            and all(snapshot["active"].get(x["entity_id"]) == x["revision"] for x in r["payload"]["target_refs"])
            for r in reviews
        ):
            blocked.append("No clean review on current exact targets")
        if status["data"]["state"]["awaiting_human"]:
            blocked.append("Business approval still pending")
        blocked.append("Official brief/publication/submission gates are not confirmed by this hook")
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
