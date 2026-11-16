"""Explicit structured fixture proposals, never claimed as actual model execution.

No observer oracle is imported/read here. Actual host role logs live separately.
"""

import copy
import json
import shutil
import uuid

from tools.contracts import business_digest, key, sha, target_digest
from tools.research_contracts import strategy_manifest
from tools.safeio import canonical
from tools.sources import ingest
from tools.store import Store, unknown_usage
from .helpers import PROJECT, cli, record_cli, write_request
from .step02_helpers import prepare, source_spec, input_refs, metric_spec

SPEC = json.loads((PROJECT / "tests/specs/03-strategy.json").read_text())


class Fixture:
    def __init__(self, root, case="test-core", via_cli=False):
        self.root, self.case, self.via_cli = root, case, via_cli

    def status(self):
        with Store(self.root, self.case) as store:
            return store.status()

    def record(self, kind, payload, entity_id=None):
        if self.via_cli:
            if kind == "approval":
                filename = write_request(
                    self.root, {"payload": payload, **({"id": entity_id} if entity_id else {})}, case=self.case
                )
                command = "request" if payload["status"] == "requested" else "record"
                return cli(
                    self.root,
                    "approval",
                    command,
                    "--case",
                    self.case,
                    "--file",
                    filename,
                    "--expected-revision",
                    self.status()["case_revision"],
                )[1]["data"]["ref"]
            return record_cli(self.root, kind, payload, case=self.case, entity_id=entity_id)["data"]["ref"]
        with Store(self.root, self.case) as store:
            return store.record(
                kind, {"payload": payload, **({"id": entity_id} if entity_id else {})}, store.status()["case_revision"]
            )["data"]["ref"]

    def records(self):
        with Store(self.root, self.case) as store:
            snap, _, _ = store._load()
            return store.records(snap)

    def artifact(self, raw, parents=(), origin="synthetic_fixture", media="application/json", processing="algorithm"):
        with Store(self.root, self.case) as store:
            return store.record(
                "artifact",
                {
                    "payload": {
                        "sha256": sha(raw),
                        "size": len(raw),
                        "media_type": media,
                        "origin": origin,
                        "parent_refs": list(parents),
                        "processing_kind": processing,
                    }
                },
                store.status()["case_revision"],
                artifacts={sha(raw): raw},
            )["data"]["ref"]

    def approve(self, scope, targets, terms=None, status="approve"):
        terms = terms or {}
        payload = {
            "scope": scope,
            "targets": targets,
            "terms": terms,
            "target_digest": target_digest(scope, targets, self.records(), terms),
            "question": "Technical fixture only: select exact proposal?",
            "status": "requested",
        }
        request = self.record("approval", payload)
        receipt = self.artifact(b"Explicit fixture approval transcript; no real person or live H.", media="text/plain")
        return self.record(
            "approval",
            {
                **payload,
                "status": status,
                "request_ref": request,
                "approval_kind": "fixture",
                "actor": "fixture-not-human",
                "channel": "technical_fixture",
                "timestamp": "2026-11-08T00:00:00Z",
                "evidence_ref": receipt,
            },
        )

    def quote(self, name, line):
        result = self.imports[name]
        ext = self.records()[key(result["extraction_ref"])]["payload"]
        fragment = next(f for f in ext["fragments"] if f["coordinates"].get("start") == line)
        return {
            "ref": result["source_ref"],
            "locator": {
                "source_revision": result["source_ref"]["revision"],
                "source_hash": result["source_sha256"],
                "extraction_id": result["extraction_ref"]["entity_id"],
                "kind": fragment["kind"],
                "coordinates": fragment["coordinates"],
                "exact_quote": fragment["text"],
            },
        }

    def simulation(self, role, parents):
        payload = {
            "contract_version": 3,
            "role": role,
            "execution_id": str(uuid.uuid5(uuid.NAMESPACE_URL, "technical-fixture-role:" + role)),
            "conditions": ["Explicit artificial contract fixture; no actual model call"],
            "known_unknowns": ["Real demand and real baseline unknown"],
            "input_refs": parents,
            "turns": [
                {"speaker": "interviewer", "text": "What constraint could invalidate this proposal?"},
                {
                    "speaker": "respondent",
                    "text": "A synthetic objection, not a real person's answer: privacy may prevent export.",
                },
                {"speaker": "interviewer", "text": "What actual observation would resolve that?"},
                {"speaker": "respondent", "text": "Seek consent and observe a real permitted local workflow."},
            ],
            "objections": ["Fixture opinion is not empirical corroboration"],
            "real_validation": "Consent-based observation with real users, not another synthetic vote",
            "execution": {
                "mode": "fixture",
                "model": None,
                "started_at": "2026-11-08T00:00:00Z",
                "ended_at": "2026-11-08T00:00:01Z",
                "context_independence": "not_independent",
                "usage": unknown_usage(),
            },
        }
        transcript = self.artifact(canonical(payload), parents, origin="model_simulation")
        return self.record("simulation", {**payload, "transcript_ref": transcript})

    def strategy(self, kind, selected, choice, basis, sections, text=None, entity_id=None):
        text = text or (
            "# "
            + kind
            + " strategy — SYNTHETIC TECHNICAL PROPOSAL\n\n"
            + "\n\n".join(f"## {name}\n{value}" for name, value in sections.items())
            + "\n"
        )
        p = {
            "contract_version": 3,
            "strategy_type": kind,
            "text": text,
            "basis_refs": basis,
            "selected_option_ref": selected,
            "option_choice_ref": choice,
            "sections": sections,
            "content_sha256": sha(text.encode()),
        }
        parents = [selected, choice, *basis]
        p["artifact_ref"] = self.artifact(text.encode(), parents, media="text/markdown")
        p["manifest_ref"] = self.artifact(canonical(strategy_manifest(p)), parents)
        return self.record("strategy", p, entity_id)


