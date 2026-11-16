"""Bounded pinned dependency closure and effective status, not semantic matching."""

import copy
from datetime import datetime
from .contracts import key, ref, references
from .errors import CoreError


def dependency_maps(records):
    forward = {}
    reverse = {}
    for identity, record in records.items():
        if record["kind"] in {"action", "approval", "permission"}:
            continue
        for reference in references(record["payload"], grounding=True):
            target = key(reference)
            forward.setdefault(identity, set()).add(target)
            reverse.setdefault(target, set()).add(identity)
    return forward, reverse


def effective(snapshot, records, reference):
    forward, _ = dependency_maps(records)
    pending = [key(reference)]
    seen = set()
    reasons = []
    while pending:
        identity = pending.pop()
        if identity in seen:
            continue
        seen.add(identity)
        if len(seen) > 2048:
            raise CoreError("GRAPH_LIMIT", "Effective-status traversal exceeds cap", 4)
        r = records.get(identity)
        if not r:
            raise CoreError("MISSING_REF", "Missing graph record")
        latest = records[f"{r['id']}@{snapshot['active'][r['id']]}"]
        p = latest["payload"]
        if r["kind"] == "claim" and p["status"] in {"retracted", "stale"}:
            reasons.append(latest["id"] + ":" + p["status"])
        if r["kind"] == "source" and (p["status"] != "available" or not p["rights"]["processing"]):
            reasons.append(latest["id"] + ":source_unavailable_or_denied")
        if r["kind"] == "artifact":
            pending.extend(
                k
                for k, v in records.items()
                if v["kind"] == "source" and v["payload"]["sha256"] == r["payload"]["sha256"]
            )
        pending.extend(forward.get(identity, ()))
    return {"eligible": not reasons, "reasons": sorted(set(reasons))}


def impact(store, claim_id):
    snapshot, _, _ = store._load()
    records = store.records(snapshot)
    if claim_id not in snapshot["active"]:
        raise CoreError("IMPACT_REF", "Unknown starting entity")
    start = f"{claim_id}@{snapshot['active'][claim_id]}"
    _, reverse = dependency_maps(records)
    # An entity withdrawal affects users of its older pinned revisions too.
    pending = [identity for identity, r in records.items() if r["id"] == claim_id]
    seen = set()
    depth = 0
    while pending:
        next_level = []
        for identity in pending:
            if identity in seen:
                continue
            seen.add(identity)
            next_level.extend(reverse.get(identity, ()))
        if len(seen) > 2048 or depth > 64:
            raise CoreError("GRAPH_LIMIT", "Impact traversal exceeds bounded limits", 4)
        pending = next_level
        depth += 1
    targets = [
        records[k]
        for k in sorted(seen)
        if records[k]["id"] != claim_id and snapshot["active"].get(records[k]["id"]) == records[k]["revision"]
    ]
    return {
        "case_revision": snapshot["case_revision"],
        "data": {
            "start_ref": ref(records[start]),
            "affected": [
                {"ref": ref(r), "kind": r["kind"], "effective": effective(snapshot, records, ref(r))} for r in targets
            ],
            "meaning": "Registered dependency closure only; semantic relevance and revised business approval are not inferred",
            "mutation_performed": False,
        },
    }


def retract(store, request, expected):
    if (
        not isinstance(request, dict)
        or set(request) != {"target_ref", "reason"}
        or not isinstance(request["reason"], str)
        or not request["reason"]
    ):
        raise CoreError("RETRACTION_SPEC", "Retraction needs exact target_ref and nonempty reason")
    snapshot, _, _ = store._load()
    records = store.records(snapshot)
    reference = request["target_ref"]
    if reference.get("case_id") != store.case_id or key(reference) not in records:
        raise CoreError("RETRACTION_REF", "Unknown pinned claim")
    target = records[key(reference)]
    if target["kind"] != "claim" or snapshot["active"].get(target["id"]) != target["revision"]:
        raise CoreError("RETRACTION_REF", "Retraction must target current CLM revision")
    payload = copy.deepcopy(target["payload"])
    payload["status"] = "retracted"
    payload["limitations"].append("Retraction reason: " + request["reason"])
    return store.record("claim", {"id": target["id"], "payload": payload}, expected)


def agenda(store, as_of):
    try:
        instant = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        if instant.tzinfo is None:
            raise ValueError("timezone required")
    except (ValueError, TypeError):
        raise CoreError("AGENDA_TIME", "as-of must include an explicit timezone")
    snapshot, _, _ = store._load()
    records = store.records(snapshot)
    items = []
    for identity, r in records.items():
        if snapshot["active"].get(r["id"]) != r["revision"] or r["kind"] not in {
            "obligation",
            "decision",
            "experiment",
        }:
            continue
        p = r["payload"]
        row = {"ref": ref(r), "kind": r["kind"], "effective": effective(snapshot, records, ref(r))}
        if r["kind"] == "obligation":
            done = p["status"] == "completed"
            row.update(
                action=p["action"],
                status=p["status"],
                owner=p["owner"],
                unassigned=p["owner"] == "unassigned",
                due=p["due"],
                overdue=False
                if p["due"] == "unknown" or done
                else datetime.fromisoformat(p["due"].replace("Z", "+00:00")) < instant,
                due_unknown=p["due"] == "unknown",
                missing_metric=p["metric"] is None,
                completed=done,
                dependency_blocked=any(
                    records[key(x)]["payload"].get("status") in {"blocked", "pending", "retracted", "stale"}
                    for x in p["dependency_refs"]
                ),
            )
        elif r["kind"] == "experiment":
            row.update(
                missing_baseline=p.get("baseline") is None, completed=False, note="Protocol is not a measured outcome"
            )
        else:
            row.update(status=p["status"], review_required=not row["effective"]["eligible"], owner=p["owner"])
        items.append(row)
    return {
        "case_revision": snapshot["case_revision"],
        "data": {
            "as_of": as_of,
            "items": items,
            "awaiting_human": snapshot["runtime"]["awaiting_human"],
            "background_monitoring": False,
        },
    }
