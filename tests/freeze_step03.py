"""Freeze explicit observer key before any interview/strategy model execution.

This module writes data only and is not imported by strategy/smoke generators.
"""

import json
from tools.contracts import sha
from tools.development import ROOT, now, write_json


def main():
    progress = json.loads((ROOT / "planning/progress.json").read_text())
    assert "/03/" in progress["active_run"]
    folder = ROOT / "tests/fixtures/research"
    dest = ROOT / progress["active_run"] / "fixture-freeze.json"
    assert not dest.exists(), "Frozen observer key exists; inspect instead of replacing"
    oracle = {
        "origin": "synthetic_fixture",
        "observer_only": True,
        "theme": "Manual verification can delay completion, not universal across the corpus",
        "quotes": [
            {
                "file": "interview-1.txt",
                "line": 3,
                "text": "Участник: После встречи я ещё двадцать минут сверял, кто за что отвечает.",
            },
            {
                "file": "interview-2.txt",
                "line": 3,
                "text": "Участник: Я откладываю итоговое письмо, потому что вручную проверяю договорённости.",
            },
        ],
        "counterexample": {
            "file": "interview-3.txt",
            "line": 3,
            "text": "Участник: Я сразу отправил короткий список задач, перепроверка не задержала работу.",
        },
        "capability": {"file": "capabilities.txt", "line": 3, "text": "Automatic export is planned, not available."},
        "defects": {
            "guide": "leading_solution_confirmation",
            "options": "channels_are_not_four_product_mechanisms",
            "promise": "contradicts_planned_capability",
        },
        "fieldwork_conducted": False,
        "population_prevalence": None,
    }
    for item in oracle["quotes"] + [oracle["counterexample"], oracle["capability"]]:
        assert (folder / item["file"]).read_text().splitlines()[item["line"] - 1] == item["text"]
    write_json(folder / "oracle.json", oracle)
    files = {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in sorted(folder.iterdir()) if p.is_file()}
    for p in [ROOT / "tests/specs/03-strategy.json", ROOT / "tests/rubrics/03-semantic.md"]:
        files[str(p.relative_to(ROOT))] = sha(p.read_bytes())
    write_json(
        folder / "manifest.json",
        {
            "schema_version": 1,
            "origin": "synthetic_fixture",
            "rights": {"processing": True, "external_transfer": False, "publication": False},
            "files": files,
            "limitations": "Artificial anonymized text; no real interviewee or consent receipt; observer key kept out of synthesis input bundles",
        },
    )
    files[str((folder / "manifest.json").relative_to(ROOT))] = sha((folder / "manifest.json").read_bytes())
    write_json(
        dest,
        {
            "frozen_at": now(),
            "files": files,
            "observer_key_sha256": sha((folder / "oracle.json").read_bytes()),
            "method": "Literal hand-specified quotes, not production analysis output",
        },
    )
    print(json.dumps({"freeze": str(dest.relative_to(ROOT)), "files": len(files)}))


if __name__ == "__main__":
    main()
