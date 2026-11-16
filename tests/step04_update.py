"""Apply permitted media evidence to the existing four-option fixture story."""

import copy
from tools.contracts import key


def update(f, sources, ux, journey):
    claim = f.record(
        "claim",
        {
            "text": "Owned media shows only a static first step and sampled frames; task completion and real customer behavior remain unknown; audio recognition is blocked without OS authorization",
            "type": "interpretation",
            "status": "unverified",
            "origin": "synthetic_fixture",
            "evidence": [],
            "counterevidence": [],
            "basis_refs": [ux, journey, *sources],
            "limitations": [
                "Media fixtures are not real UX or field interviews",
                "Sparse frames do not cover the whole video; OCR critical number/negation remains sample-verification dependent",
            ],
        },
    )
    current = f.records()
    old = current[key(f.proposal)]["payload"] if hasattr(f, "proposal") else None
    if old is None:
        raise ValueError("This helper needs the existing strict DEC fixture proposal bundle")
    # Extend the research question without pretending synthetic media changes the
    # human's direction choice or the previously pinned option/criteria bundle.
    question = f.record(
        "question",
        {
            "contract_version": 3,
            "text": "Does the complete permitted task actually finish, and are availability messages understood?",
            "affected_choice": "All four mechanisms: status quo has no newly proven value; improve needs full-task validation; refocus needs real checker-task observation; close remains conditional on field evidence, not a static mockup.",
            "priority": "high",
            "minimal_evidence": "Consented full-task observation in working UI and independently checked critical words/numbers.",
            "stop_condition": "No approved working UI/participant or unavailable audio verification: preserve gap, do not infer completion.",
            "outcome": {
                "status": "gap",
                "text": "Only owned synthetic pixels and sampled frames; event appearance is not behavior, task outcome unknown.",
                "basis_refs": [claim, ux, journey, *sources],
            },
        },
    )
    prior_plan = next(r for r in current.values() if r["kind"] == "research_plan" and r["id"] == "RPL-001")
    plan = copy.deepcopy(prior_plan["payload"])
    plan["question_refs"].append(question)
    plan["limitations"].append(
        "Media does not establish completion or change four-option ranking; real full-task/critical-span verification is still missing."
    )
    # A supplementary plan, not a revision of approved direction criteria. The
    # old plan/options stay pinned; changing that bundle would require direction H.
    new_plan = f.record("research_plan", plan)
    promises = []
    for old_ref in old["promise_refs"]:
        promise = copy.deepcopy(current[key(old_ref)]["payload"])
        promise["basis_refs"] += [claim, ux, journey]
        promise["qualification"] += (
            " Static NEXT and sampled color changes are not proof of export/completion; planned remains planned. Unverified audio/OCR cannot justify a capability claim."
        )
        promises.append(f.record("promise", promise, old_ref["entity_id"]))
    experiment = copy.deepcopy(current[key(f.experiment)]["payload"])
    experiment["limitations"] += [
        "Synthetic screen is not behavioral evidence; require a permitted full-task observation",
        "Local STT authorization missing; do not insert oracle number/negation into evidence",
    ]
    experiment["guardrails"] += [
        "Ask participant to explain planned/unavailable export, then observe an entire permitted task; do not score screenshot as successful completion."
    ]
    experiment["stop_conditions"] += [
        "No consent/working UI or critical media verification: stop before asserting effect; unknown baseline stays null."
    ]
    new_experiment = f.record("experiment", experiment, f.experiment["entity_id"])
    new_strategies = []
    for old_ref in [f.product, f.communication]:
        p = current[key(old_ref)]["payload"]
        sections = copy.deepcopy(p["sections"])
        field = "dependencies" if p["strategy_type"] == "product" else "forbidden_promises"
        sections[field] += (
            " Media update: first-step screenshot and sparse video do not demonstrate completion; obtain a real permitted full-task observation. No asserted audio number or automatic export."
        )
        basis = [r for r in p["basis_refs"] if r != f.experiment] + [
            new_experiment,
            new_plan,
            *promises,
            claim,
            ux,
            journey,
            *sources,
        ]
        new_strategies.append(
            f.strategy(
                p["strategy_type"],
                p["selected_option_ref"],
                p["option_choice_ref"],
                basis,
                sections,
                entity_id=old_ref["entity_id"],
            )
        )
    proposal = copy.deepcopy(old)
    proposal.update(
        status="pending",
        strategy_refs=new_strategies,
        experiment_ref=new_experiment,
        promise_refs=promises,
        basis_refs=[*old["basis_refs"], new_plan, question, claim, ux, journey, *sources],
    )
    for name in ["approved_proposal_ref", "approval_ref", "business_content_digest"]:
        proposal.pop(name, None)
    new_decision = f.record("decision", proposal, f.proposal["entity_id"])
    request = {
        "scope": "reconsideration",
        "targets": [new_decision],
        "terms": {},
        "question": "Media limitations changed the exact fixture strategy/experiment bundle. Real approval is not inferred.",
        "status": "requested",
    }
    from tools.contracts import target_digest

    request["target_digest"] = target_digest("reconsideration", [new_decision], f.records(), {})
    approval_request = f.record("approval", request)
    return {
        "claim_ref": claim,
        "research_plan_ref": new_plan,
        "question_ref": question,
        "promise_refs": promises,
        "experiment_ref": new_experiment,
        "strategy_refs": new_strategies,
        "decision_ref": new_decision,
        "approval_request_ref": approval_request,
    }