def build_research(root, case="test-core", via_cli=False, quantitative=True):
    prepare(root)
    shutil.copytree(
        PROJECT / "tests/fixtures/research",
        root / "tests/fixtures/research",
        ignore=shutil.ignore_patterns("oracle.json", "manifest.json"),
    )
    f = Fixture(root, case, via_cli)
    with Store(root, case) as store:
        store.init("test")
    f.brief = f.record(
        "brief",
        {
            "goal": "Technical question: should the fictional review-first workflow stay, improve, refocus or close?",
            "constraints": [
                "Only synthetic inputs; not approved demo or fieldwork",
                "No real sales baseline, no automatic export, no live permissions",
            ],
            "open_questions": [
                "Which real event definition is applicable?",
                "Would local review remove a real delay?",
                "Who could approve the actual product decision?",
            ],
        },
    )
    questions = []
    for text in [
        "Does manual verification delay the completed job?",
        "Does privacy prevent transferring the workflow?",
        "Which activation event/window and real baseline would apply?",
    ]:
        questions.append(
            f.record(
                "question",
                {
                    "contract_version": 3,
                    "text": text,
                    "affected_choice": "Improve local review versus retain/refocus/close the direction",
                    "priority": "high",
                    "minimal_evidence": "Located contrasting corpus passages, then actual consent-based observation",
                    "stop_condition": "Stop when the decision-changing uncertainty is resolved or permission/budget ends",
                    "outcome": {
                        "status": "gap",
                        "text": "Synthetic corpus can test tooling but cannot resolve real market demand",
                        "basis_refs": [],
                    },
                },
            )
        )
    criteria = {k: copy.deepcopy(SPEC["criteria"][k]) for k in ("scale", "weights", "sensitivity_weights")}
    f.plan = f.record(
        "research_plan",
        {
            "contract_version": 3,
            "decision_question": "Which of four product mechanisms deserves a real validation, not an automatic business commitment?",
            "question_refs": questions,
            "criteria": criteria,
            "limitations": [
                "Weights and scores are fictional judgments fixed before comparison, not a measured utility function"
            ],
        },
    )
    f.guide_payload = {
        "contract_version": 3,
        "research_plan_ref": f.plan,
        "questions": [
            {
                "question": "Вспомните последний случай завершения итогов встречи. Что вы делали?",
                "intent": "Последнее конкретное поведение, не согласие с предложенным решением",
            },
            {
                "question": "Что произошло между черновиком и отправкой?",
                "intent": "Барьер и альтернативные объяснения задержки",
            },
            {
                "question": "Были ли случаи без задержки и какие ограничения на инструменты действовали?",
                "intent": "Контрпример, альтернативы и privacy без обещания продукта",
            },
        ],
        "consent_protocol": "Для реальных бесед сначала отдельное согласие на запись/обработку; здесь учебный обезличенный корпус без реальных интервьюируемых",
        "limitations": ["Fieldwork not conducted; neutral wording needs semantic review, not just schema"],
    }
    f.guide = f.record("interview_guide", f.guide_payload)
    f.imports = {}
    for name in SPEC["input_corpus"]:
        _, profile = source_spec("policy-v2")
        profile["title"] = "Technical research fixture " + name
        profile["primary_publication"] = "fixture-policy" if name.startswith("definition") else name
        path = "tests/fixtures/research/" + name
        if via_cli:
            request = write_request(root, profile, case=case, name="source-" + name + ".json")
            saved = cli(
                root,
                "ingest",
                "--case",
                case,
                "--path",
                path,
                "--spec",
                request,
                "--expected-revision",
                f.status()["case_revision"],
            )[1]
        else:
            with Store(root, case) as store:
                saved = ingest(store, path, profile, store.status()["case_revision"])
        f.imports[name] = saved["data"]
    f.analysis_payload = {
        "contract_version": 3,
        "research_plan_ref": f.plan,
        "guide_ref": f.guide,
        "corpus_refs": [f.imports[name]["source_ref"] for name in SPEC["input_corpus"][:3]],
        "corpus_kind": "synthetic_fixture",
        "fieldwork_conducted": False,
        "themes": [
            {
                "theme": "Manual checking can delay handoff, but this is not universal",
                "quotes": [f.quote("interview-1.txt", 3), f.quote("interview-2.txt", 3)],
                "counterexample": f.quote("interview-3.txt", 3),
                "interpretation": "The technical corpus suggests testing review effort; it does not prove real prevalence or demand",
                "alternative": "Delay may be caused by coordination/permission rather than the editor itself",
                "real_validation": "Observe actual permitted workflows, including quick completions, after consent",
            }
        ],
        "limitations": [
            "Structured fixture proposal, not actual model interview analysis",
            "Three artificial transcripts are not a population sample; no fieldwork",
        ],
    }
    f.analysis = f.record("interview_analysis", f.analysis_payload)
    f.conflict = f.record(
        "claim",
        {
            "text": "Synthetic activation definitions differ: 24h meeting creation versus 7-day report export; same publication group, not independent evidence",
            "type": "interpretation",
            "status": "unverified",
            "origin": "synthetic_fixture",
            "evidence": [f.quote("definition-old.txt", 2), f.quote("definition-new.txt", 2)],
            "counterevidence": [],
            "basis_refs": [f.analysis],
            "limitations": ["Declared dates, not independently established publication dates; no pooling of rates"],
        },
    )
    f.calculations = []
    if quantitative:
        from tools.calculations import metrics

        inputs = input_refs(root)
        for operation in ("cohorts", "funnel", "economics", "scenarios"):
            with Store(root, case) as store:
                result = metrics(store, metric_spec(operation, inputs), store.status()["case_revision"])
            f.calculations.append(result["data"]["calculation_ref"])
    return f


