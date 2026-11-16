"""Disposable readable views of pinned records, never a strategy generator."""

from .contracts import key
from .safeio import canonical


def host_usage_rows(records):
    """One charge per actual execution ID; linked adapter usage is reference-only."""
    executions = {}
    for record in records.values():
        if record["kind"] == "route_result":
            p = record["payload"]
            executions.setdefault(
                p["context_id"],
                {
                    "entry_kind": "host_execution",
                    "execution_id": p["context_id"],
                    "mode": "host_manual_bridge",
                    "model": p["model"],
                    "route_refs": [],
                    "accounting_role": "charge",
                    "usage": p["usage"],
                },
            )["route_refs"].append(
                {"case_id": record["case_id"], "entity_id": record["id"], "revision": record["revision"]}
            )
        if record["kind"] == "simulation" and record["payload"]["execution"]["mode"] != "fixture":
            p = record["payload"]
            entry = executions.setdefault(
                p["execution_id"],
                {
                    "entry_kind": "host_execution",
                    "execution_id": p["execution_id"],
                    "mode": p["execution"]["mode"],
                    "model": p["execution"]["model"],
                    "simulation_refs": [],
                    "accounting_role": "reference_only" if p.get("adapter_attempt_id") else "charge",
                    "adapter_attempt_id": p.get("adapter_attempt_id"),
                    "usage": None if p.get("adapter_attempt_id") else p["execution"]["usage"],
                },
            )
            entry["simulation_refs"].append(
                {"case_id": record["case_id"], "entity_id": record["id"], "revision": record["revision"]}
            )
    return list(executions.values())


def render(title, records):
    lines = [
        "# " + title,
        "",
        "Structural projection; origin/status/refs are authoritative in the pinned record. No human approval is implied.",
        "",
    ]
    for record in records:
        lines += [f"## {record['id']}@{record['revision']} — origins: {', '.join(record['lineage_roots'])}", ""]
        for field, value in record["payload"].items():
            lines += ["### " + field, "", value if isinstance(value, str) else canonical(value).decode(), ""]
    return ("\n".join(lines) + "\n").encode()


def projections(snapshot, records, blob_reader):
    active = [records[f"{entity}@{rev}"] for entity, rev in snapshot["active"].items()]
    result = {}
    for kind, title, path in [
        ("research_plan", "Research plan", "output/research-plan.md"),
        ("option", "Options — proposed or fixture-approved, not live H", "output/options.md"),
        ("claim", "Situation claims", "output/situation.md"),
    ]:
        selected = [
            r for r in active if r["kind"] == kind and (kind == "claim" or r["payload"].get("contract_version") == 3)
        ]
        if selected and any(r["kind"] == "research_plan" for r in active):
            result[path] = render(title, selected)
    for record in records.values():
        if record["kind"] in {"interview_guide", "interview_analysis", "simulation"}:
            directory = "interviews" if record["kind"] != "simulation" else "simulations"
            result[f"{directory}/{record['id']}/r{record['revision']}.json"] = canonical(record) + b"\n"
        if record["kind"] == "decision" and record["payload"].get("contract_version") == 3:
            result[f"decisions/{record['id']}/r{record['revision']}.json"] = canonical(record) + b"\n"
        if record["kind"] in {"ux_observation", "ux_journey"}:
            result[f"ux/{record['id']}/r{record['revision']}.json"] = canonical(record) + b"\n"
        if record["kind"] in {"route_result", "review"}:
            result[f"reviews/{record['id']}/r{record['revision']}.json"] = canonical(record) + b"\n"
        if record["kind"] == "obligation":
            result[f"obligations/{record['id']}/r{record['revision']}.json"] = canonical(record) + b"\n"
    decisions = [r for r in active if r["kind"] == "decision" and r["payload"].get("contract_version") == 3]
    if decisions:
        decision = max(decisions, key=lambda r: int(r["id"].split("-")[1]))
        for reference in decision["payload"]["strategy_refs"]:
            strategy = records[key(reference)]
            artifact = records[key(strategy["payload"]["artifact_ref"])]["payload"]
            result["output/" + strategy["payload"]["strategy_type"] + "-strategy.md"] = blob_reader(artifact["sha256"])
        result["output/validation-plan.md"] = render(
            "Validation plan", [records[key(decision["payload"]["experiment_ref"])]]
        )
        result["output/decision-bundle.json"] = (
            canonical(
                {
                    "decision_ref": {
                        "case_id": decision["case_id"],
                        "entity_id": decision["id"],
                        "revision": decision["revision"],
                    },
                    "status": decision["payload"]["status"],
                    "strategy_refs": decision["payload"]["strategy_refs"],
                    "lineage_roots": decision["lineage_roots"],
                }
            )
            + b"\n"
        )
    return result
