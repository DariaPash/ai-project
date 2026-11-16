"""Step03 structural bindings. These checks do not judge interview/strategy meaning."""

from datetime import datetime

from .errors import CoreError

NEW_KINDS = {"research_plan", "interview_guide", "interview_analysis", "simulation"}
STRICT_KINDS = {"question", "option", "strategy", "promise", "experiment", "decision"}


def strategy_manifest(payload):
    return {
        name: payload[name]
        for name in (
            "contract_version",
            "strategy_type",
            "selected_option_ref",
            "option_choice_ref",
            "content_sha256",
            "basis_refs",
            "sections",
        )
    }


def validate_new(snapshot, records, kind, payload):
    """Write-only policy: never retroactively invalidate legacy history."""
    if kind == "action" and payload.get("operation") == "note":
        import json

        try:
            note = json.loads(payload.get("note", ""))
        except (ValueError, TypeError):
            note = None
        if isinstance(note, dict) and note.get("type") == "host_dispatch_v5":
            raise CoreError(
                "ROUTE_LEGACY_WRITE", "Legacy dispatch notes are read-only history; prepare a new bound v5.1 intent"
            )
        if isinstance(note, dict) and note.get("type") == "mcp_intent_v1":
            from .contracts import validate_schema

            validate_schema("mcp-request", note, "intent")
    strict = any(r["kind"] == "research_plan" for r in records.values())
    if kind == "experiment" and payload.get("baseline_status") == "measured" and payload.get("baseline_ref"):
        from .contracts import key

        reference = payload["baseline_ref"]
        if key(reference) in records and snapshot["active"].get(reference["entity_id"]) != reference["revision"]:
            raise CoreError(
                "BASELINE_MEASUREMENT", "A new measured baseline cannot silently use a superseded/retracted claim"
            )
    if kind in STRICT_KINDS and (strict or snapshot["namespace"] != "test") and payload.get("contract_version") != 3:
        raise CoreError("CONTRACT_VERSION", "New research/business records require contract_version=3")
    if (
        kind == "approval"
        and payload.get("scope") in {"option_choice", "final_decision", "reconsideration"}
        and (strict or snapshot["namespace"] != "test")
    ):
        from .contracts import key

        if payload["scope"] == "option_choice" and payload.get("terms", {}).get("contract_version") != 3:
            raise CoreError(
                "OPTION_CHOICE_REQUIRED", "Research direction approval requires the strict four-option bundle", 3
            )
        if payload["scope"] != "option_choice" and (
            len(payload["targets"]) != 1
            or records.get(key(payload["targets"][0]), {}).get("payload", {}).get("contract_version") != 3
        ):
            raise CoreError("CONTRACT_VERSION", "New final business approval requires one strict DEC proposal")
    if kind in {"strategy", "decision"} and payload.get("contract_version") == 3:
        from .contracts import key

        choice = records.get(key(payload["option_choice_ref"]))
        if not choice:
            return  # The common missing-ref check gives the stable input error.
        if choice["kind"] != "approval":
            raise CoreError("RESEARCH_REF_KIND", "option_choice_ref must identify an APR receipt")
        if choice["payload"]["scope"] != "option_choice" or choice["payload"]["status"] != "approve":
            raise CoreError(
                "OPTION_CHOICE_REQUIRED", "A final or unanswered APR cannot replace the direction receipt", 3
            )
        for reference in choice["payload"]["targets"] + [payload["option_choice_ref"]]:
            if snapshot["active"].get(reference["entity_id"]) != reference["revision"]:
                raise CoreError("APPROVAL_STALE", "The chosen bundle/receipt changed; obtain a new H approval", 3)
    if kind == "simulation" and payload.get("adapter_attempt_id"):
        attempt = snapshot["attempts"].get(payload["adapter_attempt_id"])
        if not attempt or attempt["status"] != "succeeded" or attempt["usage"] != payload["execution"]["usage"]:
            raise CoreError(
                "SIMULATION_ATTEMPT", "Linked adapter attempt must have a matching successful execution receipt"
            )