def add_options(f, simulations=None):
    f.simulations = simulations or [
        f.simulation(role, [f.analysis])
        for role in ("time-constrained manager", "privacy-constrained operator", "evidence-demanding buyer")
    ]
    mechanisms = {
        "status_quo": "Keep the existing local manual template; accept waiting and coordination cost while obtaining a real baseline",
        "improve": "Improve local review of task owners before manual handoff, not automated sending",
        "refocus": "Exit meeting-draft generation and recording processing entirely; become an offline completeness checker for already agreed task lists in teams forbidden to process recordings",
        "close": "Freeze new onboarding, notify affected users, migrate/export permitted local data and retain support obligations before shutdown",
    }
    scores = {
        "status_quo": {"value": 1, "privacy": 4, "reversibility": 4},
        "improve": {"value": 3, "privacy": 4, "reversibility": 3},
        "refocus": {"value": 2, "privacy": 3, "reversibility": 2},
        "close": {"value": 0, "privacy": 4, "reversibility": 1},
    }
    cards = {
        "status_quo": (
            "Current permitted local-template users",
            "Finish summaries with no new software investment",
            "Waiting/coordination dominates review, or the proposed gain is below the predeclared useful threshold",
            "Stop preserving the process if recurring quality loss exceeds its acceptable guardrail",
            "Observe the existing flow first, including waiting cost",
        ),
        "improve": (
            "Teams whose manual task-owner verification is the bottleneck and who may edit drafts locally",
            "Review task owners before manual handoff without automatic sending",
            "A permitted comparison clears the proposed 10% useful reduction without losing accuracy or increasing privacy risk",
            "Reject if the improvement is below the useful threshold or merely shifts work to colleagues",
            "Compare local review-first versus current template, separating review from waiting",
        ),
        "refocus": (
            "Teams with already agreed structured task lists, but no permission to process meeting recordings; exclude teams needing draft generation from recordings",
            "Check completeness/ownership of an existing agreed list offline, not summarize a meeting",
            "The narrower non-recording job is admissible and useful whereas both meeting-draft mechanisms are inadmissible or unnecessary",
            "Reject if obtaining a structured agreed list itself causes more rework than the checker saves",
            "Test only prepared task lists; exclude recording ingestion and draft generation",
        ),
        "close": (
            "Existing users and the support/migration owner; no new onboarding audience",
            "Safely leave the direction while preserving data access and obligations",
            "No admissible bounded mechanism meets the useful/quality threshold and remaining support/migration costs are fundable",
            "Do not shut down while data migration, notice or support duties are unresolved",
            "Inventory obligations and verify a reversible migration before disabling service",
        ),
    }
    f.options = []
    for option_type in SPEC["required_option_types"]:
        f.options.append(
            f.record(
                "option",
                {
                    "contract_version": 3,
                    "option_type": option_type,
                    "mechanism": mechanisms[option_type],
                    "audience": cards[option_type][0],
                    "job": cards[option_type][1],
                    "research_plan_ref": f.plan,
                    "basis_refs": [f.analysis, f.conflict, *f.simulations, *f.calculations],
                    "assumptions": ["Real demand, implementation costs and causal effects are unknown"],
                    "economics_range": "Unknown real effect; synthetic E base net 30000 and higher-cost net 10000 RUB/month only illustrate sensitivity, not this mechanism's forecast",
                    "horizon": "One bounded validation cycle, time budget to be approved",
                    "reversibility": "Preserve current local data and support; close requires migration before irreversible removal",
                    "risks": [
                        "Privacy/coordination may dominate review effort",
                        "Fictional scores are not measured preferences",
                    ],
                    "strongest_objection": "No actual customer observation yet demonstrates that this mechanism solves the main constraint",
                    "wins_when": cards[option_type][2],
                    "refusal": cards[option_type][3],
                    "minimal_test": cards[option_type][4],
                    "scores": scores[option_type],
                },
            )
        )
    f.choice_terms = {"contract_version": 3, "research_plan_ref": f.plan, "selected_option_ref": f.options[1]}
    f.choice_targets = [*f.options, f.plan]
    criteria = f.records()[key(f.plan)]["payload"]["criteria"]
    f.sensitivity = {
        "origin": "synthetic_fixture",
        "method": "Weighted sums of fictional predeclared 0..4 scores, not measured utility or a human choice",
        "sets": [
            {
                "weights": weights,
                "scores": {
                    kind: sum(weights[name] * values[name] for name in weights) for kind, values in scores.items()
                },
            }
            for weights in [criteria["weights"], *criteria["sensitivity_weights"]]
        ],
    }
    f.sensitivity_ref = f.artifact(canonical(f.sensitivity), f.choice_targets)
    return f


