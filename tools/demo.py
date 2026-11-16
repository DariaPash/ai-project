"""Read-only overview of the actual saved project, not a canned success demo."""

import argparse
import json
from pathlib import Path

from .errors import CoreError
from .graph import agenda, impact
from .store import Store, now


def main():
    parser = argparse.ArgumentParser(
        description="Show the actual saved strategy case; no tests, paid API or mock results."
    )
    parser.add_argument(
        "--project", help="Project directory containing cases/; default: latest working case from development receipts"
    )
    parser.add_argument("--case", default="test-core")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.project:
        project = Path(args.project).resolve()
    else:
        progress = json.loads((root / "planning/progress.json").read_text())
        receipts = []
        for step in ("06", "05", "04"):
            for run in sorted((root / "planning/evidence" / step).glob("run-*")):
                for name in ("working-memory-session.json", "runtime-review-start.json", "processing-receipt.json"):
                    path = run / name
                    if path.exists():
                        receipts.append((path.stat().st_mtime, json.loads(path.read_text())))
        if not receipts:
            raise CoreError("DEMO_CASE", "No saved case receipt; use --project explicitly", 3)
        project = root / max(receipts, key=lambda pair: pair[0])[1]["project"]
    with Store(project, args.case) as store:
        status = store.status()
        snapshot, _, _ = store._load()
        records = store.records(snapshot)
        active = [r for r in records.values() if snapshot["active"].get(r["id"]) == r["revision"]]
        kinds = lambda kind: [
            {
                "ref": {"case_id": r["case_id"], "entity_id": r["id"], "revision": r["revision"]},
                "payload": r["payload"],
                "lineage_roots": r["lineage_roots"],
            }
            for r in active
            if r["kind"] == kind
        ]
        result = {
            "title": "Стратег с проверяемыми основаниями — фактическое сохранённое состояние",
            "at": now(),
            "case": args.case,
            "namespace": snapshot["namespace"],
            "synthetic_materials": True,
            "case_revision": status["case_revision"],
            "snapshot_digest": status["data"]["snapshot_digest"],
            "awaiting_human": snapshot["runtime"]["awaiting_human"],
            "next_action": snapshot["runtime"]["next_action"],
            "sources": [
                {"id": r["id"], "format": r["payload"]["format"], "origin": r["payload"]["origin"]}
                for r in active
                if r["kind"] == "source"
            ],
            "options": kinds("option"),
            "strategies": kinds("strategy"),
            "decisions": kinds("decision"),
            "independent_reviews": kinds("review"),
            "memory_indexes": kinds("memory_index"),
            "agenda": agenda(store, now())["data"],
            "limits": [
                "Не бизнес-исследование: учебные материалы и модельные гипотезы",
                "Реальное согласование решения не получено",
                "STT/listening, официальный бриф и вторая среда не подтверждены",
                "MCP/API недоступны; local semantic memory English only",
                "Новые тесты/benchmark отключены пользователем",
                "Ничего не опубликовано и не отправлено",
            ],
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
