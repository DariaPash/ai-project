"""Read-only concise terminal views of actual immutable case records, not slides."""

import json
from pathlib import Path
import sys
import textwrap

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.store import Store
from tools.contracts import key


def line(text):
    print(textwrap.fill(str(text), width=106, subsequent_indent="  "))


def main():
    scene = sys.argv[1]
    with Store(Path.cwd(), "test-core") as store:
        snapshot, _, _ = store._load()
        records = store.records(snapshot)
        active = lambda kind: [
            r for r in records.values() if r["kind"] == kind and snapshot["active"].get(r["id"]) == r["revision"]
        ]
        title = lambda r: f"{r['id']}@{r['revision']}"
        print("SAVED CASE / synthetic_fixture / not a new generation or real business approval")
        if scene == "request":
            print((Path.cwd() / "cases/test-core/brief.md").read_text().strip())
            print("Plan and open questions, read from committed records:")
            for r in active("research_plan"):
                line(title(r) + " " + json.dumps(r["payload"], ensure_ascii=False)[:800])
            for text in snapshot["runtime"].get("open_questions", []):
                line("- " + text)
        elif scene == "sources":
            for identity in ("SRC-001@1", "EXT-001@1", "CLM-001@1", "CAL-001@1", "CAL-003@1"):
                r = records[identity]
                p = r["payload"]
                print("\n" + identity + " / " + r["kind"])
                value = p.get("text", p.get("statement", p.get("result", p.get("sha256"))))
                line(json.dumps(value, ensure_ascii=False)[:440])
            print("Synthetic source numbers are not measured market demand or causal effects.")
        elif scene == "options":
            for r in active("option"):
                p = r["payload"]
                print("\n" + title(r) + " / " + p["option_type"])
                line(p["mechanism"])
                line("Refusal: " + str(p.get("refusal", p.get("risks", [])))[:150])
            print("Fixture choice is not a real product-owner decision.")
        elif scene in ("product", "communication"):
            for r in active("strategy"):
                if r["payload"]["strategy_type"] != scene:
                    continue
                print(title(r) + " / " + scene + " / saved proposal")
                for name, text in r["payload"]["sections"].items():
                    line(name + ": " + text[:200])
            print("No automatic product export or guaranteed business effect is claimed.")
        elif scene == "experiment":
            for r in active("experiment"):
                print(title(r))
                line(json.dumps(r["payload"], ensure_ascii=False)[:1500])
            for r in active("decision"):
                line(title(r) + " status=" + r["payload"]["status"])
            print("Real baseline, consent and product-owner approval remain missing.")
        elif scene == "review":
            for r in active("review"):
                p = r["payload"]
                print(title(r) + " / " + p["verdict"])
                line("Actual saved separate-context report; scope and limitations:")
                line(json.dumps(p, ensure_ascii=False)[:1400])
            print("Delivery/schema validation and static review are not full acceptance.")
        elif scene == "integrations":
            for identity in ("EXT-017@1", "EXT-020@1", "RTE-002@1"):
                r = records[identity]
                p = r["payload"]
                print("\n" + identity + " / " + r["kind"])
                if r["kind"] == "extraction":
                    line(p["text"][:500])
                else:
                    line(json.dumps(p, ensure_ascii=False)[:650])
            print("STT listening unverified; MCP text synthetic; RTE tokens unknown/$10 reserve.")
        elif scene == "codex":
            if not (ROOT / "planning/progress.json").is_file():
                print("Historical Codex receipt is not included here; no new continuation was run.")
                return
            progress = json.loads((ROOT / "planning/progress.json").read_text())
            saved = (
                ROOT
                / progress["steps"]["06"].get("latest_run", progress["active_run"])
                / "actual-codex-continuation.json"
            )
            report = json.loads(saved.read_text())
            line("HISTORICAL ACTUAL Codex continuation; no new model call in this video.")
            line("Status: " + report["status"] + " / response " + str(report.get("response_ref")))
            line("Actual provider usage: " + json.dumps(report["actual_provider_usage"]))
            answer = json.loads((saved.parent / "codex-final-response.txt").read_text())
            line("Proposed delta: " + answer["proposed_capability_delta"]["product_boundary"])
            line("Next: " + answer["next_action"])
            print("Separate local branch. Old strategy bytes and business-H remain unchanged.")
        else:
            raise SystemExit("Unknown read-only view")


if __name__ == "__main__":
    main()