def complete_fixture(f):
    f.choice = f.approve("option_choice", f.choice_targets, f.choice_terms)
    f.promise = f.record(
        "promise",
        {
            "contract_version": 3,
            "text": "Только проверка ручного черновика; автоматический экспорт пока запланирован, не доступен",
            "capability_status": "planned",
            "basis_refs": [f.imports["capabilities.txt"]["source_ref"]],
            "capability_evidence": f.quote("capabilities.txt", 3),
            "qualification": "Не обещать автоматическую отправку, скорость или эффект, которых не наблюдали",
        },
    )
    f.experiment_payload = {
        "contract_version": 3,
        "hypothesis": "A local review checklist may reduce avoidable rework, not necessarily total coordination time",
        "baseline": None,
        "baseline_status": "unknown",
        "baseline_reason": "No real measured completion baseline; synthetic Q/E is not a substitute",
        "metric": "Time to correct agreed task summary, with accuracy guardrail",
        "useful_delta": "Proposed technical decision threshold: at least 10% lower median time to a correct agreed summary versus the measured baseline/comparison, with no accuracy loss. This is a fictional proposed threshold, not an observed effect or real H approval.",
        "comparison": "Counterbalanced permitted local template versus review-first prototype",
        "unit": "Completed task summary by a consenting real participant",
        "horizon": "Proposed 14-calendar-day technical protocol: first 4 days measure permitted baseline; next 10 days counterbalance the two local workflows. No real pilot starts before H/consent/resource approval.",
        "guardrails": ["No external transfer", "No loss of task-owner accuracy"],
        "stop_conditions": [
            "Stop for privacy violation, missing consent or exhausted approved budget",
            "If no valid baseline exists by day 4, stop the comparison rather than impute zero",
        ],
        "reconsideration": [
            "Retain status quo if the observed benefit is too small; reconsider scope/closure if adoption constraints dominate"
        ],
        "limitations": ["Technical proposal; no measured baseline, effect or statistical power claim"],
    }
    f.experiment = f.record("experiment", f.experiment_payload)
    f.product_sections = {
        "segment_job": "Teams permitted to review summaries locally, checking owners before manual handoff",
        "alternatives": "Existing local editor/template, manual coordination, or no new service",
        "choice_refusals": "Fixture-selected improve: narrow review-first workflow; refuse cloud recording ingestion and automatic sending",
        "value_economics": "Benefit hypothesis is less rework, not guaranteed speed or demand; real costs/revenue unknown; synthetic E ranges are illustrative only",
        "dependencies": "Consent, local data permissions, a real baseline, bounded implementation budget and accurate task mapping",
        "next_experiment": "Use the pinned comparison and privacy/accuracy stop conditions before rollout",
    }
    f.communication_sections = {
        "contact": "When a team prepares a manually reviewed summary",
        "barrier": "Uncertain accuracy and privacy, not lack of an advertising channel",
        "message": "Explore a local review-first draft, not automatic export",
        "proof": "Only synthetic tooling evidence exists; request a permitted observation, not a claim of market success",
        "channel_roles": "Internal demo explains limitations; a checklist helps evaluation; direct contact obtains consent, not automatic promotion",
        "target_action": "Consent to one bounded task observation, not commit to purchase",
        "measurement": "Check understanding of planned versus available and compare task quality after consent",
        "forbidden_promises": "No automatic export/sending, guaranteed time saving, real retention gain or proven demand",
    }
    basis = [f.analysis, f.conflict, *f.simulations, *f.calculations, f.experiment]
    f.product = f.strategy("product", f.options[1], f.choice, basis, f.product_sections)
    f.communication = f.strategy("communication", f.options[1], f.choice, [*basis, f.promise], f.communication_sections)
    f.decision_payload = {
        "contract_version": 3,
        "status": "pending",
        "selected_option_ref": f.options[1],
        "option_choice_ref": f.choice,
        "rejected_refs": [f.options[i] for i in (0, 2, 3)],
        "basis_refs": [f.analysis, f.conflict, *f.simulations, *f.calculations],
        "strategy_refs": [f.product, f.communication],
        "experiment_ref": f.experiment,
        "promise_refs": [f.promise],
        "owner": "unassigned",
        "due": "unknown",
        "metrics": ["Unknown real baseline; measure correct completion time and quality before comparing"],
        "triggers": ["Actual evidence contradicts the manual-review hypothesis", "Privacy permission/budget changes"],
    }
    f.proposal = f.record("decision", f.decision_payload)
    f.final = f.approve("final_decision", [f.proposal])
    f.confirmed = f.record(
        "decision",
        {
            **f.decision_payload,
            "status": "confirmed",
            "approved_proposal_ref": f.proposal,
            "approval_ref": f.final,
            "business_content_digest": business_digest(f.decision_payload),
        },
        f.proposal["entity_id"],
    )
    return f