def validate_research_record(record, records, namespace, blob_reader):
    from .contracts import key, _check_quote, validate_schema, sha
    from .safeio import canonical, parse_json

    p = record["payload"]
    kind = record["kind"]

    def typed(reference, expected, strict=False):
        target = records[key(reference)]
        if target["kind"] != expected or (strict and target["payload"].get("contract_version") != 3):
            raise CoreError("RESEARCH_REF_KIND", "Research bundle reference has the wrong kind/contract")
        return target

    def choice(reference, selected):
        a = typed(reference, "approval")["payload"]
        if (
            a["scope"] != "option_choice"
            or a["status"] != "approve"
            or a.get("terms", {}).get("contract_version") != 3
            or a["terms"]["selected_option_ref"] != selected
        ):
            raise CoreError(
                "OPTION_CHOICE_REQUIRED",
                "Two-stage research decisions need the applicable approved direction receipt",
                3,
            )
        return a

    if kind == "approval":
        if p["scope"] == "option_choice" and p.get("terms", {}).get("contract_version") == 3:
            terms = p["terms"]
            validate_schema("strategy", terms, "choice_terms")
            plan = typed(terms["research_plan_ref"], "research_plan", True)
            options = [records[key(r)] for r in p["targets"] if records[key(r)]["kind"] == "option"]
            if (
                len(p["targets"]) != 5
                or len(options) != 4
                or {o["payload"]["option_type"] for o in options} != {"status_quo", "improve", "refocus", "close"}
                or terms["research_plan_ref"] not in p["targets"]
                or terms["selected_option_ref"] not in [r for r in p["targets"] if records[key(r)]["kind"] == "option"]
            ):
                raise CoreError(
                    "OPTION_BUNDLE",
                    "Direction bundle must pin four distinct classes, criteria plan and an included selection",
                )
            if any(
                o["payload"].get("contract_version") != 3
                or o["payload"]["research_plan_ref"] != terms["research_plan_ref"]
                for o in options
            ):
                raise CoreError("OPTION_BUNDLE", "All four options must share the exact predeclared research criteria")
        if p["scope"] in {"final_decision", "reconsideration"} and any(
            records[key(r)]["payload"].get("contract_version") == 3 for r in p["targets"]
        ):
            if len(p["targets"]) != 1 or records[key(p["targets"][0])]["kind"] != "decision" or p.get("terms", {}):
                raise CoreError(
                    "FINAL_BUNDLE", "Final approval pins one DEC; business content cannot hide outside its digest"
                )
        return
    if kind not in NEW_KINDS and p.get("contract_version") != 3:
        return
    if kind == "question" and p["outcome"]["status"] == "result" and not p["outcome"]["basis_refs"]:
        raise CoreError("RESEARCH_RESULT", "A resolved question needs pinned evidence, not just a conclusion")
    if kind == "research_plan":
        for r in p["question_refs"]:
            typed(r, "question", True)
        criteria = p["criteria"]
        weights = criteria["weights"]
        for candidate in [weights, *criteria["sensitivity_weights"]]:
            if set(candidate) != set(weights) or abs(sum(candidate.values()) - 1) > 1e-9:
                raise CoreError("CRITERIA_WEIGHTS", "Fixed and sensitivity weights must share keys and sum to one")
    if kind == "option":
        plan = typed(p["research_plan_ref"], "research_plan", True)
        if plan["created_at"] > record["created_at"] or set(p["scores"]) != set(plan["payload"]["criteria"]["weights"]):
            raise CoreError(
                "CRITERIA_ORDER", "Options must use predeclared criteria without silently changing scales/keys"
            )
    if kind in {"interview_guide", "interview_analysis"}:
        typed(p["research_plan_ref"], "research_plan", True)
    if kind == "interview_analysis":
        guide = typed(p["guide_ref"], "interview_guide", True)
        if guide["payload"]["research_plan_ref"] != p["research_plan_ref"]:
            raise CoreError("INTERVIEW_PLAN", "Guide and analysis must use the same plan")
        for r in p["corpus_refs"]:
            typed(r, "source")
        if p["corpus_kind"] == "synthetic_fixture":
            if p["fieldwork_conducted"] or any(
                "synthetic_fixture" not in typed(r, "source")["lineage_roots"] for r in p["corpus_refs"]
            ):
                raise CoreError("FIELDWORK_SCOPE", "A technical corpus is not conducted fieldwork", 4)
        else:
            if not p.get("consent_ref") or not p["fieldwork_conducted"]:
                raise CoreError(
                    "CONSENT_REQUIRED", "Real interview analysis requires a real scoped processing consent", 3
                )
            consent = typed(p["consent_ref"], "approval")["payload"]
            if (
                consent["status"] != "approve"
                or consent.get("approval_kind") != "real"
                or consent["scope"] != "source_access"
                or not consent.get("terms", {}).get("processing")
                or any(r not in consent["targets"] for r in p["corpus_refs"])
                or any(
                    set(typed(r, "source")["lineage_roots"]) & {"synthetic_fixture", "model_simulation", "unknown"}
                    for r in p["corpus_refs"]
                )
            ):
                raise CoreError("CONSENT_REQUIRED", "Consent must cover this exact real corpus and processing scope", 3)
        for theme in p["themes"]:

            def identity(item):
                return canonical(
                    {"ref": item["ref"], "locator": {k: v for k, v in item["locator"].items() if k != "quote_hash"}}
                )

            items = theme["quotes"] + [theme["counterexample"]]
            if (
                len({key(q["ref"]) for q in theme["quotes"]}) < 2
                or any(q["ref"] not in p["corpus_refs"] for q in items)
                or any(identity(theme["counterexample"]) == identity(q) for q in theme["quotes"])
            ):
                raise CoreError(
                    "INTERVIEW_QUOTES", "Theme needs two corpus sources and a distinct located counterexample"
                )
            for item in items:
                _check_quote(item, records)
    if kind == "simulation":
        execution = p["execution"]
        if execution["mode"] == "fixture" and namespace != "test":
            raise CoreError("SIMULATION_FIXTURE", "Fixture role receipts are test-only", 4)
        if (
            any(turn["speaker"] != ("interviewer" if i % 2 == 0 else "respondent") for i, turn in enumerate(p["turns"]))
            or len(p["turns"]) % 2
        ):
            raise CoreError("DIALOGUE_TURNS", "Log alternating question/answer plus clarification/answer turns")
        if datetime.fromisoformat(execution["ended_at"]) < datetime.fromisoformat(execution["started_at"]):
            raise CoreError("EXECUTION_TIME", "Role end must not precede its start")
        if (execution["mode"] == "host_inline" and execution["context_independence"] != "not_independent") or (
            execution["mode"] == "isolated_host"
            and (not execution.get("session_id") or execution["context_independence"] != "separate_context")
        ):
            raise CoreError("EXECUTION_CONTEXT", "Execution receipt must not invent context independence")
        usage = execution["usage"]
        if usage["money"]["basis"] != "unknown" and (
            usage["money"]["amount"] is None or not usage["money"]["currency"]
        ):
            raise CoreError("UNKNOWN_USAGE", "Actual/estimated model cost requires a known amount and currency")
        if (usage["money"]["basis"] == "unknown" and usage["money"]["amount"] is not None) or (
            (usage["tokens"] is None or usage["human_minutes"] is None or usage["money"]["basis"] == "unknown")
            and not usage["unknown_reason"]
        ):
            raise CoreError("UNKNOWN_USAGE", "Unknown execution cost/usage needs null and an explanation")
        transcript = typed(p["transcript_ref"], "artifact")
        expected = {k: v for k, v in p.items() if k != "transcript_ref"}
        if execution["mode"] != "fixture":
            for other in records.values():
                op = other["payload"]
                if (
                    other["kind"] == "simulation"
                    and op["execution"]["mode"] != "fixture"
                    and op["execution_id"] == p["execution_id"]
                    and {k: v for k, v in op.items() if k != "transcript_ref"} != expected
                ):
                    raise CoreError(
                        "SIMULATION_EXECUTION",
                        "One actual execution ID cannot be reused for different turns/usage/inputs",
                    )
        if (
            "model_simulation" not in transcript["lineage_roots"]
            or transcript["payload"]["media_type"] != "application/json"
            or parse_json(blob_reader(transcript["payload"]["sha256"])) != expected
        ):
            raise CoreError(
                "SIMULATION_RECEIPT", "Role turns/receipt must match their immutable model-origin JSON artifact"
            )
        if execution["mode"] != "fixture" and transcript["payload"].get("processing_kind") != "LLM-assisted":
            raise CoreError("SIMULATION_RECEIPT", "An ACT note/reservation is not a completed host dialogue transcript")
    if kind == "strategy":
        choice(p["option_choice_ref"], p["selected_option_ref"])
        typed(p["selected_option_ref"], "option", True)
        artifact = typed(p["artifact_ref"], "artifact")
        manifest = typed(p["manifest_ref"], "artifact")
        raw = p["text"].encode()
        parents = [p["selected_option_ref"], p["option_choice_ref"], *p["basis_refs"]]
        if any(parent not in a["payload"]["parent_refs"] for a in (artifact, manifest) for parent in parents):
            raise CoreError(
                "STRATEGY_LINEAGE",
                "Strategy content and manifest artifacts must inherit all proposal evidence parents",
                4,
            )
        if (
            sha(raw) != p["content_sha256"]
            or artifact["payload"]["sha256"] != p["content_sha256"]
            or blob_reader(artifact["payload"]["sha256"]) != raw
            or parse_json(blob_reader(manifest["payload"]["sha256"])) != strategy_manifest(p)
        ):
            raise CoreError(
                "STRATEGY_ARTIFACT", "Strategy text/digest/manifest must identify exactly the same immutable proposal"
            )
    if kind == "promise":
        _check_quote(p["capability_evidence"], records)
    if kind == "experiment":
        if (p["baseline_status"] == "unknown") != (p["baseline"] is None):
            raise CoreError("BASELINE_UNKNOWN", "Unknown baseline stays null; measured/assumed baseline is explicit")
        if p["baseline_status"] == "measured":
            if not p.get("baseline_ref"):
                raise CoreError("BASELINE_REF", "Measured baseline requires real pinned evidence")
            target = records[key(p["baseline_ref"])]
            if target["kind"] not in {"source", "calculation", "claim"} or set(target["lineage_roots"]) & {
                "synthetic_fixture",
                "model_simulation",
                "unknown",
            }:
                raise CoreError(
                    "SYNTHETIC_AS_REAL", "Synthetic/unknown inputs cannot become a measured real baseline", 4
                )
            if (
                target["kind"] != "claim"
                or target["payload"]["type"] != "fact"
                or target["payload"]["status"] != "supported"
                or target["payload"].get("support_scope") != "real_world"
                or not target["payload"]["evidence"]
            ):
                raise CoreError(
                    "BASELINE_MEASUREMENT",
                    "Measured baseline needs a reviewed real-world fact claim with located measurement evidence, not an unverified hypothesis/source/assumption",
                )
    if kind == "decision":
        approval = choice(p["option_choice_ref"], p["selected_option_ref"])
        remaining = {
            key(r) for r in approval["targets"] if records[key(r)]["kind"] == "option" and r != p["selected_option_ref"]
        }
        if {key(r) for r in p["rejected_refs"]} != remaining:
            raise CoreError(
                "DECISION_OPTIONS", "Selected/rejected refs must exactly match the approved four-option bundle"
            )
        strategies = [typed(r, "strategy", True)["payload"] for r in p["strategy_refs"]]
        if {s["strategy_type"] for s in strategies} != {"product", "communication"} or any(
            s["selected_option_ref"] != p["selected_option_ref"] or s["option_choice_ref"] != p["option_choice_ref"]
            for s in strategies
        ):
            raise CoreError(
                "DECISION_STRATEGIES",
                "DEC requires matching product and communication strategies for the approved direction",
            )
        typed(p["experiment_ref"], "experiment", True)
        for r in p["promise_refs"]:
            typed(r, "promise", True)
        communication = next(s for s in strategies if s["strategy_type"] == "communication")
        if any(r not in communication["basis_refs"] for r in p["promise_refs"]) or any(
            p["experiment_ref"] not in s["basis_refs"] for s in strategies
        ):
            raise CoreError(
                "DECISION_BUNDLE", "Both strategies must pin the experiment; communication must pin the promise matrix"
            )
